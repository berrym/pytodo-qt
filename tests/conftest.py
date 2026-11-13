"""Pytest configuration and fixtures."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_EXIT_PROBE = Path(__file__).parent / "exit_probe.py"
_EXIT_PROBE_TIMEOUT_SECONDS = 180


def _install_pyqtgraph_axisitem_teardown_guard() -> None:
    """Wrap pyqtgraph.AxisItem.boundingRect so a deleted linkedView ViewBox
    no longer escalates into a TEARDOWN ERROR.

    pyqtgraph's AxisItem.boundingRect calls linkedView().boundingRect();
    if the linked ViewBox has been C++-deleted but its Python wrapper
    still resolves (sip/PyQt6 quirk), the inner call raises
    RuntimeError("wrapped C/C++ object of type ViewBox has been
    deleted"). pytest-qt's event-loop exception filter escalates that
    into a teardown failure. The race surfaces on Windows 3.11 CI after
    subtle construction-timing changes; it is a pyqtgraph internal
    bug — the library should guard the linkedView access — but it has
    not been fixed upstream.

    The guard returns an empty QRectF when the ViewBox is dead. The
    AxisItem is moments away from destruction at this point, so the
    return value is never painted. Test-only — the production binary
    does not import this module.
    """
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


@pytest.fixture(autouse=True)
def _flush_qt_events_before_teardown(qtbot):
    """Drain Qt's deferred-event queue before pytest-qt destroys widgets.

    pyqtgraph's AxisItem queues internal layout/boundingRect events that
    fire asynchronously. If pytest-qt's qtbot deletes widgets before
    those events run, AxisItem.boundingRect ends up calling
    boundingRect on an already-deleted linked ViewBox and pytest-qt
    escalates the resulting RuntimeError into a TEARDOWN ERROR. The
    failure surfaced on Windows 3.11 specifically after subtle
    construction-timing changes; the same shape was previously
    addressed in 5ab2caf via lazy PlotWidget construction.

    Depending on qtbot forces ordering: this fixture is instantiated
    AFTER qtbot, so it tears down BEFORE qtbot. processEvents() runs
    after the test body completes but before qtbot's widget cleanup,
    so pending events fire on still-live widgets.
    """
    yield
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        app.processEvents()


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_teardown(item):
    """Destroy the widgets a test registered, once the test is torn down.

    pytest-qt closes each widget given to ``qtbot.addWidget`` and calls
    ``deleteLater`` on it. A deferred delete posted outside a running
    event loop is not carried out by ``processEvents``, which is all
    pytest-qt calls, so the widgets stay alive until Python's garbage
    collector frees their wrappers. That happens at an arbitrary later
    moment and piece by piece, and a pyqtgraph plot destroyed that way
    can be left with a layout request pending on items that are gone:
    the next ``processEvents`` then crashes the test run.

    Carrying out the deferred deletes here destroys each widget whole,
    parent first, at a known point between tests.
    """
    result = yield
    from PyQt6.QtCore import QCoreApplication, QEvent

    if QCoreApplication.instance() is not None:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return result


@pytest.fixture(scope="session")
def exit_report(tmp_path_factory: pytest.TempPathFactory) -> tuple[int, dict, str]:
    """Launch and quit the real application once per test session.

    Returns (exit code, the probe's report, the tail of stderr). The
    launch is offscreen, which has no system tray, and reads and writes
    nothing outside a scratch directory. See ``exit_probe.py`` for the
    report's fields.
    """
    root = tmp_path_factory.mktemp("app_launch")
    report_path = root / "report.json"
    env = dict(os.environ)
    env.update(
        XDG_CONFIG_HOME=str(root / "config"),
        XDG_DATA_HOME=str(root / "data"),
        XDG_STATE_HOME=str(root / "state"),
        QT_QPA_PLATFORM="offscreen",
        # No secrets are read from or written to the real system keyring.
        PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
    )
    result = subprocess.run(
        [sys.executable, str(_EXIT_PROBE), str(report_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=_EXIT_PROBE_TIMEOUT_SECONDS,
        check=False,
    )
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    return result.returncode, report, result.stderr[-4000:]


@pytest.fixture
def temp_app_dir():
    """Provide a temporary application directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_legacy_database():
    """Provide sample legacy database format."""
    return {
        "Shopping": [
            {"reminder": "Buy milk", "priority": 2, "complete": False},
            {"reminder": "Buy bread", "priority": 3, "complete": True},
        ],
        "Work": [
            {"reminder": "Email report", "priority": 1, "complete": False},
        ],
    }
