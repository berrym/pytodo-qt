"""Tests for the AutoSyncScheduler."""

import pytest

from pytodo_qt.gui.auto_sync import AutoSyncScheduler

# Short delay for tests that need the debounce timer to actually fire.
# notify_change() calls start(delay_seconds * 1000), so we use the
# smallest whole-second value and wait accordingly.
_TEST_DELAY_S = 1


class TestAutoSyncScheduler:
    """Tests for debounce and periodic timer behavior."""

    @pytest.fixture()
    def scheduler(self, qtbot):
        """Create a scheduler with a 1-second debounce for testing."""
        s = AutoSyncScheduler(delay_seconds=_TEST_DELAY_S, interval_minutes=0)
        qtbot.addWidget(s)
        return s

    def test_push_requested_after_debounce(self, qtbot, scheduler):
        """notify_change() should emit push_requested after the debounce delay."""
        scheduler.start()

        with qtbot.waitSignal(scheduler.push_requested, timeout=2000):
            scheduler.notify_change()

    def test_debounce_restarts_on_rapid_changes(self, qtbot, scheduler):
        """Rapid notify_change() calls should only emit once after quiet period."""
        scheduler.start()

        emit_count = 0

        def on_push():
            nonlocal emit_count
            emit_count += 1

        scheduler.push_requested.connect(on_push)

        # Rapid changes — each restarts the 1-second timer
        for _ in range(5):
            scheduler.notify_change()
            qtbot.wait(200)

        # Wait for the debounce to fire (1s after last change)
        qtbot.waitUntil(lambda: emit_count >= 1, timeout=2000)
        # Give extra time to ensure no second emission
        qtbot.wait(1500)
        assert emit_count == 1

    def test_periodic_sync_requested(self, qtbot):
        """Periodic timer should emit sync_requested."""
        scheduler = AutoSyncScheduler(delay_seconds=0, interval_minutes=1)
        qtbot.addWidget(scheduler)
        # Start with a very short interval for testing by directly starting the timer
        scheduler._running = True
        scheduler._periodic_timer.start(50)

        with qtbot.waitSignal(scheduler.sync_requested, timeout=500):
            pass

    def test_stop_prevents_debounce(self, qtbot, scheduler):
        """stop() should cancel any pending debounce timer."""
        scheduler.start()

        scheduler.notify_change()
        assert scheduler._debounce_timer.isActive()

        scheduler.stop()

        assert not scheduler._debounce_timer.isActive()
        assert not scheduler._periodic_timer.isActive()

    def test_disabled_when_delay_zero(self, qtbot):
        """notify_change() should be a no-op when delay is 0."""
        scheduler = AutoSyncScheduler(delay_seconds=0, interval_minutes=0)
        qtbot.addWidget(scheduler)
        scheduler.start()

        scheduler.notify_change()
        assert not scheduler._debounce_timer.isActive()

    def test_disabled_when_not_started(self, qtbot, scheduler):
        """notify_change() should be a no-op before start() is called."""
        scheduler.notify_change()
        assert not scheduler._debounce_timer.isActive()

    def test_update_config_changes_periodic(self, qtbot):
        """update_config() should restart the periodic timer with new interval."""
        scheduler = AutoSyncScheduler(delay_seconds=0, interval_minutes=0)
        qtbot.addWidget(scheduler)
        scheduler.start()

        assert not scheduler._periodic_timer.isActive()

        # Enable periodic
        scheduler.update_config(delay_seconds=0, interval_minutes=5)
        assert scheduler._periodic_timer.isActive()
        assert scheduler._periodic_timer.interval() == 5 * 60 * 1000

        # Disable periodic
        scheduler.update_config(delay_seconds=0, interval_minutes=0)
        assert not scheduler._periodic_timer.isActive()

    def test_update_config_stops_pending_debounce(self, qtbot):
        """update_config() should stop pending debounce when delay changes."""
        scheduler = AutoSyncScheduler(delay_seconds=5, interval_minutes=0)
        qtbot.addWidget(scheduler)
        scheduler.start()

        # Trigger a pending debounce
        scheduler.notify_change()
        assert scheduler._debounce_timer.isActive()

        # Reconfigure — pending debounce should be stopped
        scheduler.update_config(delay_seconds=10, interval_minutes=0)
        assert not scheduler._debounce_timer.isActive()

    def test_start_activates_periodic_timer(self, qtbot):
        """start() with non-zero interval should activate periodic timer."""
        scheduler = AutoSyncScheduler(delay_seconds=5, interval_minutes=10)
        qtbot.addWidget(scheduler)
        scheduler.start()

        assert scheduler._running is True
        assert scheduler._periodic_timer.isActive()
        assert scheduler._periodic_timer.interval() == 10 * 60 * 1000
        # Debounce timer only starts on notify_change, not on start
        assert not scheduler._debounce_timer.isActive()
