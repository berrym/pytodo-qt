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
