"""Tests for ``MainWindow``'s detail-panel visibility hook (#55).

Verifies the outer-window-geometry restore semantics. The fix routes
all visibility transitions through ``QDockWidget.visibilityChanged``
so every entry point — toolbar action, keyboard shortcut, the dock's
own close-X button, programmatic ``show()`` from
``_update_detail_panel`` — restores the window to the no-panel
baseline on hide. The baseline itself is tracked by ``resizeEvent``
on every window-size change.

Tests target the handlers as unbound methods called against a mock
``MainWindow`` instance — same pattern other tests in the suite use
for MainWindow methods. Avoids the cost of constructing a full
MainWindow + Database + config stack for what is purely arithmetic
on widget geometry.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from pytodo_qt.gui.main_window import MainWindow


def _make_mock_window(
    *,
    width: int = 1400,
    height: int = 900,
    panel_visible: bool = False,
    panel_width: int = 320,
    is_maximized: bool = False,
    is_fullscreen: bool = False,
    no_panel_width: int | None = None,
    has_action: bool = True,
    has_button: bool = True,
    show_in_progress: bool = False,
) -> MagicMock:
    """Construct a mock MainWindow with the geometry attrs the handlers read."""
    window = MagicMock()
    window.width.return_value = width
    window.height.return_value = height
    window.isMaximized.return_value = is_maximized
    window.isFullScreen.return_value = is_fullscreen
    window.isVisible.return_value = True
    window._no_panel_width = no_panel_width
    window._show_in_progress = show_in_progress
    window._detail_panel = MagicMock()
    window._detail_panel.isVisible.return_value = panel_visible
    window._detail_panel.width.return_value = panel_width
    if has_action:
        window._detail_panel_action = MagicMock()
    else:
        # MagicMock auto-creates attrs; explicitly remove so hasattr fails.
        del window._detail_panel_action
    if has_button:
        window._detail_btn = MagicMock()
    else:
        del window._detail_btn
    return window


class TestVisibilityChangedHide:
    """Hide branch resizes window back to no-panel baseline."""

    def test_hide_resizes_to_no_panel_width(self):
        """When the dock hides on a normal window, restore to the
        baseline tracked by resizeEvent."""
        window = _make_mock_window(width=1720, panel_visible=False, no_panel_width=1400)
        MainWindow._on_detail_panel_visibility_changed(window, False)
        window._schedule_no_panel_width_restore.assert_called_once()
        window._detail_panel_action.setChecked.assert_called_once_with(False)
        window._detail_btn.setChecked.assert_called_once_with(False)

    def test_hide_skipped_when_no_baseline_yet(self):
        """First-ever visibility transition during init fires
        visibilityChanged(False) before any baseline has been
        captured. Must not crash and must not resize to None."""
        window = _make_mock_window(width=1400, panel_visible=False, no_panel_width=None)
        MainWindow._on_detail_panel_visibility_changed(window, False)
        window.resize.assert_not_called()

    def test_hide_skipped_when_maximized(self):
        """Maximized windows can't resize without un-maximizing.
        Central widget naturally reclaims the freed dock slot."""
        window = _make_mock_window(
            width=2560,
            panel_visible=False,
            is_maximized=True,
            no_panel_width=1400,
        )
        MainWindow._on_detail_panel_visibility_changed(window, False)
        window.resize.assert_not_called()
        # Checkbox sync still runs.
        window._detail_panel_action.setChecked.assert_called_once_with(False)

    def test_hide_skipped_when_fullscreen(self):
        window = _make_mock_window(
            width=2560,
            panel_visible=False,
            is_fullscreen=True,
            no_panel_width=1400,
        )
        MainWindow._on_detail_panel_visibility_changed(window, False)
        window.resize.assert_not_called()


class TestVisibilityChangedShow:
    """Show branch only syncs checkbox state — no resize."""

    def test_show_does_not_resize(self):
        window = _make_mock_window(width=1400, panel_visible=True, no_panel_width=1400)
        MainWindow._on_detail_panel_visibility_changed(window, True)
        window.resize.assert_not_called()

    def test_show_syncs_action_and_button_checked(self):
        window = _make_mock_window(width=1720, panel_visible=True, no_panel_width=1400)
        MainWindow._on_detail_panel_visibility_changed(window, True)
        window._detail_panel_action.setChecked.assert_called_once_with(True)
        window._detail_btn.setChecked.assert_called_once_with(True)


class TestVisibilityChangedSyncWithoutOptionalAttrs:
    """``hasattr`` guards on toolbar action / button mean the handler
    works even before those attrs are wired up — important during init
    where visibilityChanged can fire from the initial ``hide()`` call
    before the toolbar is built."""

    def test_no_toolbar_action(self):
        window = _make_mock_window(
            width=1720, panel_visible=False, no_panel_width=1400, has_action=False
        )
        MainWindow._on_detail_panel_visibility_changed(window, False)
        # Should still resize and sync the button.
        window._schedule_no_panel_width_restore.assert_called_once()
        window._detail_btn.setChecked.assert_called_once_with(False)

    def test_no_inline_button(self):
        window = _make_mock_window(
            width=1720, panel_visible=False, no_panel_width=1400, has_button=False
        )
        MainWindow._on_detail_panel_visibility_changed(window, False)
        window._schedule_no_panel_width_restore.assert_called_once()
        window._detail_panel_action.setChecked.assert_called_once_with(False)

    def test_no_action_no_button(self):
        """During init both may be absent. Handler must not crash."""
        window = _make_mock_window(
            width=1400,
            panel_visible=False,
            no_panel_width=None,
            has_action=False,
            has_button=False,
        )
        MainWindow._on_detail_panel_visibility_changed(window, False)
        window.resize.assert_not_called()


class TestResizeEventTracking:
    """``resizeEvent`` keeps ``_no_panel_width`` current across all
    window-size changes so the visibilityChanged hide path has the
    right baseline to restore to."""

    def _make_resize_event(self, width: int, height: int) -> MagicMock:
        event = MagicMock()
        event.size.return_value = MagicMock(width=lambda: width, height=lambda: height)
        return event

    def test_resize_with_panel_hidden_sets_baseline_to_full_width(self):
        """Direct measurement when dock is hidden."""
        window = _make_mock_window(width=1500, panel_visible=False, no_panel_width=1400)
        event = self._make_resize_event(1500, 900)
        MainWindow._track_no_panel_width(window, event)
        assert window._no_panel_width == 1500

    def test_resize_with_panel_shown_subtracts_dock_width(self):
        """Derived measurement when dock is shown — preserves the
        no-panel baseline through the auto-grow on dock-show and
        through any user window resize while the dock is open."""
        window = _make_mock_window(
            width=1900, panel_visible=True, panel_width=320, no_panel_width=1400
        )
        event = self._make_resize_event(1900, 900)
        MainWindow._track_no_panel_width(window, event)
        assert window._no_panel_width == 1580  # 1900 - 320

    def test_resize_skipped_when_maximized(self):
        """Maximized window resizes shouldn't update the normal-window
        baseline — that baseline reflects the user's preferred
        non-maximized width."""
        window = _make_mock_window(
            width=2560,
            panel_visible=False,
            is_maximized=True,
            no_panel_width=1400,
        )
        event = self._make_resize_event(2560, 1440)
        MainWindow._track_no_panel_width(window, event)
        assert window._no_panel_width == 1400  # unchanged

    def test_resize_during_construction_is_safe(self):
        """resizeEvent can fire before __init__ finishes wiring the
        dock. The hasattr guard prevents AttributeError; the handler
        is a no-op in that window."""
        # Simulate the early-init state: no _detail_panel yet.
        window = MagicMock(
            spec=["isVisible", "isMaximized", "isFullScreen", "_no_panel_width", "width", "height"]
        )
        window.isVisible.return_value = True
        window.isMaximized.return_value = False
        window.isFullScreen.return_value = False
        window._no_panel_width = None
        event = self._make_resize_event(1400, 900)
        # Must not raise even though _detail_panel is missing.
        MainWindow._track_no_panel_width(window, event)

    def test_resize_with_zero_or_negative_derived_width_skipped(self):
        """If the dock is wider than the window (shouldn't happen, but
        defend) the derived width would be <= 0; skip rather than set
        a bad baseline."""
        window = _make_mock_window(
            width=300, panel_visible=True, panel_width=320, no_panel_width=1400
        )
        event = self._make_resize_event(300, 900)
        MainWindow._track_no_panel_width(window, event)
        assert window._no_panel_width == 1400  # unchanged


class TestSnapshotForShow:
    """``_snapshot_no_panel_width_for_show`` captures the pre-grow
    window width so the auto-grow ``resizeEvent`` (which fires with
    dock.isVisible() still False) can't corrupt the baseline."""

    def test_snapshot_captures_current_width_and_sets_flag(self):
        window = _make_mock_window(width=1100, panel_visible=False, no_panel_width=None)
        MainWindow._snapshot_no_panel_width_for_show(window)
        assert window._no_panel_width == 1100
        assert window._show_in_progress is True

    def test_snapshot_skipped_when_panel_already_visible(self):
        """Defensive: don't overwrite a baseline if the panel is
        already shown — would corrupt to the grown width."""
        window = _make_mock_window(width=1229, panel_visible=True, no_panel_width=1100)
        MainWindow._snapshot_no_panel_width_for_show(window)
        assert window._no_panel_width == 1100
        assert window._show_in_progress is False

    def test_snapshot_skipped_when_maximized(self):
        window = _make_mock_window(
            width=2560, panel_visible=False, is_maximized=True, no_panel_width=1100
        )
        MainWindow._snapshot_no_panel_width_for_show(window)
        assert window._no_panel_width == 1100
        assert window._show_in_progress is False

    def test_snapshot_skipped_when_fullscreen(self):
        window = _make_mock_window(
            width=2560, panel_visible=False, is_fullscreen=True, no_panel_width=1100
        )
        MainWindow._snapshot_no_panel_width_for_show(window)
        assert window._no_panel_width == 1100
        assert window._show_in_progress is False


class TestShowInProgressSuppression:
    """While the show transition is in flight, ``_track_no_panel_width``
    must NOT update the baseline. The auto-grow ``resizeEvent`` fires
    with ``dock.isVisible() == False`` (Qt flips the visibility flag
    after the layout pass), and would otherwise overwrite the
    snapshotted pre-grow width with the post-grow width."""

    def _make_resize_event(self, width: int, height: int) -> MagicMock:
        event = MagicMock()
        event.size.return_value = MagicMock(width=lambda: width, height=lambda: height)
        return event

    def test_resize_during_show_transition_does_not_corrupt_baseline(self):
        """Snapshot pre-show: window=1100. Then Qt fires resizeEvent
        for the auto-grow with width=1229 and dock.isVisible()=False
        (the value Qt actually returns during this pass per the #55
        diagnostic log). The handler must skip the update."""
        window = _make_mock_window(
            width=1229,  # post-grow window width as seen by resizeEvent
            panel_visible=False,  # Qt's stale visibility flag during grow
            panel_width=320,
            no_panel_width=1100,  # snapshotted pre-grow value
            show_in_progress=True,
        )
        event = self._make_resize_event(1229, 700)
        MainWindow._track_no_panel_width(window, event)
        # Baseline must NOT be overwritten with 1229.
        assert window._no_panel_width == 1100

    def test_resize_after_visibility_changed_resumes_tracking(self):
        """Once visibilityChanged(True) clears the flag, normal
        resizeEvent tracking resumes — user resizes update the
        baseline as derived = window − dock."""
        window = _make_mock_window(
            width=1500,
            panel_visible=True,
            panel_width=320,
            no_panel_width=1100,
            show_in_progress=False,  # transition complete
        )
        event = self._make_resize_event(1500, 700)
        MainWindow._track_no_panel_width(window, event)
        assert window._no_panel_width == 1180  # 1500 - 320


class TestVisibilityChangedClearsFlag:
    """``visibilityChanged(True)`` clears ``_show_in_progress`` so
    ``resizeEvent`` resumes tracking user-driven resizes."""

    def test_show_clears_show_in_progress(self):
        window = _make_mock_window(
            width=1229,
            panel_visible=True,
            no_panel_width=1100,
            show_in_progress=True,
        )
        MainWindow._on_detail_panel_visibility_changed(window, True)
        assert window._show_in_progress is False
        # Show path doesn't resize.
        window.resize.assert_not_called()


class TestRepeatedToggleNoRatchet:
    """Show / hide pairs do not incrementally grow the window over
    repeated cycles. The resizeEvent + visibilityChanged design is
    symmetric: every cycle restores to the same no-panel baseline."""

    def test_five_cycles_no_drift_simulation(self):
        """Simulate Qt's behavior across five show/hide cycles by
        threading the resizeEvent and visibilityChanged calls in the
        order Qt would fire them. Final width must equal starting
        width."""
        starting_width = 1400
        dock_width = 320
        current_width = [starting_width]
        baseline_holder = [starting_width]  # established by initial resize

        def _resize(w: int, h: int) -> None:
            current_width[0] = w

        def _make_resize_event(w: int) -> MagicMock:
            ev = MagicMock()
            ev.size.return_value = MagicMock(width=lambda: w, height=lambda: 900)
            return ev

        for _ in range(5):
            # SHOW: Qt grows window; resizeEvent fires with new width
            # while the dock has just become visible.
            current_width[0] += dock_width
            window = _make_mock_window(
                width=current_width[0],
                panel_visible=True,
                panel_width=dock_width,
                no_panel_width=baseline_holder[0],
            )
            window.resize.side_effect = _resize
            MainWindow._track_no_panel_width(window, _make_resize_event(current_width[0]))
            baseline_holder[0] = window._no_panel_width

            # HIDE: visibilityChanged(False) fires; window resizes to
            # baseline; resizeEvent fires for that resize too.
            window = _make_mock_window(
                width=current_width[0],
                panel_visible=False,  # post-hide
                panel_width=dock_width,  # still queryable per Qt semantics
                no_panel_width=baseline_holder[0],
            )
            window.resize.side_effect = _resize
            MainWindow._on_detail_panel_visibility_changed(window, False)
            # The handler schedules the resize via _schedule_no_panel_width_restore,
            # which is mocked. Simulate the deferred QTimer.singleShot
            # firing by invoking the resize manually with the baseline.
            if window._no_panel_width is not None:
                window.resize(window._no_panel_width, 700)
            # Simulate the resizeEvent that the deferred self.resize() fires.
            MainWindow._track_no_panel_width(window, _make_resize_event(current_width[0]))
            baseline_holder[0] = window._no_panel_width

        assert current_width[0] == starting_width, (
            f"Five toggle cycles drifted from {starting_width} to {current_width[0]} — "
            "the resize-event tracking is asymmetric."
        )
