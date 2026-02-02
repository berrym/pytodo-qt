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
    get_legacy_dir,
    get_legacy_ini_file,
    get_log_file,
    get_state_dir,
    get_xdg_config_home,
    get_xdg_data_home,
    get_xdg_state_home,
    migrate_from_legacy,
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
        with patch.dict(os.environ, {}, clear=True):
            # Clear XDG_CONFIG_HOME if present
            os.environ.pop("XDG_CONFIG_HOME", None)
            result = get_xdg_config_home()
            assert result == Path.home() / ".config"

    def test_custom_config_home(self):
        """Test custom config home from environment."""
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": "/custom/config"}):
            result = get_xdg_config_home()
            assert result == Path("/custom/config")


class TestXDGDataHome:
    """Tests for get_xdg_data_home."""

    def test_default_data_home(self):
        """Test default data home when XDG_DATA_HOME not set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("XDG_DATA_HOME", None)
            result = get_xdg_data_home()
            assert result == Path.home() / ".local" / "share"

    def test_custom_data_home(self):
        """Test custom data home from environment."""
        with patch.dict(os.environ, {"XDG_DATA_HOME": "/custom/data"}):
            result = get_xdg_data_home()
            assert result == Path("/custom/data")


class TestXDGStateHome:
    """Tests for get_xdg_state_home."""

    def test_default_state_home(self):
        """Test default state home when XDG_STATE_HOME not set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("XDG_STATE_HOME", None)
            result = get_xdg_state_home()
            assert result == Path.home() / ".local" / "state"

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

    def test_get_legacy_dir(self):
        """Test get_legacy_dir returns home + .pytodo-qt."""
        result = get_legacy_dir()
        assert result == Path.home() / ".pytodo-qt"


class TestFilePaths:
    """Tests for file path functions."""

    def test_get_config_file(self):
        """Test get_config_file returns correct path."""
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": "/xdg/config"}):
            result = get_config_file()
            assert result == Path("/xdg/config/pytodo-qt/config.toml")

    def test_get_legacy_ini_file(self):
        """Test get_legacy_ini_file returns correct path."""
        result = get_legacy_ini_file()
        assert result == Path.home() / ".pytodo-qt" / "pytodo-qt.ini"

    def test_get_database_file(self):
        """Test get_database_file returns correct path."""
        with patch.dict(os.environ, {"XDG_DATA_HOME": "/xdg/data"}):
            result = get_database_file()
            assert result == Path("/xdg/data/pytodo-qt/pytodo-qt-db.json")

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


class TestMigration:
    """Tests for migrate_from_legacy function."""

    def test_no_legacy_dir(self):
        """Test migration when legacy dir doesn't exist."""
        with patch(
            "pytodo_qt.core.paths.get_legacy_dir",
            return_value=Path("/nonexistent/path"),
        ):
            result = migrate_from_legacy()
            assert result is False

    def test_migrate_config_file(self):
        """Test migrating config file from legacy location."""
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_dir = Path(tmpdir) / "legacy"
            legacy_dir.mkdir()

            # Create legacy config
            legacy_config = legacy_dir / "config.toml"
            legacy_config.write_text("[server]\nport = 5364\n")

            new_config_dir = Path(tmpdir) / "config" / "pytodo-qt"
            Path(tmpdir) / "data" / "pytodo-qt"
            Path(tmpdir) / "state" / "pytodo-qt"

            with (
                patch("pytodo_qt.core.paths.get_legacy_dir", return_value=legacy_dir),
                patch.dict(
                    os.environ,
                    {
                        "XDG_CONFIG_HOME": str(Path(tmpdir) / "config"),
                        "XDG_DATA_HOME": str(Path(tmpdir) / "data"),
                        "XDG_STATE_HOME": str(Path(tmpdir) / "state"),
                    },
                ),
            ):
                result = migrate_from_legacy()

            assert result is True
            assert (new_config_dir / "config.toml").exists()
            assert (new_config_dir / "config.toml").read_text() == "[server]\nport = 5364\n"

    def test_migrate_database_file(self):
        """Test migrating database file from legacy location."""
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_dir = Path(tmpdir) / "legacy"
            legacy_dir.mkdir()

            # Create legacy database
            legacy_db = legacy_dir / "pytodo-qt-db.json"
            legacy_db.write_text('{"lists": {}}')

            with (
                patch("pytodo_qt.core.paths.get_legacy_dir", return_value=legacy_dir),
                patch.dict(
                    os.environ,
                    {
                        "XDG_CONFIG_HOME": str(Path(tmpdir) / "config"),
                        "XDG_DATA_HOME": str(Path(tmpdir) / "data"),
                        "XDG_STATE_HOME": str(Path(tmpdir) / "state"),
                    },
                ),
            ):
                result = migrate_from_legacy()

            new_db = Path(tmpdir) / "data" / "pytodo-qt" / "pytodo-qt-db.json"
            assert result is True
            assert new_db.exists()
            assert new_db.read_text() == '{"lists": {}}'

    def test_migrate_legacy_ini(self):
        """Test migrating legacy INI file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_dir = Path(tmpdir) / "legacy"
            legacy_dir.mkdir()

            # Create legacy INI
            legacy_ini = legacy_dir / "pytodo-qt.ini"
            legacy_ini.write_text("[General]\npassword=secret\n")

            with (
                patch("pytodo_qt.core.paths.get_legacy_dir", return_value=legacy_dir),
                patch.dict(
                    os.environ,
                    {
                        "XDG_CONFIG_HOME": str(Path(tmpdir) / "config"),
                        "XDG_DATA_HOME": str(Path(tmpdir) / "data"),
                        "XDG_STATE_HOME": str(Path(tmpdir) / "state"),
                    },
                ),
            ):
                result = migrate_from_legacy()

            new_ini = Path(tmpdir) / "config" / "pytodo-qt" / "pytodo-qt.ini"
            assert result is True
            assert new_ini.exists()

    def test_no_migration_if_dest_exists(self):
        """Test that existing destination files are not overwritten."""
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_dir = Path(tmpdir) / "legacy"
            legacy_dir.mkdir()

            # Create legacy config
            legacy_config = legacy_dir / "config.toml"
            legacy_config.write_text("[old]\nvalue = 1\n")

            # Pre-create new config
            new_config_dir = Path(tmpdir) / "config" / "pytodo-qt"
            new_config_dir.mkdir(parents=True)
            new_config = new_config_dir / "config.toml"
            new_config.write_text("[new]\nvalue = 2\n")

            with (
                patch("pytodo_qt.core.paths.get_legacy_dir", return_value=legacy_dir),
                patch.dict(
                    os.environ,
                    {
                        "XDG_CONFIG_HOME": str(Path(tmpdir) / "config"),
                        "XDG_DATA_HOME": str(Path(tmpdir) / "data"),
                        "XDG_STATE_HOME": str(Path(tmpdir) / "state"),
                    },
                ),
            ):
                result = migrate_from_legacy()

            # Should not have migrated (nothing new)
            assert result is False
            # Original content should be preserved
            assert new_config.read_text() == "[new]\nvalue = 2\n"

    def test_migration_marker_created(self):
        """Test that migration marker file is created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_dir = Path(tmpdir) / "legacy"
            legacy_dir.mkdir()

            # Create legacy config
            legacy_config = legacy_dir / "config.toml"
            legacy_config.write_text("[server]\nport = 5364\n")

            with (
                patch("pytodo_qt.core.paths.get_legacy_dir", return_value=legacy_dir),
                patch.dict(
                    os.environ,
                    {
                        "XDG_CONFIG_HOME": str(Path(tmpdir) / "config"),
                        "XDG_DATA_HOME": str(Path(tmpdir) / "data"),
                        "XDG_STATE_HOME": str(Path(tmpdir) / "state"),
                    },
                ),
            ):
                migrate_from_legacy()

            marker = legacy_dir / ".migrated-to-xdg"
            assert marker.exists()
            assert "Migrated to XDG directories" in marker.read_text()
