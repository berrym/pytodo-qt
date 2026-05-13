"""Pytest configuration and fixtures."""

import tempfile
from pathlib import Path

import pytest


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
