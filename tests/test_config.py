"""Tests for configuration system."""

import tempfile
from pathlib import Path

from pytodo_qt.core.config import (
    AppConfig,
    ConfigManager,
    DatabaseConfig,
    DiscoveryConfig,
)


class TestAppConfig:
    """Tests for AppConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = AppConfig()

        assert config.database.active_list == ""
        assert config.database.sort_tier1 == "completion"
        assert config.database.sort_tier1_reverse is False
        assert config.database.sort_tier2 == "due_date"
        assert config.database.sort_tier2_reverse is False
        assert config.database.sort_tier3 == "priority"
        assert config.database.sort_tier3_reverse is False

        assert config.server.enabled is True
        assert config.server.address == "0.0.0.0"
        assert config.server.port == 5364
        assert config.server.allow_pull is True
        assert config.server.allow_push is True

        assert config.security.protocol_version == 2

        assert config.discovery.enabled is True
        assert config.discovery.service_name == ""

        assert config.appearance.theme == "system"

    def test_to_toml(self):
        """Test TOML serialization."""
        config = AppConfig()
        config.database.active_list = "Test List"
        config.server.port = 9999

        toml_str = config.to_toml()

        assert 'active_list = "Test List"' in toml_str
        assert "port = 9999" in toml_str

    def test_from_dict(self):
        """Test creating config from dictionary."""
        data = {
            "database": {
                "active_list": "My List",
                "sort_tier1": "priority",
                "sort_tier1_reverse": True,
                "sort_tier2": "completion",
                "sort_tier2_reverse": False,
                "sort_tier3": "due_date",
                "sort_tier3_reverse": True,
            },
            "server": {
                "enabled": False,
                "port": 8080,
            },
        }

        config = AppConfig.from_dict(data)

        assert config.database.active_list == "My List"
        assert config.database.sort_tier1 == "priority"
        assert config.database.sort_tier1_reverse is True
        assert config.database.sort_tier2 == "completion"
        assert config.database.sort_tier3 == "due_date"
        assert config.database.sort_tier3_reverse is True
        assert config.server.enabled is False
        assert config.server.port == 8080
        # Defaults for unspecified values
        assert config.security.protocol_version == 2

    def test_from_dict_missing_sort_tiers_gets_defaults(self):
        """Old TOML files missing sort tier fields get sensible defaults."""
        data = {
            "database": {
                "active_list": "Old Config",
                "sort_key": "priority",
                "reverse_sort": True,
            },
        }
        config = AppConfig.from_dict(data)
        assert config.database.sort_tier1 == "completion"
        assert config.database.sort_tier1_reverse is False
        assert config.database.sort_tier2 == "due_date"
        assert config.database.sort_tier3 == "priority"

    def test_sort_tiers_helper(self):
        """Test sort_tiers() returns list of (dimension, reverse) tuples."""
        config = DatabaseConfig(
            sort_tier1="priority",
            sort_tier1_reverse=True,
            sort_tier2="completion",
            sort_tier2_reverse=False,
            sort_tier3="due_date",
            sort_tier3_reverse=True,
        )
        tiers = config.sort_tiers()
        assert tiers == [
            ("priority", True),
            ("completion", False),
            ("due_date", True),
        ]


class TestConfigManager:
    """Tests for ConfigManager."""

    def test_save_and_load(self):
        """Test saving and loading configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            manager = ConfigManager(app_dir)

            # Modify config
            config = manager.config
            config.database.active_list = "Test"
            config.server.port = 1234

            # Save
            assert manager.save() is True

            # Create new manager and load
            manager2 = ConfigManager(app_dir)
            config2 = manager2.load()

            assert config2.database.active_list == "Test"
            assert config2.server.port == 1234

    def test_reset_to_defaults(self):
        """Test resetting to default configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            manager = ConfigManager(app_dir)

            # Modify config
            config = manager.config
            config.server.port = 9999
            manager.save()

            # Reset
            config = manager.reset_to_defaults()

            assert config.server.port == 5364


class TestDiscoveryConfig:
    """Tests for DiscoveryConfig."""

    def test_get_service_name_custom(self):
        """Test custom service name."""
        config = DiscoveryConfig(service_name="my-service")
        assert config.get_service_name() == "my-service"

    def test_get_service_name_default(self):
        """Test default service name generation."""
        config = DiscoveryConfig()
        name = config.get_service_name()
        assert name.startswith("pytodo-")

    def test_auto_sync_trusted_default_false(self):
        """Test auto_sync_trusted defaults to False."""
        config = DiscoveryConfig()
        assert config.auto_sync_trusted is False

    def test_auto_sync_trusted_from_dict(self):
        """Test auto_sync_trusted loaded from dict."""
        app_config = AppConfig.from_dict({"discovery": {"auto_sync_trusted": True}})
        assert app_config.discovery.auto_sync_trusted is True


class TestConfigManagerExtended:
    """Extended tests for ConfigManager."""

    def test_ensure_directories_creates_new(self):
        """Test ensure_directories creates directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "config" / "pytodo-qt"
            data_dir = Path(tmpdir) / "data" / "pytodo-qt"
            state_dir = Path(tmpdir) / "state" / "pytodo-qt"

            manager = ConfigManager(config_dir=config_dir, data_dir=data_dir)
            manager.state_dir = state_dir

            # Directories should not exist yet
            assert not config_dir.exists()
            assert not data_dir.exists()
            assert not state_dir.exists()

            manager.ensure_directories()

            # Now they should exist
            assert config_dir.exists()
            assert data_dir.exists()
            assert state_dir.exists()

    def test_reload_forces_disk_read(self):
        """Test reload forces reload from disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "config"
            data_dir = Path(tmpdir) / "data"
            state_dir = Path(tmpdir) / "state"

            manager = ConfigManager(config_dir=config_dir, data_dir=data_dir)
            manager.state_dir = state_dir

            # Load initial config
            manager.load()

            # Modify in memory
            assert manager._config is not None
            manager._config.server.port = 9999

            # Reload should reset
            config = manager.reload()

            # Should be default since file was overwritten with defaults
            assert config.server.port == 5364

    def test_save_returns_false_without_config(self):
        """Test save returns False when no config loaded."""
        manager = ConfigManager()
        manager._config = None

        result = manager.save()

        assert result is False


class TestGlobalFunctions:
    """Tests for global config functions."""

    def test_get_config_manager_singleton(self):
        """Test get_config_manager returns singleton."""
        import pytodo_qt.core.config as config_module

        # Reset global
        config_module._config_manager = None

        from pytodo_qt.core.config import get_config_manager

        manager1 = get_config_manager()
        manager2 = get_config_manager()

        assert manager1 is manager2

        # Cleanup
        config_module._config_manager = None

    def test_get_config_returns_appconfig(self):
        """Test get_config returns AppConfig instance."""
        import pytodo_qt.core.config as config_module

        with tempfile.TemporaryDirectory() as tmpdir:
            config_module._config_manager = ConfigManager(
                config_dir=Path(tmpdir) / "config",
                data_dir=Path(tmpdir) / "data",
            )
            config_module._config_manager.state_dir = Path(tmpdir) / "state"

            from pytodo_qt.core.config import get_config

            config = get_config()

            assert isinstance(config, AppConfig)

            # Cleanup
            config_module._config_manager = None
