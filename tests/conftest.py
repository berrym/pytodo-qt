"""Pytest configuration and fixtures."""

import tempfile
from pathlib import Path

import pytest


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
