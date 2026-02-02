"""Tests for configuration system."""

import tempfile
from pathlib import Path

from pytodo_qt.core.config import (
    AppConfig,
    ConfigManager,
    DiscoveryConfig,
)


class TestAppConfig:
    """Tests for AppConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = AppConfig()

        assert config.database.active_list == ""
        assert config.database.sort_key == "priority"
        assert config.database.reverse_sort is False

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
                "sort_key": "reminder",
                "reverse_sort": True,
            },
            "server": {
                "enabled": False,
                "port": 8080,
            },
        }

        config = AppConfig.from_dict(data)

        assert config.database.active_list == "My List"
        assert config.database.sort_key == "reminder"
        assert config.database.reverse_sort is True
        assert config.server.enabled is False
        assert config.server.port == 8080
        # Defaults for unspecified values
        assert config.security.protocol_version == 2


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
            from unittest.mock import patch

            config_dir = Path(tmpdir) / "config"
            data_dir = Path(tmpdir) / "data"
            state_dir = Path(tmpdir) / "state"

            manager = ConfigManager(config_dir=config_dir, data_dir=data_dir)
            manager.state_dir = state_dir
            manager.legacy_ini_file = config_dir / "pytodo-qt.ini"

            # Load initial config
            with patch("pytodo_qt.core.config.paths.migrate_from_legacy"):
                manager.load()

            # Modify in memory
            manager._config.server.port = 9999

            # Reload should reset
            with patch("pytodo_qt.core.config.paths.migrate_from_legacy"):
                config = manager.reload()

            # Should be default since file was overwritten with defaults
            assert config.server.port == 5364

    def test_save_returns_false_without_config(self):
        """Test save returns False when no config loaded."""
        manager = ConfigManager()
        manager._config = None

        result = manager.save()

        assert result is False


class TestINIMigration:
    """Tests for INI config migration."""

    def test_migrate_from_ini_all_sections(self):
        """Test migrating full INI config."""
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "config"
            data_dir = Path(tmpdir) / "data"
            state_dir = Path(tmpdir) / "state"

            config_dir.mkdir(parents=True)
            data_dir.mkdir(parents=True)
            state_dir.mkdir(parents=True)

            ini_file = config_dir / "pytodo-qt.ini"
            ini_file.write_text("""
[database]
active_list = WorkItems
sort_key = reminder
reverse_sort = yes

[server]
run = no
address = 192.168.1.1
port = 7777
pull = yes
push = no
""")

            manager = ConfigManager(config_dir=config_dir, data_dir=data_dir)
            manager.state_dir = state_dir
            manager.legacy_ini_file = ini_file

            config = manager._migrate_from_ini()

            assert config.database.active_list == "WorkItems"
            assert config.database.sort_key == "reminder"
            assert config.database.reverse_sort is True
            assert config.server.enabled is False
            assert config.server.address == "192.168.1.1"
            assert config.server.port == 7777
            assert config.server.allow_pull is True
            assert config.server.allow_push is False

    def test_migrate_from_ini_invalid_port_fallback(self):
        """Test migration handles invalid port value."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "config"
            data_dir = Path(tmpdir) / "data"
            state_dir = Path(tmpdir) / "state"

            config_dir.mkdir(parents=True)

            ini_file = config_dir / "pytodo-qt.ini"
            ini_file.write_text("""
[server]
port = notanumber
""")

            manager = ConfigManager(config_dir=config_dir, data_dir=data_dir)
            manager.state_dir = state_dir
            manager.legacy_ini_file = ini_file

            config = manager._migrate_from_ini()

            # Should fallback to default
            assert config.server.port == 5364

    def test_load_migrates_ini_when_no_toml(self):
        """Test load migrates from INI when no TOML exists."""
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "config"
            data_dir = Path(tmpdir) / "data"
            state_dir = Path(tmpdir) / "state"

            config_dir.mkdir(parents=True)
            data_dir.mkdir(parents=True)
            state_dir.mkdir(parents=True)

            ini_file = config_dir / "pytodo-qt.ini"
            ini_file.write_text("""
[database]
active_list = FromINI

[server]
port = 6666
""")

            manager = ConfigManager(config_dir=config_dir, data_dir=data_dir)
            manager.state_dir = state_dir
            manager.legacy_ini_file = ini_file

            with patch("pytodo_qt.core.config.paths.migrate_from_legacy"):
                config = manager.load()

            assert config.database.active_list == "FromINI"
            assert config.server.port == 6666

            # TOML should have been created
            assert manager.config_file.exists()


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
        from unittest.mock import patch

        import pytodo_qt.core.config as config_module

        with tempfile.TemporaryDirectory() as tmpdir:
            config_module._config_manager = ConfigManager(
                config_dir=Path(tmpdir) / "config",
                data_dir=Path(tmpdir) / "data",
            )
            config_module._config_manager.state_dir = Path(tmpdir) / "state"
            config_module._config_manager.legacy_ini_file = (
                Path(tmpdir) / "config" / "pytodo-qt.ini"
            )

            from pytodo_qt.core.config import get_config

            with patch("pytodo_qt.core.config.paths.migrate_from_legacy"):
                config = get_config()

            assert isinstance(config, AppConfig)

            # Cleanup
            config_module._config_manager = None
