"""config.py

TOML-based configuration system with dataclass support and INI migration.
"""

from __future__ import annotations

import shutil
import socket
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths
from .logger import Logger

logger = Logger(__name__)


@dataclass
class DatabaseConfig:
    """Database and list settings."""

    active_list: str = ""
    sort_key: str = "priority"
    reverse_sort: bool = False


@dataclass
class ServerConfig:
    """Network server settings."""

    enabled: bool = True
    address: str = "0.0.0.0"
    port: int = 5364
    allow_pull: bool = True
    allow_push: bool = True


@dataclass
class SecurityConfig:
    """Security and protocol settings."""

    protocol_version: int = 2


@dataclass
class DiscoveryConfig:
    """Zeroconf/mDNS discovery settings."""

    enabled: bool = True
    service_name: str = ""  # defaults to pytodo-{hostname}

    def get_service_name(self) -> str:
        """Get service name, defaulting to pytodo-{hostname}."""
        if self.service_name:
            return self.service_name
        return f"pytodo-{socket.gethostname()}"


@dataclass
class AppearanceConfig:
    """UI appearance settings."""

    theme: str = "system"  # light, dark, system


@dataclass
class AppConfig:
    """Complete application configuration."""

    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    appearance: AppearanceConfig = field(default_factory=AppearanceConfig)

    def to_toml(self) -> str:
        """Convert config to TOML string."""
        lines = []

        # Database section
        lines.append("[database]")
        lines.append(f'active_list = "{self.database.active_list}"')
        lines.append(f'sort_key = "{self.database.sort_key}"')
        lines.append(f"reverse_sort = {str(self.database.reverse_sort).lower()}")
        lines.append("")

        # Server section
        lines.append("[server]")
        lines.append(f"enabled = {str(self.server.enabled).lower()}")
        lines.append(f'address = "{self.server.address}"')
        lines.append(f"port = {self.server.port}")
        lines.append(f"allow_pull = {str(self.server.allow_pull).lower()}")
        lines.append(f"allow_push = {str(self.server.allow_push).lower()}")
        lines.append("")

        # Security section
        lines.append("[security]")
        lines.append(f"protocol_version = {self.security.protocol_version}")
        lines.append("")

        # Discovery section
        lines.append("[discovery]")
        lines.append(f"enabled = {str(self.discovery.enabled).lower()}")
        lines.append(f'service_name = "{self.discovery.service_name}"')
        lines.append("")

        # Appearance section
        lines.append("[appearance]")
        lines.append(f'theme = "{self.appearance.theme}"')
        lines.append("")

        return "\n".join(lines)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        """Create config from dictionary."""
        config = cls()

        if "database" in data:
            db = data["database"]
            config.database = DatabaseConfig(
                active_list=db.get("active_list", ""),
                sort_key=db.get("sort_key", "priority"),
                reverse_sort=db.get("reverse_sort", False),
            )

        if "server" in data:
            srv = data["server"]
            config.server = ServerConfig(
                enabled=srv.get("enabled", True),
                address=srv.get("address", "0.0.0.0"),
                port=srv.get("port", 5364),
                allow_pull=srv.get("allow_pull", True),
                allow_push=srv.get("allow_push", True),
            )

        if "security" in data:
            sec = data["security"]
            config.security = SecurityConfig(
                protocol_version=sec.get("protocol_version", 2),
            )

        if "discovery" in data:
            disc = data["discovery"]
            config.discovery = DiscoveryConfig(
                enabled=disc.get("enabled", True),
                service_name=disc.get("service_name", ""),
            )

        if "appearance" in data:
            app = data["appearance"]
            config.appearance = AppearanceConfig(
                theme=app.get("theme", "system"),
            )

        return config


class ConfigManager:
    """Manages application configuration with TOML storage and INI migration."""

    def __init__(self, config_dir: Path | None = None, data_dir: Path | None = None):
        """Initialize config manager.

        Args:
            config_dir: Config directory. Defaults to XDG_CONFIG_HOME/pytodo-qt
            data_dir: Data directory. Defaults to XDG_DATA_HOME/pytodo-qt
        """
        self.config_dir = config_dir or paths.get_config_dir()
        self.data_dir = data_dir or paths.get_data_dir()
        self.state_dir = paths.get_state_dir()

        self.config_file = self.config_dir / "config.toml"
        self.legacy_ini_file = self.config_dir / "pytodo-qt.ini"
        self.db_file = self.data_dir / "pytodo-qt-db.json"
        self.log_file = self.state_dir / "pytodo-qt.log"

        self._config: AppConfig | None = None

    def ensure_directories(self) -> None:
        """Ensure all application directories exist."""
        for dir_path in [self.config_dir, self.data_dir, self.state_dir]:
            if not dir_path.exists():
                try:
                    dir_path.mkdir(parents=True)
                    logger.log.info("Created directory: %s", dir_path)
                except OSError as e:
                    logger.log.exception("Error creating directory %s: %s", dir_path, e)
                    raise

    @property
    def config(self) -> AppConfig:
        """Get current configuration, loading if necessary."""
        if self._config is None:
            self._config = self.load()
        return self._config

    def load(self) -> AppConfig:
        """Load configuration from TOML file, migrating from INI if needed."""
        # Migrate from legacy ~/.pytodo-qt directory if needed
        paths.migrate_from_legacy()

        self.ensure_directories()

        # Try loading TOML config
        if self.config_file.exists():
            try:
                with open(self.config_file, "rb") as f:
                    data = tomllib.load(f)
                self._config = AppConfig.from_dict(data)
                logger.log.info("Loaded configuration from %s", self.config_file)
                return self._config
            except Exception as e:
                logger.log.exception("Error loading TOML config: %s", e)

        # Check for legacy INI file and migrate
        if self.legacy_ini_file.exists():
            logger.log.info("Found legacy INI config, migrating...")
            self._config = self._migrate_from_ini()
            self.save()
            return self._config

        # Create default config
        logger.log.info("Creating default configuration")
        self._config = AppConfig()
        self.save()
        return self._config

    def _migrate_from_ini(self) -> AppConfig:
        """Migrate configuration from legacy INI format."""
        import configparser

        config = AppConfig()
        ini = configparser.ConfigParser()

        try:
            ini.read(self.legacy_ini_file)

            # Migrate database section
            if "database" in ini:
                db_section = ini["database"]
                config.database.active_list = db_section.get("active_list", "")
                config.database.sort_key = db_section.get("sort_key", "priority")
                config.database.reverse_sort = db_section.get("reverse_sort", "no").lower() == "yes"

            # Migrate server section
            if "server" in ini:
                srv_section = ini["server"]
                config.server.enabled = srv_section.get("run", "yes").lower() == "yes"
                config.server.address = srv_section.get("address", "0.0.0.0")
                try:
                    config.server.port = int(srv_section.get("port", "5364"))
                except ValueError:
                    config.server.port = 5364
                config.server.allow_pull = srv_section.get("pull", "yes").lower() == "yes"
                config.server.allow_push = srv_section.get("push", "yes").lower() == "yes"

            # Backup old INI file
            backup_path = self.legacy_ini_file.with_suffix(".ini.backup")
            shutil.copy2(self.legacy_ini_file, backup_path)
            logger.log.info("Backed up legacy config to %s", backup_path)

        except Exception as e:
            logger.log.exception("Error migrating INI config: %s", e)

        return config

    def save(self) -> bool:
        """Save current configuration to TOML file."""
        if self._config is None:
            return False

        try:
            self.ensure_directories()
            with open(self.config_file, "w", encoding="utf-8") as f:
                f.write(self._config.to_toml())
            logger.log.info("Saved configuration to %s", self.config_file)
            return True
        except Exception as e:
            logger.log.exception("Error saving config: %s", e)
            return False

    def reload(self) -> AppConfig:
        """Force reload configuration from disk."""
        self._config = None
        return self.load()

    def reset_to_defaults(self) -> AppConfig:
        """Reset configuration to defaults."""
        self._config = AppConfig()
        self.save()
        return self._config


# Global config manager instance
_config_manager: ConfigManager | None = None


def get_config_manager() -> ConfigManager:
    """Get the global config manager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def get_config() -> AppConfig:
    """Get the current application configuration."""
    return get_config_manager().config
