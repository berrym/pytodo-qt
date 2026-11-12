"""config.py

TOML-based configuration system with dataclass support.
"""

from __future__ import annotations

import socket
import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
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
    # When True, view_mode is rewritten every time the user switches
    # views so the next app start restores whatever they were last
    # looking at. When False, view_mode is the "default view" the
    # user picked in Settings and view switches don't mutate it.
    remember_last_view: bool = True
    calendar_sub_view: str = "week"  # "day", "week", "month", "timeline", or "agenda"
    timeline_sub_view: str = (
        "tasks"  # "tasks", "daily", "productivity", "accuracy", "timing", or "cycle"
    )
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

    def block_range(self, block: str) -> tuple[int, int] | None:
        """Return the (start, end) of a named time block in minutes.

        Both values are offsets from midnight at the start of the day the
        block belongs to, so a block that begins or runs past midnight
        has values of 1440 or more: with the default night range of
        21:00-06:00, ``late_night`` is (1530, 1800), i.e. 01:30-06:00 on
        the following calendar day.

        - ``morning``, ``afternoon``, ``evening`` and ``night`` span their
          configured range. ``night`` is the whole range, although
          ``block_for_hour`` reports only its first half under that name.
        - ``early_X`` is the first half of ``X`` and ``late_X`` the
          second, split at the midpoint to the minute. A range whose end
          hour is not after its start hour is taken to cross midnight.
        - ``noon`` and ``midnight`` are the fixed bands 11:30-12:30 and
          23:30-00:30.

        Returns None for an unrecognized name and for a zero-length
        configured range.
        """
        fixed = {
            "noon": (11 * 60 + 30, 12 * 60 + 30),
            "midnight": (23 * 60 + 30, 24 * 60 + 30),
        }
        if block in fixed:
            return fixed[block]

        half: str | None = None
        parent = block
        for prefix in ("early_", "late_"):
            if block.startswith(prefix):
                half = prefix
                parent = block[len(prefix) :]
                break

        bounds = {
            "morning": (self.morning_start, self.morning_end),
            "afternoon": (self.afternoon_start, self.afternoon_end),
            "evening": (self.evening_start, self.evening_end),
            "night": (self.night_start, self.night_end),
        }.get(parent)
        if bounds is None:
            return None

        start_hour, end_hour = bounds
        span = ((end_hour - start_hour) % 24) * 60
        if span == 0:
            return None
        start = (start_hour % 24) * 60
        end = start + span
        if half == "early_":
            end = start + span // 2
        elif half == "late_":
            start = start + span // 2
        return (start, end)

    def next_occurrence(self, block: str, now: datetime) -> date | None:
        """Return the date of the next occurrence of a named block.

        That is today while today's block is still to come or under
        way, and tomorrow once it has ended. Returns None for a block
        that cannot be resolved.
        """
        block_range = self.block_range(block)
        if block_range is None:
            return None
        today = now.date()
        end = datetime.combine(today, time.min) + timedelta(minutes=block_range[1])
        return today if now < end else today + timedelta(days=1)

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


DUE_NOW_MODES = ("deadlines", "all", "off")
LEAD_MINUTES_RANGE = (1, 120)


def _clock_setting(section: dict[str, Any], key: str, default: time) -> time:
    """Read an "HH:MM" time of day from a config section.

    A TOML local time (``09:00:00``, unquoted) is accepted as well.
    Anything else falls back to the default.
    """
    if key not in section:
        return default
    value = section[key]
    if isinstance(value, time):
        return time(value.hour, value.minute)
    if isinstance(value, str):
        try:
            parsed = datetime.strptime(value.strip(), "%H:%M")
        except ValueError:
            pass
        else:
            return parsed.time()
    logger.log.warning(
        'Ignoring [notifications] %s = %r: expected a time such as "09:00"', key, value
    )
    return default


def _flag_setting(section: dict[str, Any], key: str, default: bool) -> bool:
    """Read a true/false value from a config section."""
    if key not in section:
        return default
    value = section[key]
    if isinstance(value, bool):
        return value
    logger.log.warning("Ignoring [notifications] %s = %r: expected true or false", key, value)
    return default


@dataclass
class NotificationConfig:
    """Task notification settings.

    Covers the daily summary, the reminders around a timed task, and
    when notifications are held back. Focus-session and milestone
    notifications are configured with the focus timer.
    """

    enabled: bool = True  # Master switch for every task notification
    summary_enabled: bool = True  # Daily summary
    summary_time: time = time(9, 0)
    lead_enabled: bool = True  # Reminder ahead of a timed task
    lead_minutes: int = 15
    due_now: str = "deadlines"  # Alert at the due time: deadlines, all, off
    quiet_hours_enabled: bool = True
    quiet_start: time = time(22, 0)
    quiet_end: time = time(7, 0)
    quiet_allow_timed: bool = True  # Timed reminders are delivered in quiet hours
    hold_during_focus: bool = True  # The summary waits for a focus session to end

    @classmethod
    def from_dict(cls, section: dict[str, Any]) -> NotificationConfig:
        """Build the settings from a ``[notifications]`` section.

        A value of the wrong kind is ignored in favor of its default.

        Sections written before these keys existed are read as well:

        - ``check_hour = N`` gives ``summary_time`` of N:00.
        - ``notify_overdue`` and ``notify_due_today`` both false give
          ``summary_enabled`` false.
        - ``upcoming_days`` is ignored; nothing used it.

        A current key takes precedence over the key it replaces. The
        old keys are not written back.
        """
        defaults = cls()

        if "summary_time" in section or "check_hour" not in section:
            summary_time = _clock_setting(section, "summary_time", defaults.summary_time)
        else:
            hour = section["check_hour"]
            if isinstance(hour, int) and not isinstance(hour, bool) and 0 <= hour <= 23:
                summary_time = time(hour, 0)
            else:
                logger.log.warning(
                    "Ignoring [notifications] check_hour = %r: expected an hour from 0 to 23",
                    hour,
                )
                summary_time = defaults.summary_time

        if "summary_enabled" in section:
            summary_enabled = _flag_setting(section, "summary_enabled", defaults.summary_enabled)
        else:
            summary_enabled = _flag_setting(section, "notify_overdue", True) or _flag_setting(
                section, "notify_due_today", True
            )

        lead_minutes = section.get("lead_minutes", defaults.lead_minutes)
        low, high = LEAD_MINUTES_RANGE
        if not isinstance(lead_minutes, int) or isinstance(lead_minutes, bool):
            logger.log.warning(
                "Ignoring [notifications] lead_minutes = %r: expected a whole number", lead_minutes
            )
            lead_minutes = defaults.lead_minutes
        elif not low <= lead_minutes <= high:
            logger.log.warning(
                "[notifications] lead_minutes = %r is outside %d-%d; using the nearest limit",
                lead_minutes,
                low,
                high,
            )
            lead_minutes = min(max(lead_minutes, low), high)

        due_now = section.get("due_now", defaults.due_now)
        if due_now not in DUE_NOW_MODES:
            logger.log.warning(
                "Ignoring [notifications] due_now = %r: expected one of %s",
                due_now,
                ", ".join(DUE_NOW_MODES),
            )
            due_now = defaults.due_now

        return cls(
            enabled=_flag_setting(section, "enabled", defaults.enabled),
            summary_enabled=summary_enabled,
            summary_time=summary_time,
            lead_enabled=_flag_setting(section, "lead_enabled", defaults.lead_enabled),
            lead_minutes=lead_minutes,
            due_now=due_now,
            quiet_hours_enabled=_flag_setting(
                section, "quiet_hours_enabled", defaults.quiet_hours_enabled
            ),
            quiet_start=_clock_setting(section, "quiet_start", defaults.quiet_start),
            quiet_end=_clock_setting(section, "quiet_end", defaults.quiet_end),
            quiet_allow_timed=_flag_setting(
                section, "quiet_allow_timed", defaults.quiet_allow_timed
            ),
            hold_during_focus=_flag_setting(
                section, "hold_during_focus", defaults.hold_during_focus
            ),
        )

    def to_toml_lines(self) -> list[str]:
        """The body of the ``[notifications]`` section."""

        def flag(value: bool) -> str:
            return str(value).lower()

        def clock(value: time) -> str:
            return f'"{value:%H:%M}"'

        return [
            f"enabled = {flag(self.enabled)}",
            f"summary_enabled = {flag(self.summary_enabled)}",
            f"summary_time = {clock(self.summary_time)}",
            f"lead_enabled = {flag(self.lead_enabled)}",
            f"lead_minutes = {self.lead_minutes}",
            f'due_now = "{self.due_now}"',
            f"quiet_hours_enabled = {flag(self.quiet_hours_enabled)}",
            f"quiet_start = {clock(self.quiet_start)}",
            f"quiet_end = {clock(self.quiet_end)}",
            f"quiet_allow_timed = {flag(self.quiet_allow_timed)}",
            f"hold_during_focus = {flag(self.hold_during_focus)}",
        ]


@dataclass
class AppearanceConfig:
    """UI appearance settings."""

    theme: str = "system"  # light, dark, system
    time_format: str = "system"  # system, 12h, 24h
    close_to_tray: bool = True
    start_minimized_to_tray: bool = False  # hide to tray on launch (or minimize if no tray)
    font: str = "system"  # "system", "bundled", or custom family name


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
        lines.append(f"remember_last_view = {str(self.database.remember_last_view).lower()}")
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
        lines.append(
            f"start_minimized_to_tray = {str(self.appearance.start_minimized_to_tray).lower()}"
        )
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
        lines.extend(self.notifications.to_toml_lines())
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
                remember_last_view=db.get("remember_last_view", True),
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
                start_minimized_to_tray=app.get("start_minimized_to_tray", False),
                font=app.get("font", "system"),
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
            config.notifications = NotificationConfig.from_dict(data["notifications"])

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
                device_inactivity_days=w.get("device_inactivity_days", 30),
            )

        return config


class ConfigManager:
    """Manages application configuration with TOML storage."""

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
        self.db_file = self.data_dir / "pytodo-qt.db"  # SQLite database
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
        """Load configuration from the TOML file, falling back to defaults."""
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

        # Create default config
        logger.log.info("Creating default configuration")
        self._config = AppConfig()
        self.save()
        return self._config

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
