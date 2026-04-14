"""Tests for path management module."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from pytodo_qt.core.paths import (
    APP_NAME,
    ensure_directories,
    get_config_dir,
    get_config_file,
    get_data_dir,
    get_database_file,
    get_log_file,
    get_state_dir,
    get_xdg_config_home,
    get_xdg_data_home,
    get_xdg_state_home,
)


class TestAppName:
    """Test APP_NAME constant."""

    def test_app_name(self):
        """Test app name is correct."""
        assert APP_NAME == "pytodo-qt"


class TestXDGConfigHome:
    """Tests for get_xdg_config_home."""

    def test_default_config_home(self):
        """Test default config home when XDG_CONFIG_HOME not set."""
        # Save and remove XDG_CONFIG_HOME without clearing all env vars
        # (Windows needs USERPROFILE etc. for Path.home())
        env_backup = os.environ.get("XDG_CONFIG_HOME")
        os.environ.pop("XDG_CONFIG_HOME", None)
        try:
            result = get_xdg_config_home()
            assert result == Path.home() / ".config"
        finally:
            if env_backup is not None:
                os.environ["XDG_CONFIG_HOME"] = env_backup

    def test_custom_config_home(self):
        """Test custom config home from environment."""
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": "/custom/config"}):
            result = get_xdg_config_home()
            assert result == Path("/custom/config")


class TestXDGDataHome:
    """Tests for get_xdg_data_home."""

    def test_default_data_home(self):
        """Test default data home when XDG_DATA_HOME not set."""
        env_backup = os.environ.get("XDG_DATA_HOME")
        os.environ.pop("XDG_DATA_HOME", None)
        try:
            result = get_xdg_data_home()
            assert result == Path.home() / ".local" / "share"
        finally:
            if env_backup is not None:
                os.environ["XDG_DATA_HOME"] = env_backup

    def test_custom_data_home(self):
        """Test custom data home from environment."""
        with patch.dict(os.environ, {"XDG_DATA_HOME": "/custom/data"}):
            result = get_xdg_data_home()
            assert result == Path("/custom/data")


class TestXDGStateHome:
    """Tests for get_xdg_state_home."""

    def test_default_state_home(self):
        """Test default state home when XDG_STATE_HOME not set."""
        env_backup = os.environ.get("XDG_STATE_HOME")
        os.environ.pop("XDG_STATE_HOME", None)
        try:
            result = get_xdg_state_home()
            assert result == Path.home() / ".local" / "state"
        finally:
            if env_backup is not None:
                os.environ["XDG_STATE_HOME"] = env_backup

    def test_custom_state_home(self):
        """Test custom state home from environment."""
        with patch.dict(os.environ, {"XDG_STATE_HOME": "/custom/state"}):
            result = get_xdg_state_home()
            assert result == Path("/custom/state")


class TestAppDirs:
    """Tests for application directory functions."""

    def test_get_config_dir(self):
        """Test get_config_dir returns config home + app name."""
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": "/xdg/config"}):
            result = get_config_dir()
            assert result == Path("/xdg/config/pytodo-qt")

    def test_get_data_dir(self):
        """Test get_data_dir returns data home + app name."""
        with patch.dict(os.environ, {"XDG_DATA_HOME": "/xdg/data"}):
            result = get_data_dir()
            assert result == Path("/xdg/data/pytodo-qt")

    def test_get_state_dir(self):
        """Test get_state_dir returns state home + app name."""
        with patch.dict(os.environ, {"XDG_STATE_HOME": "/xdg/state"}):
            result = get_state_dir()
            assert result == Path("/xdg/state/pytodo-qt")


class TestFilePaths:
    """Tests for file path functions."""

    def test_get_config_file(self):
        """Test get_config_file returns correct path."""
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": "/xdg/config"}):
            result = get_config_file()
            assert result == Path("/xdg/config/pytodo-qt/config.toml")

    def test_get_database_file(self):
        """Test get_database_file returns correct path (SQLite)."""
        with patch.dict(os.environ, {"XDG_DATA_HOME": "/xdg/data"}):
            result = get_database_file()
            assert result == Path("/xdg/data/pytodo-qt/pytodo-qt.db")

    def test_get_log_file(self):
        """Test get_log_file returns correct path."""
        with patch.dict(os.environ, {"XDG_STATE_HOME": "/xdg/state"}):
            result = get_log_file()
            assert result == Path("/xdg/state/pytodo-qt/pytodo-qt.log")


class TestEnsureDirectories:
    """Tests for ensure_directories function."""

    def test_creates_directories(self):
        """Test that ensure_directories creates all needed directories."""
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch.dict(
                os.environ,
                {
                    "XDG_CONFIG_HOME": str(Path(tmpdir) / "config"),
                    "XDG_DATA_HOME": str(Path(tmpdir) / "data"),
                    "XDG_STATE_HOME": str(Path(tmpdir) / "state"),
                },
            ),
        ):
            ensure_directories()

            assert (Path(tmpdir) / "config" / "pytodo-qt").exists()
            assert (Path(tmpdir) / "data" / "pytodo-qt").exists()
            assert (Path(tmpdir) / "state" / "pytodo-qt").exists()

    def test_existing_directories_not_recreated(self):
        """Test that existing directories are not affected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "config" / "pytodo-qt"
            config_dir.mkdir(parents=True)

            # Create a marker file
            marker = config_dir / "marker.txt"
            marker.write_text("test")

            with patch.dict(
                os.environ,
                {
                    "XDG_CONFIG_HOME": str(Path(tmpdir) / "config"),
                    "XDG_DATA_HOME": str(Path(tmpdir) / "data"),
                    "XDG_STATE_HOME": str(Path(tmpdir) / "state"),
                },
            ):
                ensure_directories()

                # Marker file should still exist
                assert marker.exists()
                assert marker.read_text() == "test"
