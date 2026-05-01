"""Tests for the in-app notification overlay widget and manager."""

from __future__ import annotations

import contextlib

import pytest
from PyQt6.QtCore import QSize

from pytodo_qt.gui.widgets.notification_overlay import (
    _MAX_HEIGHT,
    _MIN_HEIGHT,
    NotificationManager,
    NotificationOverlay,
)


class TestNotificationOverlayConstruction:
    """Overlay widget constructs with title, body, and timeout."""

    def test_title_and_body_stored(self, qtbot):
        overlay = NotificationOverlay("Focus Session Complete", "Time for a break!")
        qtbot.addWidget(overlay)
        assert overlay._title == "Focus Session Complete"
        assert overlay._body == "Time for a break!"

    def test_default_timeout_ms(self, qtbot):
        overlay = NotificationOverlay("t", "b")
        qtbot.addWidget(overlay)
        assert overlay._timeout_ms == 5000
        assert overlay._timeout_timer.isActive()

    def test_zero_timeout_means_no_auto_dismiss(self, qtbot):
        overlay = NotificationOverlay("t", "b", timeout_ms=0)
        qtbot.addWidget(overlay)
        assert overlay._timeout_timer.isActive() is False

    def test_top_level_window_flags(self, qtbot):
        """The overlay is a top-level tool window that stays on top and
        does not steal focus — otherwise it would interrupt the user's
        active keyboard session."""
        from PyQt6.QtCore import Qt

        overlay = NotificationOverlay("t", "b")
        qtbot.addWidget(overlay)
        flags = overlay.windowFlags()
        assert bool(flags & Qt.WindowType.FramelessWindowHint)
        assert bool(flags & Qt.WindowType.WindowStaysOnTopHint)
        assert bool(flags & Qt.WindowType.WindowDoesNotAcceptFocus)

    def test_not_dismissed_at_construction(self, qtbot):
        overlay = NotificationOverlay("t", "b")
        qtbot.addWidget(overlay)
        assert overlay._dismissing is False


class TestNotificationOverlayDismissal:
    """Dismissal path via close-glyph click and auto-dismiss timer."""

    def test_close_button_triggers_dismiss(self, qtbot):
        # Do NOT call qtbot.addWidget — this overlay self-destructs via
        # deleteLater() after the dismiss animation, and qtbot's teardown
        # would then call close() on an already-deleted C++ object.
        overlay = NotificationOverlay("t", "b")
        with qtbot.waitSignal(overlay.dismissed, timeout=2000):
            overlay._close_btn.click()
        assert overlay._dismissing is True

    def test_auto_dismiss_fires_on_timeout(self, qtbot):
        overlay = NotificationOverlay("t", "b", timeout_ms=50)
        with qtbot.waitSignal(overlay.dismissed, timeout=2000):
            pass  # timer should fire on its own
        assert overlay._dismissing is True

    def test_second_dismiss_is_a_noop(self, qtbot):
        overlay = NotificationOverlay("t", "b")
        qtbot.addWidget(overlay)
        overlay._start_dismiss()
        # A second call must not restart the animation or re-emit.
        previous_anim = overlay._slide_anim
        overlay._start_dismiss()
        assert overlay._slide_anim is previous_anim


class TestNotificationOverlayBodyClick:
    """Clicking the body area (not the close glyph) emits body_clicked
    and then dismisses."""

    def test_body_click_emits_and_dismisses(self, qtbot):
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QMouseEvent

        overlay = NotificationOverlay("t", "b")
        qtbot.addWidget(overlay)
        overlay.show()

        # Click on the left side of the widget (far from close glyph on
        # the right). We synthesize a press event at a point inside the
        # body region.
        press = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            overlay.rect().center().toPointF(),
            overlay.mapToGlobal(overlay.rect().center()).toPointF(),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        with qtbot.waitSignal(overlay.body_clicked, timeout=500):
            overlay.mousePressEvent(press)
        assert overlay._dismissing is True


class TestNotificationOverlayHoverPause:
    """The auto-dismiss timer pauses while the cursor is over the
    banner and resumes when the cursor leaves."""

    def test_enter_stops_timer_leave_restarts(self, qtbot):
        overlay = NotificationOverlay("t", "b", timeout_ms=5000)
        qtbot.addWidget(overlay)
        assert overlay._timeout_timer.isActive()

        overlay.enterEvent(None)
        assert overlay._timeout_timer.isActive() is False
        assert overlay._paused is True

        overlay.leaveEvent(None)
        assert overlay._timeout_timer.isActive() is True
        assert overlay._paused is False

    def test_leave_without_pause_does_nothing(self, qtbot):
        """If leaveEvent fires without a prior enterEvent (edge case
        during dismiss animation), the timer state is not mutated."""
        overlay = NotificationOverlay("t", "b", timeout_ms=5000)
        qtbot.addWidget(overlay)
        overlay._timeout_timer.stop()
        overlay.leaveEvent(None)
        assert overlay._timeout_timer.isActive() is False


class TestNotificationManagerQueueing:
    """Manager respects max_visible cap and promotes queued items as
    slots free up."""

    def test_first_banner_becomes_visible(self, qtbot):
        mgr = NotificationManager(max_visible=3)
        banner = mgr.show("a", "b", timeout_ms=0)
        assert banner is not None
        qtbot.addWidget(banner)
        assert mgr.visible_count == 1
        assert mgr.queued_count == 0

    def test_beyond_max_visible_goes_to_queue(self, qtbot):
        mgr = NotificationManager(max_visible=2)
        first = mgr.show("1", "one", timeout_ms=0)
        second = mgr.show("2", "two", timeout_ms=0)
        third = mgr.show("3", "three", timeout_ms=0)
        for b in (first, second):
            if b is not None:
                qtbot.addWidget(b)
        assert mgr.visible_count == 2
        assert mgr.queued_count == 1
        assert third is None

    def test_dismissal_promotes_from_queue(self, qtbot):
        mgr = NotificationManager(max_visible=1)
        first = mgr.show("1", "one", timeout_ms=0)
        _ = mgr.show("2", "two", timeout_ms=0)
        assert first is not None
        assert mgr.visible_count == 1
        assert mgr.queued_count == 1

        # Trigger dismissal and let the animation complete so the
        # `dismissed` signal reaches the manager's slot.
        with qtbot.waitSignal(first.dismissed, timeout=2000):
            first._start_dismiss()

        assert mgr.queued_count == 0
        assert mgr.visible_count == 1
        # Clean up the promoted banner before the test ends.
        mgr.dismiss_all()
        qtbot.wait(50)

    def test_dismiss_all_clears_queue(self, qtbot):
        mgr = NotificationManager(max_visible=1)
        first = mgr.show("1", "one", timeout_ms=0)
        _ = mgr.show("2", "two", timeout_ms=0)
        assert first is not None
        assert mgr.queued_count == 1

        mgr.dismiss_all()
        assert mgr.queued_count == 0
        qtbot.wait(50)  # let the deleteLater cycles run


class TestNotificationManagerGeometry:
    """Position math places banners in the top-right corner of the
    primary screen, stacked downward with fixed spacing."""

    def test_first_slot_anchors_top_right(self, qtbot):
        del qtbot  # fixture only needed for the application singleton
        mgr = NotificationManager()
        size = QSize(360, 88)
        pos = mgr._slot_position(0, size)
        screen = mgr._primary_screen_geometry()
        assert pos.x() == screen.right() - size.width() - 16
        assert pos.y() == screen.top() + 16

    def test_second_slot_below_first(self, qtbot):
        del qtbot
        mgr = NotificationManager()
        size = QSize(360, 88)
        first = mgr._slot_position(0, size)
        second = mgr._slot_position(1, size)
        assert second.x() == first.x()
        # spacing constant is 10; banner height 88 → delta is 98
        assert second.y() - first.y() == 88 + 10

    def test_stacking_accounts_for_mixed_heights(self, qtbot):
        """When existing visible banners have different heights (because
        they sized to content), a new banner's slot position must walk
        through the actual heights of preceding banners — not assume a
        uniform height. Pre-fix this used `index * uniform_height`,
        which mis-stacks any two-different-size pair.
        """
        mgr = NotificationManager()
        # Build two visible banners with deliberately different heights.
        first = NotificationOverlay("short", "short body")
        qtbot.addWidget(first)
        second = NotificationOverlay("long", "long body " * 50)
        qtbot.addWidget(second)
        first.adjustSize()
        second.adjustSize()
        first.resize(first.width(), 88)
        second.resize(second.width(), 200)

        mgr._visible.append(first)
        mgr._visible.append(second)

        # A third banner's slot must be positioned below the cumulative
        # heights of the first two, not at index * uniform_height.
        third_size = QSize(360, 88)
        third_pos = mgr._slot_position(2, third_size)
        screen = mgr._primary_screen_geometry()
        # spacing constant = 10; cumulative = 88 + 10 + 200 + 10 = 308
        expected_y = screen.top() + 16 + 88 + 10 + 200 + 10
        assert third_pos.y() == expected_y


class TestNotificationOverlayBodySizing:
    """Banners size to content between _MIN_HEIGHT and _MAX_HEIGHT so
    long text doesn't clip — closes the second half of #43."""

    def test_minimum_height_preserved_for_short_body(self, qtbot):
        """Short body keeps the original 88 px visual baseline."""
        overlay = NotificationOverlay("Title", "short")
        qtbot.addWidget(overlay)
        overlay.adjustSize()
        assert overlay.height() >= _MIN_HEIGHT

    def test_long_body_grows_beyond_minimum(self, qtbot):
        """A multi-line body produces a banner taller than the minimum
        baseline so the content is visible. The pre-fix overlay used a
        fixed height of 88 px regardless of body length, which clipped
        anything past two wrapped lines."""
        long_body = (
            "Conference call with the engineering team to discuss the "
            "next sprint, the mobile roadmap, and how the new sync "
            "protocol changes affect downstream consumers across the "
            "release pipeline."
        )
        overlay = NotificationOverlay("Long-body banner", long_body)
        qtbot.addWidget(overlay)
        overlay.adjustSize()
        # Show is required for layout/font-metrics to resolve in some
        # offscreen QPA configurations.
        overlay.show()
        # On the offscreen QPA platform some Qt builds never emit an
        # expose event; the size is already resolved by adjustSize() so
        # the wait is best-effort.
        with contextlib.suppress(Exception):
            qtbot.waitExposed(overlay, timeout=1000)
        assert overlay.height() > _MIN_HEIGHT

    def test_height_capped_at_maximum(self, qtbot):
        """Pathologically long body still respects the maximum-height
        bound so a single banner can't take over the screen."""
        pathological_body = "very long word " * 500
        overlay = NotificationOverlay("Pathological body", pathological_body)
        qtbot.addWidget(overlay)
        overlay.adjustSize()
        overlay.show()
        with contextlib.suppress(Exception):
            qtbot.waitExposed(overlay, timeout=1000)
        assert overlay.height() <= _MAX_HEIGHT


@pytest.fixture(autouse=True)
def _clean_manager_shutdown(qtbot):
    """Make sure no overlays leak between tests — `deleteLater` runs
    on the next event loop spin, so force one."""
    yield
    qtbot.wait(10)
