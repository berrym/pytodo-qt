# pyqtgraph + pytest-qt Teardown Race Guide

This document details the challenges and solutions for running a PyQt6 + pyqtgraph application's test suite under pytest-qt without intermittent teardown crashes. The failure is a pyqtgraph internal bug that surfaces probabilistically based on widget construction/destruction timing; the fixes here are general and apply to any pyqtgraph + pytest-qt project.

## The Problem

pyqtgraph charts (`pg.PlotWidget`) own a `PlotItem`, which owns a `ViewBox` and one `AxisItem` per axis. Under pytest-qt, widgets are constructed and destroyed rapidly across the test session. When a chart widget is destroyed, Qt's C++ side deletes the `ViewBox` and `AxisItem` together — but PyQt6's Python wrappers and Qt's deferred-event queue do not always agree on the ordering.

`AxisItem.boundingRect()` calls `linkedView().boundingRect()` with no guard. If a queued layout/paint event causes `boundingRect()` to run *after* the linked `ViewBox`'s C++ object has been deleted, the Python wrapper still resolves (a sip/PyQt6 quirk — the wrapper object exists, the underlying C++ does not), and the call into the dead object raises:

```
RuntimeError: wrapped C/C++ object of type ViewBox has been deleted
```

### The Specific Error

The exception fires inside the Qt event loop during pytest-qt teardown, so the **test itself passes**, then teardown escalates the caught exception into a failure:

```
_ ERROR at teardown of TestSomething.test_something _
TEARDOWN ERROR: Exceptions caught in Qt event loop:

Traceback (most recent call last):
  File ".../pyqtgraph/graphicsItems/AxisItem.py", line 960, in boundingRect
    linkedView.mapRectToItem(self, linkedView.boundingRect())
  File ".../pyqtgraph/graphicsItems/ViewBox/ViewBox.py", line 480, in boundingRect
    br = super().boundingRect()
  File ".../pyqtgraph/graphicsItems/GraphicsWidget.py", line 60, in boundingRect
    geometry = self.geometry()
RuntimeError: wrapped C/C++ object of type ViewBox has been deleted
```

The traceback is entirely inside pyqtgraph — no application code is in the chain. pytest-qt's event-loop exception filter is what turns the otherwise-swallowed exception into a non-zero exit.

### Why It Is So Hard to Pin Down

- **Probabilistic.** It depends on the exact interleaving of Qt's deferred-delete events and queued layout events. The same test suite passes on most platform/Python combinations and fails on one.
- **Timing-sensitive.** Unrelated changes that shift construction timing — a font change, an extra widget, a different default — move the suite across the threshold. The failure can appear to be "caused by" a commit that never touched charts.
- **Misattributed.** The failing test named in the report is whichever test happened to be tearing down when a *different, earlier* test's chart fired its queued event. Chasing the named test leads nowhere.
- **Platform-skewed.** In this project it reproduced consistently on Windows + Python 3.11 while every other matrix (Ubuntu/macOS × 3.11/3.12, Windows 3.12) stayed green.

## The Solution

Three layers, applied in order of when they were added. Layer 3 is the load-bearing fix; layers 1 and 2 are defense-in-depth that reduce the race window and are good practice independently.

### 1. Lazy PlotWidget Construction

Never construct a `pg.PlotWidget` in a widget's `__init__`. Construct it on first use — when the chart is first shown or first rebuilt — and swap it in for a placeholder. A chart that is never displayed (a dialog built but not shown, an off-screen `QStackedWidget` page) then never instantiates a `PlotWidget` at all and leaves no deferred events behind.

For a chart with an external rebuild trigger (e.g. a view-switcher calling `rebuild()`):

```python
def __init__(self, ...):
    ...
    self._plot = None
    self._plot_placeholder = QWidget()
    self._layout.addWidget(self._plot_placeholder, 1)

def _ensure_plot(self) -> None:
    if self._plot is not None:
        return
    import pyqtgraph as pg
    self._plot = pg.PlotWidget()
    # ... configure axes, connect scene signals ...
    self._layout.replaceWidget(self._plot_placeholder, self._plot)
    self._plot_placeholder.deleteLater()
```

For a static, one-shot chart with no rebuild trigger, defer to the first `showEvent` instead:

```python
def __init__(self, data, parent=None):
    super().__init__(parent)
    self._data = data
    self._built = False
    self._layout = QVBoxLayout(self)
    self._plot_placeholder = QWidget()
    self._plot_placeholder.setFixedHeight(...)  # reserve layout space
    self._layout.addWidget(self._plot_placeholder)

def showEvent(self, a0):  # noqa: N802
    super().showEvent(a0)
    if not self._built:
        self._build_chart()
        self._built = True
```

This alone is **not sufficient** — a chart that *is* shown during a test still queues events that can fire after teardown — but it removes every never-shown chart from the race entirely and is the correct construction pattern regardless.

### 2. Drain Deferred Events Before Teardown

An autouse fixture that runs `QApplication.processEvents()` after the test body but before pytest-qt destroys the test's widgets. Pending layout/paint events then fire while the widgets are still alive.

```python
@pytest.fixture(autouse=True)
def _flush_qt_events_before_teardown(qtbot):
    yield
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
```

The `qtbot` dependency is load-bearing for ordering. pytest finalizes fixtures in reverse instantiation order; depending on `qtbot` makes this fixture instantiate *after* `qtbot` and therefore finalize *before* it, so `processEvents()` runs while `qtbot`'s registered widgets are still alive.

This narrows the window but is **also not sufficient on its own**: `qtbot`'s own `close()` + `deleteLater()` cleanup queues a further round of events that fire after this fixture has already run.

### 3. Guard `AxisItem.boundingRect` (the load-bearing fix)

Monkey-patch `pg.AxisItem.boundingRect` at test-collection time to swallow the dead-ViewBox `RuntimeError` and return an empty rect. The `AxisItem` is microseconds from destruction when this happens; the return value is never painted.

In `tests/conftest.py`, at module scope (runs once, at import):

```python
def _install_pyqtgraph_axisitem_teardown_guard() -> None:
    import pyqtgraph as pg
    from PyQt6.QtCore import QRectF

    original_boundingRect = pg.AxisItem.boundingRect

    def _safe_boundingRect(self):  # type: ignore[no-untyped-def]
        try:
            return original_boundingRect(self)
        except RuntimeError:
            return QRectF()

    pg.AxisItem.boundingRect = _safe_boundingRect  # type: ignore[method-assign]


_install_pyqtgraph_axisitem_teardown_guard()
```

This is the fix that actually closes the race. It addresses the bug at its exact location — the unguarded `linkedView()` access inside pyqtgraph — rather than trying to outrun the timing.

## Key Technical Details

### Why This Is a pyqtgraph Bug, Not an Application Bug

`AxisItem.boundingRect` resolves its linked view and immediately calls a method on it without checking whether the underlying C++ object is still alive. Under PyQt6, a wrapper whose C++ object has been deleted does not become `None` — it remains a live Python object that raises `RuntimeError` on any attribute access. pyqtgraph should guard this (e.g. with a `try`/`except RuntimeError` or a sip-validity check); upstream has not. Application code cannot prevent the deferred event from being queued, so patching the boundary where pyqtgraph and the test process meet is the correct place to fix it.

### Why the Patch Is Test-Only

The production binary does not import `tests/conftest.py`. In a real session the application runs a single long-lived `QApplication`; charts are destroyed only at process exit, where stderr is suppressed in bundled builds (`.app` on macOS, the frozen exe on Windows) and the process is exiting anyway. The race is overwhelmingly a pytest-qt artifact of rapid construct/destruct cycling. Keeping the guard in `conftest.py` fixes the test suite without altering shipped behavior. If the same `RuntimeError` is ever observed at application exit in a dev `uv run` (visible traceback in the venv terminal), the next step is an explicit cleanup in the main window's `closeEvent` that destroys the pyqtgraph widget hierarchy before the parent destruction cascade.

### Fixture Ordering Is Not Optional

An autouse event-flush fixture that does *not* depend on `qtbot` finalizes *after* `qtbot` (autouse fixtures instantiate first, finalize last), so its `processEvents()` runs on a graveyard of already-destroyed widgets and accomplishes nothing. The `qtbot` dependency is what makes it run at the right time.

## What Was Tried That Did Not Work

The diagnostic sequence matters because the dead ends are instructive:

1. **Lazy construction of the remaining eager chart.** Correct and worth doing, but did not stop the failure — the offending chart was one that *is* shown during its test.
2. **The event-flush fixture alone.** Shifted *which* test reported the teardown error (proving it touched the timing) but did not eliminate it — `qtbot`'s own cleanup queues a later round of events.
3. **Reverting the "suspect" commit.** Confirmed the commit was only a timing trigger, not a cause: reverting went green, re-applying went red with the identical pyqtgraph traceback. This established that chasing the commit or the named test was futile and the fix had to be at the pyqtgraph boundary.

Only the `boundingRect` guard (layer 3) closed it. Layers 1 and 2 remain because they are independently good practice and reduce the surface.

## Troubleshooting

### Teardown error names a test that has no charts

Expected. The deferred event belongs to a chart from an *earlier* test; the named test is just whichever one was tearing down when it fired. Do not investigate the named test. Confirm the traceback is the `AxisItem.boundingRect → ViewBox.boundingRect → geometry()` chain and apply the layer-3 guard.

### Green locally, red on one CI matrix only

Expected for this race — it is timing-probabilistic and platform-skewed. A local pass does not mean the suite is safe. Reproduce by running the full suite on the affected matrix, or simply apply the layer-3 guard, which is platform-independent.

### A new commit "broke" the chart tests but never touched charts

Expected. Any change that shifts construction timing (fonts, an added widget, a changed default) can move the suite across the probabilistic threshold. The commit exposed the latent race; it did not introduce it. The layer-3 guard removes the sensitivity.

### Removing the conftest guard

Do not remove `_install_pyqtgraph_axisitem_teardown_guard()` without re-verifying the affected CI matrix stays green across several runs. Until pyqtgraph guards `linkedView()` upstream, this patch is load-bearing.

## References

- [pyqtgraph AxisItem source](https://github.com/pyqtgraph/pyqtgraph/blob/master/pyqtgraph/graphicsItems/AxisItem.py)
- [pytest-qt: exceptions in virtual methods / event loop](https://pytest-qt.readthedocs.io/en/latest/virtual_methods.html)
- [PyQt6: lifetime of wrapped C++ objects](https://www.riverbankcomputing.com/static/Docs/PyQt6/gotchas.html)
