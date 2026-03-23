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
    sort_tier1: str = "completion"
    sort_tier1_reverse: bool = False
    sort_tier2: str = "due_date"
    sort_tier2_reverse: bool = False
    sort_tier3: str = "priority"
    sort_tier3_reverse: bool = False
    view_mode: str = "list"  # "list" or "board"
    day_start_hour: int = 0  # Hour when the logical day starts (0-23)

    def sort_tiers(self) -> list[tuple[str, bool]]:
        """Return sort tiers as [(dimension, reverse), ...]."""
        return [
            (self.sort_tier1, self.sort_tier1_reverse),
            (self.sort_tier2, self.sort_tier2_reverse),
            (self.sort_tier3, self.sort_tier3_reverse),
        ]


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
    auto_sync_trusted: bool = False  # auto-sync when trusted devices come online
    auto_sync_delay: int = 0  # seconds to debounce before auto-push (0 = disabled)
    auto_sync_interval: int = 0  # minutes between periodic full syncs (0 = disabled)

    def get_service_name(self) -> str:
        """Get service name, defaulting to pytodo-{hostname}."""
        if self.service_name:
            return self.service_name
        return f"pytodo-{socket.gethostname()}"


@dataclass
class PomodoroConfig:
    """Focus timer settings."""

    work_duration: int = 25  # minutes (1-120)
    break_duration: int = 5  # minutes (1-30)
    long_break_duration: int = 15  # minutes (5-60)
    sessions_before_long_break: int = 4  # (2-10)
    auto_start_break: bool = True
    sound_enabled: bool = False
    sound_volume: int = 50  # 0-100
    daily_goal: int = 0  # Target sessions per day (0 = no goal)
    milestone_notifications: bool = True  # Show celebration notifications


@dataclass
class WebConfig:
    """Embedded web server settings."""

    enabled: bool = False  # Disabled by default
    port: int = 8080
    auth_token: str = ""  # Auto-generated on first start if empty
    tls_enabled: bool = True  # TLS with auto-generated self-signed cert
    bind_address: str = "0.0.0.0"  # "0.0.0.0" or "127.0.0.1"


@dataclass
class AppearanceConfig:
    """UI appearance settings."""

    theme: str = "system"  # light, dark, system
    time_format: str = "system"  # system, 12h, 24h
    close_to_tray: bool = True
    font: str = "bundled"  # "bundled", "system", or custom family name


@dataclass
class AppConfig:
    """Complete application configuration."""

    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    appearance: AppearanceConfig = field(default_factory=AppearanceConfig)
    pomodoro: PomodoroConfig = field(default_factory=PomodoroConfig)
    web: WebConfig = field(default_factory=WebConfig)

    def to_toml(self) -> str:
        """Convert config to TOML string."""
        lines = []

        # Database section
        lines.append("[database]")
        lines.append(f'active_list = "{self.database.active_list}"')
        lines.append(f'sort_tier1 = "{self.database.sort_tier1}"')
        lines.append(f"sort_tier1_reverse = {str(self.database.sort_tier1_reverse).lower()}")
        lines.append(f'sort_tier2 = "{self.database.sort_tier2}"')
        lines.append(f"sort_tier2_reverse = {str(self.database.sort_tier2_reverse).lower()}")
        lines.append(f'sort_tier3 = "{self.database.sort_tier3}"')
        lines.append(f"sort_tier3_reverse = {str(self.database.sort_tier3_reverse).lower()}")
        lines.append(f'view_mode = "{self.database.view_mode}"')
        lines.append(f"day_start_hour = {self.database.day_start_hour}")
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
        lines.append(f"auto_sync_trusted = {str(self.discovery.auto_sync_trusted).lower()}")
        lines.append(f"auto_sync_delay = {self.discovery.auto_sync_delay}")
        lines.append(f"auto_sync_interval = {self.discovery.auto_sync_interval}")
        lines.append("")

        # Appearance section
        lines.append("[appearance]")
        lines.append(f'theme = "{self.appearance.theme}"')
        lines.append(f'time_format = "{self.appearance.time_format}"')
        lines.append(f"close_to_tray = {str(self.appearance.close_to_tray).lower()}")
        lines.append(f'font = "{self.appearance.font}"')
        lines.append("")

        # Pomodoro section
        lines.append("[pomodoro]")
        lines.append(f"work_duration = {self.pomodoro.work_duration}")
        lines.append(f"break_duration = {self.pomodoro.break_duration}")
        lines.append(f"long_break_duration = {self.pomodoro.long_break_duration}")
        lines.append(f"sessions_before_long_break = {self.pomodoro.sessions_before_long_break}")
        lines.append(f"auto_start_break = {str(self.pomodoro.auto_start_break).lower()}")
        lines.append(f"sound_enabled = {str(self.pomodoro.sound_enabled).lower()}")
        lines.append(f"sound_volume = {self.pomodoro.sound_volume}")
        lines.append(f"daily_goal = {self.pomodoro.daily_goal}")
        lines.append(
            f"milestone_notifications = {str(self.pomodoro.milestone_notifications).lower()}"
        )
        lines.append("")

        # Web section
        lines.append("[web]")
        lines.append(f"enabled = {str(self.web.enabled).lower()}")
        lines.append(f"port = {self.web.port}")
        lines.append(f'auth_token = "{self.web.auth_token}"')
        lines.append(f"tls_enabled = {str(self.web.tls_enabled).lower()}")
        lines.append(f'bind_address = "{self.web.bind_address}"')
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
                sort_tier1=db.get("sort_tier1", "completion"),
                sort_tier1_reverse=db.get("sort_tier1_reverse", False),
                sort_tier2=db.get("sort_tier2", "due_date"),
                sort_tier2_reverse=db.get("sort_tier2_reverse", False),
                sort_tier3=db.get("sort_tier3", "priority"),
                sort_tier3_reverse=db.get("sort_tier3_reverse", False),
                view_mode=db.get("view_mode", "list"),
                day_start_hour=db.get("day_start_hour", 0),
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
                auto_sync_trusted=disc.get("auto_sync_trusted", False),
                auto_sync_delay=disc.get("auto_sync_delay", 0),
                auto_sync_interval=disc.get("auto_sync_interval", 0),
            )

        if "appearance" in data:
            app = data["appearance"]
            config.appearance = AppearanceConfig(
                theme=app.get("theme", "system"),
                time_format=app.get("time_format", "system"),
                close_to_tray=app.get("close_to_tray", True),
                font=app.get("font", "bundled"),
            )

        if "pomodoro" in data:
            pom = data["pomodoro"]
            config.pomodoro = PomodoroConfig(
                work_duration=pom.get("work_duration", 25),
                break_duration=pom.get("break_duration", 5),
                long_break_duration=pom.get("long_break_duration", 15),
                sessions_before_long_break=pom.get("sessions_before_long_break", 4),
                auto_start_break=pom.get("auto_start_break", True),
                sound_enabled=pom.get("sound_enabled", False),
                sound_volume=pom.get("sound_volume", 50),
                daily_goal=pom.get("daily_goal", 0),
                milestone_notifications=pom.get("milestone_notifications", True),
            )

        if "web" in data:
            w = data["web"]
            config.web = WebConfig(
                enabled=w.get("enabled", False),
                port=w.get("port", 8080),
                auth_token=w.get("auth_token", ""),
                tls_enabled=w.get("tls_enabled", True),
                bind_address=w.get("bind_address", "0.0.0.0"),
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
        self.db_file = self.data_dir / "pytodo-qt.db"  # SQLite database
        self.legacy_json_file = self.data_dir / "pytodo-qt-db.json"  # For migration
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
