"""Tests for settings module."""

from unittest.mock import MagicMock, patch

import pytest

from pytodo_qt.core import settings


class TestVersion:
    """Tests for version constant."""

    def test_version_format(self):
        """Test version is in semver format."""
        version = settings.__version__
        parts = version.split(".")
        assert len(parts) == 3
        assert all(part.isdigit() for part in parts)


class TestInitConfig:
    """Tests for init_config function."""

    def test_init_config_creates_manager(self):
        """Test that init_config creates config manager."""
        mock_manager = MagicMock()
        mock_manager.config = MagicMock()

        with patch("pytodo_qt.core.settings.get_config_manager", return_value=mock_manager):
            result = settings.init_config()

            assert result is mock_manager.config
            assert settings._config_mgr is mock_manager


class TestSaveConfig:
    """Tests for save_config function."""

    def test_save_config_with_manager(self):
        """Test save_config calls manager save."""
        mock_manager = MagicMock()
        mock_manager.save.return_value = True

        settings._config_mgr = mock_manager

        result = settings.save_config()

        assert result is True
        mock_manager.save.assert_called_once()

    def test_save_config_without_manager(self):
        """Test save_config returns False without manager."""
        settings._config_mgr = None

        result = settings.save_config()

        assert result is False


class TestDirectoryExports:
    """Tests for exported directory/file paths."""

    def test_config_dir_exported(self):
        """Test config_dir is exported."""
        assert settings.config_dir is not None

    def test_data_dir_exported(self):
        """Test data_dir is exported."""
        assert settings.data_dir is not None

    def test_state_dir_exported(self):
        """Test state_dir is exported."""
        assert settings.state_dir is not None

    def test_config_fn_exported(self):
        """Test config_fn is exported."""
        assert settings.config_fn is not None

    def test_db_fn_exported(self):
        """Test db_fn is exported."""
        assert settings.db_fn is not None

    def test_log_fn_exported(self):
        """Test log_fn is exported."""
        assert settings.log_fn is not None
