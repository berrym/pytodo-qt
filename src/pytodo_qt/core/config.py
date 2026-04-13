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
    view_mode: str = "list"  # "list", "board", or "calendar"
    calendar_sub_view: str = "week"  # "day", "week", "month", or "timeline"
    timeline_sub_view: str = "tasks"  # "tasks", "daily", "productivity", or "accuracy"
    sort_updated_at: float = 0.0  # Timestamp of last sort config change
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
    tls_enabled: bool = True  # TLS with auto-generated self-signed cert
    bind_address: str = "0.0.0.0"  # "0.0.0.0" or "127.0.0.1"
    connect_method: str = ""  # Remembered wizard preference: "", "quick", or "trusted"
    ca_generation: int = 0  # Incremented on CA cert regeneration
    caldav_enabled: bool = True  # CalDAV server on /caldav/ path
    caldav_password: str = ""  # Auto-generated on first use
    device_inactivity_days: int = 30  # Auto-remove devices inactive for N days (0 = disabled)


@dataclass
class StopwatchConfig:
    """Stopwatch time tracking settings."""

    minimum_session: int = 60  # seconds — below this, session is discarded (0 = record all)
    idle_timeout: int = 0  # minutes — auto-pause after no interaction (0 = disabled)
    show_in_status_bar: bool = True  # show elapsed time in status bar
    sound_on_stop: bool = False  # play sound when session recorded


@dataclass
class TimeBlockConfig:
    """Configurable time block boundaries for named time windows.

    Users say "morning", "evening", etc. These define what hours
    those words map to. early_X/late_X are derived as first/second
    halves of the parent range.
    """

    morning_start: int = 6  # hour (0-23)
    morning_end: int = 12
    afternoon_start: int = 12
    afternoon_end: int = 17
    evening_start: int = 17
    evening_end: int = 21
    night_start: int = 21
    night_end: int = 6  # crosses midnight

    def block_for_hour(self, hour: int) -> str:
        """Return the canonical time block name for an hour of the day.

        Each configured range (morning/afternoon/evening/night) is
        split at its midpoint into the early and late halves, matching
        the vocabulary users speak ("early morning", "late afternoon",
        etc.). The night range crosses midnight and is handled with
        wraparound arithmetic.

        Hours outside every configured range are impossible with the
        default configuration, which covers all 24 hours contiguously.
        If a user has set custom values that leave a gap, the function
        falls back to "morning" rather than raising — the caller is
        usually rendering a chart and would rather get a label than
        crash.
        """
        h = hour % 24

        if self.morning_start <= h < self.morning_end:
            midpoint = (self.morning_start + self.morning_end) / 2
            return "early_morning" if h < midpoint else "late_morning"

        if self.afternoon_start <= h < self.afternoon_end:
            midpoint = (self.afternoon_start + self.afternoon_end) / 2
            return "early_afternoon" if h < midpoint else "late_afternoon"

        if self.evening_start <= h < self.evening_end:
            midpoint = (self.evening_start + self.evening_end) / 2
            return "early_evening" if h < midpoint else "late_evening"

        # Night range may cross midnight: [night_start, 24) ∪ [0, night_end).
        in_night = h >= self.night_start or h < self.night_end
        if in_night:
            span = (24 - self.night_start) + self.night_end
            if span <= 0:
                # Degenerate config — no night range at all.
                return "morning"
            offset = h - self.night_start if h >= self.night_start else (24 - self.night_start) + h
            return "night" if offset < span / 2 else "late_night"

        return "morning"


@dataclass
class NotificationConfig:
    """Task reminder notification settings."""

    enabled: bool = True  # Desktop notifications for due/overdue items
    upcoming_days: int = 3  # Show items due within N days in Upcoming
    check_hour: int = 9  # Hour (0-23) for daily notification check
    notify_overdue: bool = True  # Notify about overdue items
    notify_due_today: bool = True  # Notify about items due today


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
    time_blocks: TimeBlockConfig = field(default_factory=TimeBlockConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    pomodoro: PomodoroConfig = field(default_factory=PomodoroConfig)
    stopwatch: StopwatchConfig = field(default_factory=StopwatchConfig)
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
        lines.append(f'calendar_sub_view = "{self.database.calendar_sub_view}"')
        lines.append(f'timeline_sub_view = "{self.database.timeline_sub_view}"')
        lines.append(f"sort_updated_at = {self.database.sort_updated_at}")
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

        # Time blocks section
        lines.append("[time_blocks]")
        lines.append(f"morning_start = {self.time_blocks.morning_start}")
        lines.append(f"morning_end = {self.time_blocks.morning_end}")
        lines.append(f"afternoon_start = {self.time_blocks.afternoon_start}")
        lines.append(f"afternoon_end = {self.time_blocks.afternoon_end}")
        lines.append(f"evening_start = {self.time_blocks.evening_start}")
        lines.append(f"evening_end = {self.time_blocks.evening_end}")
        lines.append(f"night_start = {self.time_blocks.night_start}")
        lines.append(f"night_end = {self.time_blocks.night_end}")
        lines.append("")

        # Notifications section
        lines.append("[notifications]")
        lines.append(f"enabled = {str(self.notifications.enabled).lower()}")
        lines.append(f"upcoming_days = {self.notifications.upcoming_days}")
        lines.append(f"check_hour = {self.notifications.check_hour}")
        lines.append(f"notify_overdue = {str(self.notifications.notify_overdue).lower()}")
        lines.append(f"notify_due_today = {str(self.notifications.notify_due_today).lower()}")
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

        # Stopwatch section
        lines.append("[stopwatch]")
        lines.append(f"minimum_session = {self.stopwatch.minimum_session}")
        lines.append(f"idle_timeout = {self.stopwatch.idle_timeout}")
        lines.append(f"show_in_status_bar = {str(self.stopwatch.show_in_status_bar).lower()}")
        lines.append(f"sound_on_stop = {str(self.stopwatch.sound_on_stop).lower()}")
        lines.append("")

        # Web section
        lines.append("[web]")
        lines.append(f"enabled = {str(self.web.enabled).lower()}")
        lines.append(f"port = {self.web.port}")
        lines.append(f"tls_enabled = {str(self.web.tls_enabled).lower()}")
        lines.append(f'bind_address = "{self.web.bind_address}"')
        lines.append(f'connect_method = "{self.web.connect_method}"')
        lines.append(f"ca_generation = {self.web.ca_generation}")
        lines.append(f"caldav_enabled = {str(self.web.caldav_enabled).lower()}")
        lines.append(f'caldav_password = "{self.web.caldav_password}"')
        lines.append(f"device_inactivity_days = {self.web.device_inactivity_days}")
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
                sort_updated_at=float(db.get("sort_updated_at", 0.0)),
                view_mode=db.get("view_mode", "list"),
                calendar_sub_view=db.get("calendar_sub_view", "week"),
                timeline_sub_view=db.get("timeline_sub_view", "tasks"),
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

        if "stopwatch" in data:
            sw = data["stopwatch"]
            config.stopwatch = StopwatchConfig(
                minimum_session=sw.get("minimum_session", 60),
                idle_timeout=sw.get("idle_timeout", 0),
                show_in_status_bar=sw.get("show_in_status_bar", True),
                sound_on_stop=sw.get("sound_on_stop", False),
            )

        if "notifications" in data:
            n = data["notifications"]
            config.notifications = NotificationConfig(
                enabled=n.get("enabled", True),
                upcoming_days=n.get("upcoming_days", 3),
                check_hour=n.get("check_hour", 9),
                notify_overdue=n.get("notify_overdue", True),
                notify_due_today=n.get("notify_due_today", True),
            )

        if "time_blocks" in data:
            tb = data["time_blocks"]
            config.time_blocks = TimeBlockConfig(
                morning_start=tb.get("morning_start", 6),
                morning_end=tb.get("morning_end", 12),
                afternoon_start=tb.get("afternoon_start", 12),
                afternoon_end=tb.get("afternoon_end", 17),
                evening_start=tb.get("evening_start", 17),
                evening_end=tb.get("evening_end", 21),
                night_start=tb.get("night_start", 21),
                night_end=tb.get("night_end", 6),
            )

        if "web" in data:
            w = data["web"]
            config.web = WebConfig(
                enabled=w.get("enabled", False),
                port=w.get("port", 8080),
                tls_enabled=w.get("tls_enabled", True),
                bind_address=w.get("bind_address", "0.0.0.0"),
                connect_method=w.get("connect_method", ""),
                ca_generation=w.get("ca_generation", 0),
                caldav_enabled=w.get("caldav_enabled", True),
                caldav_password=w.get("caldav_password", ""),
                device_inactivity_days=w.get("device_inactivity_days", 30),
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
