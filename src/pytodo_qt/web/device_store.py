"""device_store.py

SQLite-backed storage for paired mobile devices.

Each device that pairs via PIN gets a unique auth token. The token is
given to the device once, in the answer to its pairing, and only a hash
of it is stored here: a copy of the file that leaves the protection of
its permissions (a backup, a copied configuration directory, a disk
read from another system) holds nothing a device could present (#85).
The database lives in the config directory alongside TLS certificates,
separate from the main todo database.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from pytodo_qt.core.logger import Logger
from pytodo_qt.core.private_files import create_private_file, make_private

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
    last_seen INTEGER NOT NULL,
    address TEXT NOT NULL DEFAULT ''
)
"""

_COLUMNS = "id, token, device_name, user_agent, pairing_method, ca_generation, paired_at, last_seen, address"

# What is read back of a device: everything but its token, which is not
# kept.
_READ = "id, device_name, user_agent, pairing_method, ca_generation, paired_at, last_seen, address"

# The form of a stored token: this prefix and the hex SHA-256 of the
# token. A token as issued (secrets.token_urlsafe) has no colon, so a
# row an earlier version wrote is told apart by the prefix.
TOKEN_HASH_PREFIX = "sha256:"


def token_hash(token: str) -> str:
    """What is stored, and looked up, for ``token``.

    One SHA-256 without salt: a token is 32 random bytes, so there is
    nothing to guess, and a slow hash would add its time to every
    request for nothing.
    """
    return TOKEN_HASH_PREFIX + hashlib.sha256(token.encode("utf-8")).hexdigest()


def _device(row: tuple) -> PairedDevice:
    """A device read back from the store: without a token."""
    return PairedDevice(
        id=row[0],
        token="",
        device_name=row[1],
        user_agent=row[2],
        pairing_method=row[3],
        ca_generation=row[4],
        paired_at=row[5],
        last_seen=row[6],
        address=row[7],
    )


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class PairedDevice:
    """A mobile device that has paired via PIN."""

    id: str = field(default_factory=lambda: str(uuid4()))
    # The token as issued, on the device that add_device returns, to be
    # given to the device once; empty on a device read back from the
    # store, which keeps only its hash.
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    device_name: str = ""
    user_agent: str = ""
    pairing_method: str = "quick"  # "quick" or "trusted"
    ca_generation: int = 0
    paired_at: int = field(default_factory=_now_ms)
    last_seen: int = field(default_factory=_now_ms)
    # The address the device paired at, as its browser named the server:
    # "planner.local:8080" or "192.168.1.20:8080". A browser keeps the
    # token for that address only, so this is where the device has to be
    # sent back to. Empty for a device paired before addresses were kept.
    address: str = ""


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

        The database holds a hash of every paired device's token. Its
        file is created for this account only, and SQLite gives the files
        it keeps beside it the same permissions; files an earlier version
        created are restricted. Tokens an earlier version stored as issued
        are replaced by their hashes (_hash_stored_tokens).
        """
        self._restrict_files()
        try:
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
            )
            self._prepare()
        except sqlite3.DatabaseError:
            logger.log.warning("Device database corrupt — recreating: %s", self._db_path)
            if self._conn:
                self._conn.close()
                self._conn = None
            corrupt_path = self._db_path.with_suffix(".db.corrupt")
            if self._db_path.exists():
                self._db_path.rename(corrupt_path)
            self._restrict_files()
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
            )
            self._prepare()
        # The file set aside as corrupt held tokens as an earlier
        # version stored them; the store is open without it.
        with contextlib.suppress(OSError):
            self._db_path.with_suffix(".db.corrupt").unlink(missing_ok=True)

    def _prepare(self) -> None:
        """Bring an open database to this version's form."""
        assert self._conn is not None
        # What is deleted or overwritten is overwritten with zeros, not
        # left in free pages, where a copy of the file would keep it.
        self._conn.execute("PRAGMA secure_delete=ON")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_TABLE)
        self._add_missing_columns()
        self._conn.commit()
        self._hash_stored_tokens()

    def _hash_stored_tokens(self) -> None:
        """Replace each token an earlier version stored as issued by its
        hash, so that paired devices go on working.

        In one transaction: a row is converted with all the others or not
        at all. A converted row is not converted again. Then the file is
        rebuilt (VACUUM) and the write-ahead log emptied into it and cut
        to nothing, so that no copy of a token as issued is left in a
        free page or a log frame.
        """
        assert self._conn is not None
        with self._conn:
            rows = self._conn.execute(
                "SELECT id, token FROM paired_devices WHERE substr(token, 1, ?) != ?",
                (len(TOKEN_HASH_PREFIX), TOKEN_HASH_PREFIX),
            ).fetchall()
            for device_id, token in rows:
                self._conn.execute(
                    "UPDATE paired_devices SET token = ? WHERE id = ?",
                    (token_hash(token), device_id),
                )
        if not rows:
            return
        # Outside any transaction: VACUUM cannot run in one.
        self._conn.execute("VACUUM")
        self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        logger.log.info("Device tokens: %d stored as hashes", len(rows))

    def _add_missing_columns(self) -> None:
        """Bring a table made by an earlier version up to this one."""
        assert self._conn is not None
        present = {row[1] for row in self._conn.execute("PRAGMA table_info(paired_devices)")}
        if "address" not in present:
            self._conn.execute(
                "ALTER TABLE paired_devices ADD COLUMN address TEXT NOT NULL DEFAULT ''"
            )

    def _restrict_files(self) -> None:
        """Create the database file private, and restrict what exists."""
        create_private_file(self._db_path)
        make_private(self._db_path)
        for suffix in ("-wal", "-shm"):
            make_private(self._db_path.with_name(self._db_path.name + suffix))
        make_private(self._db_path.with_suffix(".db.corrupt"))

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
        address: str = "",
    ) -> PairedDevice:
        """Create and store a new paired device with a unique token.

        The device returned carries the token as issued, to be given to
        the device; the store keeps only its hash.
        """
        assert self._conn is not None
        now = _now_ms()
        device = PairedDevice(
            device_name=device_name,
            user_agent=user_agent,
            pairing_method=pairing_method,
            ca_generation=ca_generation,
            paired_at=now,
            last_seen=now,
            address=address,
        )
        self._conn.execute(
            f"INSERT INTO paired_devices ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                device.id,
                token_hash(device.token),
                device.device_name,
                device.user_agent,
                device.pairing_method,
                device.ca_generation,
                device.paired_at,
                device.last_seen,
                device.address,
            ),
        )
        self._conn.commit()
        return device

    def get_device_by_token(self, token: str) -> PairedDevice | None:
        """Look up a device by the token it presents.

        The hash of what is presented is looked up. The time the lookup
        takes depends on the hash only, which tells nothing of a token.
        """
        assert self._conn is not None
        if not token:
            return None
        row = self._conn.execute(
            f"SELECT {_READ} FROM paired_devices WHERE token = ?",
            (token_hash(token),),
        ).fetchone()
        return None if row is None else _device(row)

    def get_all_devices(self) -> list[PairedDevice]:
        """Return all paired devices, ordered by most recently paired first."""
        assert self._conn is not None
        rows = self._conn.execute(
            f"SELECT {_READ} FROM paired_devices ORDER BY paired_at DESC",
        ).fetchall()
        return [_device(row) for row in rows]

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

    def rename_device(self, device_id: str, new_name: str) -> bool:
        """Rename a device. Returns True if a device was updated."""
        assert self._conn is not None
        cursor = self._conn.execute(
            "UPDATE paired_devices SET device_name = ? WHERE id = ?",
            (new_name, device_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def update_last_seen(self, device_id: str) -> None:
        """Update the last_seen timestamp for a device."""
        assert self._conn is not None
        self._conn.execute(
            "UPDATE paired_devices SET last_seen = ? WHERE id = ?",
            (_now_ms(), device_id),
        )
        self._conn.commit()

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
            f"SELECT {_READ} FROM paired_devices WHERE ca_generation < ? ORDER BY paired_at DESC",
            (current_ca_generation,),
        ).fetchall()
        return [_device(row) for row in rows]
