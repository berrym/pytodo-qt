"""device_store.py

SQLite-backed storage for paired mobile devices.

Each device that pairs via PIN gets a unique auth token stored here.
The database lives in the config directory alongside TLS certificates,
separate from the main todo database.
"""

from __future__ import annotations

import re
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from pytodo_qt.core.logger import Logger

logger = Logger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS paired_devices (
    id TEXT PRIMARY KEY,
    token TEXT NOT NULL UNIQUE,
    device_name TEXT NOT NULL,
    user_agent TEXT NOT NULL,
    pairing_method TEXT NOT NULL,
    ca_generation INTEGER NOT NULL,
    paired_at INTEGER NOT NULL,
    last_seen INTEGER NOT NULL
)
"""


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class PairedDevice:
    """A mobile device that has paired via PIN."""

    id: str = field(default_factory=lambda: str(uuid4()))
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    device_name: str = ""
    user_agent: str = ""
    pairing_method: str = "quick"  # "quick" or "trusted"
    ca_generation: int = 0
    paired_at: int = field(default_factory=_now_ms)
    last_seen: int = field(default_factory=_now_ms)


# --- User-Agent parsing ---

# Order matters: more specific patterns first
_UA_PATTERNS: list[tuple[str, str | None]] = [
    # iOS devices
    (r"iPad", "iPad"),
    (r"iPod", "iPod"),
    (r"iPhone", "iPhone"),
    # Samsung — extract model name
    (r"SM-[A-Z]\d{3,4}[A-Za-z]*", None),  # raw model, mapped below
    (r"Samsung\s+(Galaxy\s+\S+)", None),
    # Google Pixel
    (r"Pixel\s+\d+\w*(?:\s+Pro)?(?:\s+XL)?", None),
    # Generic Android with device model in parentheses
    (r";\s*([^;)]+)\s+Build/", None),
    # Generic Android fallback (no specific model)
    (r"Android", "Android device"),
    # Desktop browsers
    (r"Macintosh", "Mac"),
    (r"Windows NT", "Windows PC"),
    (r"CrOS", "Chromebook"),
    (r"Linux(?!.*Android)", "Linux PC"),
]

# Common Samsung model prefixes
_SAMSUNG_MODELS: dict[str, str] = {
    "SM-S": "Samsung Galaxy S",
    "SM-A": "Samsung Galaxy A",
    "SM-F": "Samsung Galaxy Z Fold",
    "SM-G": "Samsung Galaxy S",
    "SM-N": "Samsung Galaxy Note",
    "SM-T": "Samsung Galaxy Tab",
    "SM-X": "Samsung Galaxy Tab",
}


def parse_device_name(user_agent: str) -> str:
    """Extract a human-readable device name from a User-Agent string.

    Examples:
        "Mozilla/5.0 (iPhone; ...)" → "iPhone"
        "Mozilla/5.0 (Linux; Android 14; Pixel 8 ...)" → "Pixel 8"
        "Mozilla/5.0 (Linux; Android 14; SM-S918B ...)" → "Samsung Galaxy S"
    """
    if not user_agent:
        return "Unknown device"

    # Check for iPad/iPhone/iPod first (simple string match)
    for pattern, label in _UA_PATTERNS:
        match = re.search(pattern, user_agent)
        if not match:
            continue

        if label is not None:
            return label

        # Dynamic extraction
        text = match.group(0).strip()

        # Samsung model number → friendly name
        for prefix, name in _SAMSUNG_MODELS.items():
            if text.startswith(prefix):
                return name

        # Pixel or captured group
        if text.startswith("Pixel"):
            return text

        # Generic Android Build/ capture — clean up
        if match.lastindex and match.lastindex >= 1:
            name = match.group(1).strip()
            # Skip overly generic names
            if name.lower() not in ("linux", "android", "mobile", "wv"):
                return name

        return text

    return "Unknown device"


class WebDeviceStore:
    """Manages paired mobile devices in a SQLite database."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        """Open the database, creating the table if needed.

        If the database is corrupt, renames it and creates a fresh one.
        """
        try:
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(_CREATE_TABLE)
            self._conn.commit()
        except sqlite3.DatabaseError:
            logger.log.warning("Device database corrupt — recreating: %s", self._db_path)
            if self._conn:
                self._conn.close()
                self._conn = None
            corrupt_path = self._db_path.with_suffix(".db.corrupt")
            if self._db_path.exists():
                self._db_path.rename(corrupt_path)
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(_CREATE_TABLE)
            self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def add_device(
        self,
        device_name: str,
        user_agent: str,
        pairing_method: str,
        ca_generation: int,
    ) -> PairedDevice:
        """Create and store a new paired device with a unique token."""
        assert self._conn is not None
        now = _now_ms()
        device = PairedDevice(
            device_name=device_name,
            user_agent=user_agent,
            pairing_method=pairing_method,
            ca_generation=ca_generation,
            paired_at=now,
            last_seen=now,
        )
        self._conn.execute(
            "INSERT INTO paired_devices"
            " (id, token, device_name, user_agent, pairing_method,"
            "  ca_generation, paired_at, last_seen)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                device.id,
                device.token,
                device.device_name,
                device.user_agent,
                device.pairing_method,
                device.ca_generation,
                device.paired_at,
                device.last_seen,
            ),
        )
        self._conn.commit()
        return device

    def get_device_by_token(self, token: str) -> PairedDevice | None:
        """Look up a device by its auth token."""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT id, token, device_name, user_agent, pairing_method,"
            " ca_generation, paired_at, last_seen"
            " FROM paired_devices WHERE token = ?",
            (token,),
        ).fetchone()
        if row is None:
            return None
        return PairedDevice(
            id=row[0],
            token=row[1],
            device_name=row[2],
            user_agent=row[3],
            pairing_method=row[4],
            ca_generation=row[5],
            paired_at=row[6],
            last_seen=row[7],
        )

    def get_all_devices(self) -> list[PairedDevice]:
        """Return all paired devices, ordered by most recently paired first."""
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT id, token, device_name, user_agent, pairing_method,"
            " ca_generation, paired_at, last_seen"
            " FROM paired_devices ORDER BY paired_at DESC",
        ).fetchall()
        return [
            PairedDevice(
                id=r[0],
                token=r[1],
                device_name=r[2],
                user_agent=r[3],
                pairing_method=r[4],
                ca_generation=r[5],
                paired_at=r[6],
                last_seen=r[7],
            )
            for r in rows
        ]

    def remove_device(self, device_id: str) -> bool:
        """Remove a device by ID. Returns True if a device was removed."""
        assert self._conn is not None
        cursor = self._conn.execute("DELETE FROM paired_devices WHERE id = ?", (device_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    def remove_all_devices(self) -> int:
        """Remove all paired devices. Returns count removed."""
        assert self._conn is not None
        cursor = self._conn.execute("DELETE FROM paired_devices")
        self._conn.commit()
        return cursor.rowcount

    def update_last_seen(self, device_id: str) -> None:
        """Update the last_seen timestamp for a device."""
        assert self._conn is not None
        self._conn.execute(
            "UPDATE paired_devices SET last_seen = ? WHERE id = ?",
            (_now_ms(), device_id),
        )
        self._conn.commit()

    def get_active_tokens(self) -> set[str]:
        """Return the set of all active device tokens."""
        assert self._conn is not None
        rows = self._conn.execute("SELECT token FROM paired_devices").fetchall()
        return {r[0] for r in rows}

    def remove_inactive_devices(self, max_age_ms: int) -> int:
        """Remove devices not seen within *max_age_ms* milliseconds.

        Returns the number of devices removed.
        """
        assert self._conn is not None
        cutoff = _now_ms() - max_age_ms
        cursor = self._conn.execute(
            "DELETE FROM paired_devices WHERE last_seen < ?",
            (cutoff,),
        )
        self._conn.commit()
        return cursor.rowcount

    def get_stale_devices(self, current_ca_generation: int) -> list[PairedDevice]:
        """Return devices paired at an older CA generation (need cert reinstall)."""
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT id, token, device_name, user_agent, pairing_method,"
            " ca_generation, paired_at, last_seen"
            " FROM paired_devices WHERE ca_generation < ?"
            " ORDER BY paired_at DESC",
            (current_ca_generation,),
        ).fetchall()
        return [
            PairedDevice(
                id=r[0],
                token=r[1],
                device_name=r[2],
                user_agent=r[3],
                pairing_method=r[4],
                ca_generation=r[5],
                paired_at=r[6],
                last_seen=r[7],
            )
            for r in rows
        ]
