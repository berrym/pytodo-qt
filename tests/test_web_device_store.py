"""Tests for WebDeviceStore — paired mobile device tracking."""

from __future__ import annotations

from pathlib import Path

from pytodo_qt.web.device_store import (
    PairedDevice,
    WebDeviceStore,
    parse_device_name,
)


class TestParseDeviceName:
    """User-Agent string parsing to human-readable device names."""

    def test_iphone(self):
        ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15"
        assert parse_device_name(ua) == "iPhone"

    def test_ipad(self):
        ua = "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15"
        assert parse_device_name(ua) == "iPad"

    def test_ipod(self):
        ua = "Mozilla/5.0 (iPod touch; CPU iPhone OS 15_0 like Mac OS X)"
        assert parse_device_name(ua) == "iPod"

    def test_pixel(self):
        ua = "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36"
        assert parse_device_name(ua) == "Pixel 8 Pro"

    def test_pixel_simple(self):
        ua = "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36"
        assert parse_device_name(ua) == "Pixel 9"

    def test_samsung_s_series(self):
        ua = "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36"
        assert parse_device_name(ua) == "Samsung Galaxy S"

    def test_samsung_a_series(self):
        ua = "Mozilla/5.0 (Linux; Android 14; SM-A546B) AppleWebKit/537.36"
        assert parse_device_name(ua) == "Samsung Galaxy A"

    def test_samsung_tab(self):
        ua = "Mozilla/5.0 (Linux; Android 14; SM-T870) AppleWebKit/537.36"
        assert parse_device_name(ua) == "Samsung Galaxy Tab"

    def test_samsung_fold(self):
        ua = "Mozilla/5.0 (Linux; Android 14; SM-F946B) AppleWebKit/537.36"
        assert parse_device_name(ua) == "Samsung Galaxy Z Fold"

    def test_generic_android_with_model(self):
        ua = "Mozilla/5.0 (Linux; Android 13; RMX3630 Build/TP1A) AppleWebKit/537.36"
        assert parse_device_name(ua) == "RMX3630"

    def test_mac(self):
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        assert parse_device_name(ua) == "Mac"

    def test_windows(self):
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        assert parse_device_name(ua) == "Windows PC"

    def test_chromebook(self):
        ua = "Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36"
        assert parse_device_name(ua) == "Chromebook"

    def test_linux_desktop(self):
        ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        assert parse_device_name(ua) == "Linux PC"

    def test_empty_string(self):
        assert parse_device_name("") == "Unknown device"

    def test_garbage(self):
        assert parse_device_name("not-a-real-ua") == "Unknown device"

    def test_none_like(self):
        assert parse_device_name("Mozilla/5.0") == "Unknown device"


class TestPairedDeviceDataclass:
    """PairedDevice dataclass defaults."""

    def test_defaults_generate_id_and_token(self):
        d = PairedDevice()
        assert d.id  # non-empty uuid string
        assert d.token  # non-empty token string
        assert d.pairing_method == "quick"
        assert d.ca_generation == 0

    def test_two_devices_have_unique_tokens(self):
        d1 = PairedDevice()
        d2 = PairedDevice()
        assert d1.token != d2.token
        assert d1.id != d2.id


class TestWebDeviceStore:
    """CRUD operations on the device store."""

    def _make_store(self, tmp_path: Path) -> WebDeviceStore:
        store = WebDeviceStore(tmp_path / "web_devices.db")
        store.open()
        return store

    def test_open_creates_db_file(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        assert (tmp_path / "web_devices.db").exists()
        store.close()

    def test_add_device(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        device = store.add_device("iPhone", "ua-string", "quick", 0)
        assert device.device_name == "iPhone"
        assert device.user_agent == "ua-string"
        assert device.pairing_method == "quick"
        assert device.ca_generation == 0
        assert device.token  # non-empty
        assert device.id  # non-empty
        store.close()

    def test_add_device_unique_tokens(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        d1 = store.add_device("iPhone", "ua1", "quick", 0)
        d2 = store.add_device("Pixel", "ua2", "trusted", 0)
        assert d1.token != d2.token
        assert d1.id != d2.id
        store.close()

    def test_get_device_by_token(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        added = store.add_device("iPhone", "ua", "quick", 0)
        found = store.get_device_by_token(added.token)
        assert found is not None
        assert found.id == added.id
        assert found.device_name == "iPhone"
        store.close()

    def test_get_device_by_token_not_found(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        assert store.get_device_by_token("nonexistent") is None
        store.close()

    def test_get_all_devices(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        store.add_device("A", "ua1", "quick", 0)
        store.add_device("B", "ua2", "trusted", 0)
        store.add_device("C", "ua3", "quick", 1)
        devices = store.get_all_devices()
        assert len(devices) == 3
        names = {d.device_name for d in devices}
        assert names == {"A", "B", "C"}
        store.close()

    def test_get_all_devices_empty(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        assert store.get_all_devices() == []
        store.close()

    def test_remove_device(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        device = store.add_device("iPhone", "ua", "quick", 0)
        assert store.remove_device(device.id)
        assert store.get_device_by_token(device.token) is None
        store.close()

    def test_remove_device_not_found(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        assert not store.remove_device("nonexistent-id")
        store.close()

    def test_remove_all_devices(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        store.add_device("A", "ua1", "quick", 0)
        store.add_device("B", "ua2", "quick", 0)
        store.add_device("C", "ua3", "quick", 0)
        count = store.remove_all_devices()
        assert count == 3
        assert store.get_all_devices() == []
        store.close()

    def test_remove_all_devices_empty(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        assert store.remove_all_devices() == 0
        store.close()

    def test_update_last_seen(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        device = store.add_device("iPhone", "ua", "quick", 0)
        old_last_seen = device.last_seen

        import time as _time

        _time.sleep(0.01)
        store.update_last_seen(device.id)

        updated = store.get_device_by_token(device.token)
        assert updated is not None
        assert updated.last_seen >= old_last_seen
        store.close()

    def test_rename_device(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        device = store.add_device("Old Name", "ua", "quick", 0)
        assert store.rename_device(device.id, "New Name")
        updated = store.get_device_by_token(device.token)
        assert updated is not None
        assert updated.device_name == "New Name"
        store.close()

    def test_rename_device_not_found(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        assert not store.rename_device("nonexistent", "Name")
        store.close()

    def test_remove_inactive_devices(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        # Add a device and manually backdate its last_seen
        device = store.add_device("Old Phone", "ua", "quick", 0)
        assert store._conn is not None
        # Set last_seen to 60 days ago (in ms)
        old_ts = device.last_seen - (60 * 86_400_000)
        store._conn.execute(
            "UPDATE paired_devices SET last_seen = ? WHERE id = ?",
            (old_ts, device.id),
        )
        store._conn.commit()

        # Add a recent device
        recent = store.add_device("New Phone", "ua2", "quick", 0)

        # Remove devices inactive for >30 days
        removed = store.remove_inactive_devices(30 * 86_400_000)
        assert removed == 1

        # Old device gone, recent device still present
        assert store.get_device_by_token(device.token) is None
        assert store.get_device_by_token(recent.token) is not None
        store.close()

    def test_remove_inactive_devices_none_inactive(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        store.add_device("Active", "ua", "quick", 0)
        removed = store.remove_inactive_devices(30 * 86_400_000)
        assert removed == 0
        assert len(store.get_all_devices()) == 1
        store.close()

    def test_remove_inactive_devices_zero_max_age(self, tmp_path: Path):
        """max_age_ms=0 would remove everything — but caller should not pass 0."""
        store = self._make_store(tmp_path)
        store.add_device("Test", "ua", "quick", 0)
        # With max_age_ms large enough, nothing removed
        removed = store.remove_inactive_devices(999_999_999_999)
        assert removed == 0
        store.close()

    def test_get_stale_devices(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        store.add_device("Old", "ua1", "trusted", 0)
        store.add_device("Also old", "ua2", "trusted", 1)
        store.add_device("Current", "ua3", "trusted", 2)

        stale = store.get_stale_devices(current_ca_generation=2)
        assert len(stale) == 2
        names = {d.device_name for d in stale}
        assert names == {"Old", "Also old"}
        store.close()

    def test_get_stale_devices_none_stale(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        store.add_device("Current", "ua", "trusted", 5)
        assert store.get_stale_devices(current_ca_generation=5) == []
        store.close()

    def test_close_and_reopen_persists(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        device = store.add_device("iPhone", "ua", "quick", 0)
        token = device.token
        store.close()

        store2 = WebDeviceStore(tmp_path / "web_devices.db")
        store2.open()
        found = store2.get_device_by_token(token)
        assert found is not None
        assert found.device_name == "iPhone"
        store2.close()

    def test_corrupt_db_recovery(self, tmp_path: Path):
        """A corrupt database file is renamed and a fresh one is created."""
        db_path = tmp_path / "web_devices.db"
        db_path.write_text("this is not a valid sqlite database")

        store = WebDeviceStore(db_path)
        store.open()  # Should recover without raising

        # The corrupt file was set aside, and is removed once the fresh
        # store is open: it held tokens as an earlier version kept them
        # (#85).
        assert not (tmp_path / "web_devices.db.corrupt").exists()
        assert db_path.read_bytes() != b"this is not a valid sqlite database"

        # Fresh store works
        device = store.add_device("Test", "ua", "quick", 0)
        assert store.get_device_by_token(device.token) is not None
        store.close()

    def test_remove_device_token_no_longer_active(self, tmp_path: Path):
        """Removing a device means its token is no longer accepted."""
        store = self._make_store(tmp_path)
        device = store.add_device("iPhone", "ua", "quick", 0)
        assert store.get_device_by_token(device.token) is not None

        store.remove_device(device.id)
        assert store.get_device_by_token(device.token) is None
        store.close()


class TestTheAddressADevicePairedAt:
    """A browser keeps a device's token for the address it paired at and
    no other, so that is where the device has to be sent back to
    (#113)."""

    def _make_store(self, tmp_path: Path) -> WebDeviceStore:
        store = WebDeviceStore(tmp_path / "web_devices.db")
        store.open()
        return store

    def test_it_is_kept_with_the_device(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        device = store.add_device("Mac", "ua", "quick", 0, address="planner.local:8080")
        assert device.address == "planner.local:8080"
        found = store.get_device_by_token(device.token)
        assert found is not None
        assert found.address == "planner.local:8080"
        assert [d.address for d in store.get_all_devices()] == ["planner.local:8080"]
        store.close()

    def test_it_is_there_after_the_store_is_opened_again(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        token = store.add_device("Mac", "ua", "quick", 0, address="192.168.1.20:8080").token
        store.close()
        store = self._make_store(tmp_path)
        found = store.get_device_by_token(token)
        assert found is not None
        assert found.address == "192.168.1.20:8080"
        store.close()

    def test_a_device_without_one_has_none(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        assert store.add_device("Mac", "ua", "quick", 0).address == ""
        assert PairedDevice().address == ""
        store.close()

    def test_devices_that_need_the_certificate_again_have_theirs(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        store.add_device("Mac", "ua", "trusted", 0, address="planner.local:8080")
        assert [d.address for d in store.get_stale_devices(1)] == ["planner.local:8080"]
        store.close()

    def test_a_table_of_an_earlier_version_gains_the_column(self, tmp_path: Path):
        """Its devices stay, with no address."""
        import sqlite3

        path = tmp_path / "web_devices.db"
        conn = sqlite3.connect(str(path))
        conn.execute(
            "CREATE TABLE paired_devices ("
            " id TEXT PRIMARY KEY, token TEXT NOT NULL UNIQUE, device_name TEXT NOT NULL,"
            " user_agent TEXT NOT NULL, pairing_method TEXT NOT NULL,"
            " ca_generation INTEGER NOT NULL, paired_at INTEGER NOT NULL,"
            " last_seen INTEGER NOT NULL)"
        )
        conn.execute(
            "INSERT INTO paired_devices VALUES ('id-1', 'token-1', 'Pixel', 'ua', 'quick', 0, 5, 6)"
        )
        conn.commit()
        conn.close()

        store = self._make_store(tmp_path)
        before = store.get_device_by_token("token-1")
        assert before is not None
        assert (before.device_name, before.paired_at, before.last_seen) == ("Pixel", 5, 6)
        assert before.address == ""
        added = store.add_device("Mac", "ua", "quick", 0, address="planner.local:8080")
        assert {d.address for d in store.get_all_devices()} == {"", "planner.local:8080"}
        assert store.get_device_by_token(added.token) is not None
        store.close()
        # And a second opening changes nothing.
        store = self._make_store(tmp_path)
        assert len(store.get_all_devices()) == 2
        store.close()


class TestTokensAreStoredAsHashes:
    """Only a hash of each token is kept: a copy of the file holds
    nothing a device could present (#85)."""

    def _raw(self, tmp_path: Path) -> bytes:
        """Every byte of the database and of the files SQLite keeps
        beside it."""
        found = b""
        for name in ("web_devices.db", "web_devices.db-wal", "web_devices.db-shm"):
            path = tmp_path / name
            if path.exists():
                found += path.read_bytes()
        return found

    def _store(self, tmp_path: Path) -> WebDeviceStore:
        store = WebDeviceStore(tmp_path / "web_devices.db")
        store.open()
        return store

    def _earlier_file(self, tmp_path: Path, tokens: list[str], keep_open: bool = False):
        """A database as an earlier version wrote it: tokens as issued,
        with many rows deleted and one renamed, so that old copies of
        rows lie in free pages. With ``keep_open`` the connection is
        given back open, as the application holds it had it been stopped
        hard: the last writes are still in the log."""
        import sqlite3

        conn = sqlite3.connect(tmp_path / "web_devices.db")
        conn.execute("PRAGMA secure_delete=OFF")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE paired_devices (id TEXT PRIMARY KEY, token TEXT NOT NULL UNIQUE,"
            " device_name TEXT NOT NULL, user_agent TEXT NOT NULL, pairing_method TEXT NOT NULL,"
            " ca_generation INTEGER NOT NULL, paired_at INTEGER NOT NULL,"
            " last_seen INTEGER NOT NULL)"
        )
        # Devices paired and removed: whole pages of them go free.
        for number in range(300):
            conn.execute(
                "INSERT INTO paired_devices VALUES (?, ?, ?, 'ua', 'quick', 0, 1, 4102444800000)",
                (f"gone-{number}", f"GONE-token-{number:04d}-" + "x" * 30, "Gone " + "y" * 60),
            )
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("DELETE FROM paired_devices WHERE id LIKE 'gone-%'")
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for number, token in enumerate(tokens):
            conn.execute(
                "INSERT INTO paired_devices VALUES (?, ?, ?, 'ua', 'quick', 0, ?, ?)",
                (f"device-{number}", token, f"Phone {number}", number, 4102444800000),
            )
        conn.commit()
        conn.execute("UPDATE paired_devices SET device_name = 'Renamed' WHERE id = 'device-0'")
        conn.commit()
        if keep_open:
            return conn
        conn.close()
        return None

    def test_a_new_device_is_stored_by_the_hash_of_its_token(self, tmp_path: Path):
        import hashlib

        store = self._store(tmp_path)
        device = store.add_device("iPhone", "ua", "quick", 0)
        # Given once, to the device.
        assert len(device.token) >= 40
        raw = self._raw(tmp_path)
        assert device.token.encode() not in raw
        assert ("sha256:" + hashlib.sha256(device.token.encode()).hexdigest()).encode() in raw
        assert store.get_device_by_token(device.token) is not None
        store.close()

    def test_a_device_read_back_carries_no_token(self, tmp_path: Path):
        store = self._store(tmp_path)
        added = store.add_device("iPhone", "ua", "quick", 0)
        found = store.get_device_by_token(added.token)
        assert found is not None and found.id == added.id
        assert found.device_name == "iPhone" and found.user_agent == "ua"
        assert found.token == ""
        assert [d.token for d in store.get_all_devices()] == [""]
        assert [d.token for d in store.get_stale_devices(1)] == [""]
        assert store.get_stale_devices(1)[0].device_name == "iPhone"
        store.close()

    def test_the_hash_itself_is_no_token(self, tmp_path: Path):
        """What a copy of the file holds does not let a device in."""
        from pytodo_qt.web.device_store import token_hash

        store = self._store(tmp_path)
        device = store.add_device("iPhone", "ua", "quick", 0)
        assert store.get_device_by_token(token_hash(device.token)) is None
        assert store.get_device_by_token("") is None
        assert store.get_device_by_token(device.token + "x") is None
        store.close()

    def test_tokens_an_earlier_version_stored_go_on_working_and_are_gone_from_the_files(
        self, tmp_path: Path
    ):
        tokens = [f"token-{n}-" + "a" * 36 for n in range(3)]
        self._earlier_file(tmp_path, tokens)
        assert tokens[0].encode() in self._raw(tmp_path)
        assert b"GONE-token" in self._raw(tmp_path)

        store = self._store(tmp_path)
        for number, token in enumerate(tokens):
            found = store.get_device_by_token(token)
            assert found is not None and found.id == f"device-{number}"
        # While the store is open, as the application keeps it: a copy
        # of the files taken now holds none of them, not in a free page
        # and not in a frame of the log.
        raw = self._raw(tmp_path)
        for token in tokens:
            assert token.encode() not in raw
        assert b"GONE-token" not in raw
        assert (tmp_path / "web_devices.db-wal").stat().st_size == 0
        store.close()

    def test_tokens_still_in_the_log_of_an_earlier_version_are_gone_as_well(self, tmp_path: Path):
        """The earlier version was stopped hard: its last writes are in
        the write-ahead log, not yet in the file."""
        tokens = ["token-log-" + "e" * 34]
        earlier = self._earlier_file(tmp_path, tokens, keep_open=True)
        assert earlier is not None
        try:
            assert tokens[0].encode() in (tmp_path / "web_devices.db-wal").read_bytes()
            store = self._store(tmp_path)
            assert store.get_device_by_token(tokens[0]) is not None
            raw = self._raw(tmp_path)
            assert tokens[0].encode() not in raw
            assert b"GONE-token" not in raw
            store.close()
        finally:
            earlier.close()

    def test_a_token_stored_empty_is_not_matched_by_an_empty_one(self, tmp_path: Path):
        """A row an earlier version wrote with an empty token is kept,
        hashed, and lets nothing in."""
        self._earlier_file(tmp_path, [""])
        store = self._store(tmp_path)
        assert store.get_device_by_token("") is None
        assert len(store.get_all_devices()) == 1
        store.close()

    def test_a_converted_file_is_not_converted_again(self, tmp_path: Path):
        from pytodo_qt.web.device_store import token_hash

        token = "token-x-" + "b" * 36
        self._earlier_file(tmp_path, [token])
        self._store(tmp_path).close()
        store = self._store(tmp_path)
        assert store.get_device_by_token(token) is not None
        stored = store._conn.execute("SELECT token FROM paired_devices").fetchall()  # type: ignore[union-attr]
        assert stored == [(token_hash(token),)]
        store.close()

    def test_a_file_with_both_forms_is_brought_to_one(self, tmp_path: Path):
        """Rows an earlier version wrote beside rows this one wrote, as
        after a build of each opened the same file."""
        old = "token-old-" + "c" * 34
        self._earlier_file(tmp_path, [old])
        store = self._store(tmp_path)
        new = store.add_device("New", "ua", "quick", 0)
        store.close()
        import sqlite3

        conn = sqlite3.connect(tmp_path / "web_devices.db")
        later = "token-later-" + "d" * 32
        conn.execute(
            "INSERT INTO paired_devices (id, token, device_name, user_agent, pairing_method,"
            " ca_generation, paired_at, last_seen) VALUES ('later', ?, 'Later', 'ua', 'quick',"
            " 0, 2, 4102444800000)",
            (later,),
        )
        conn.commit()
        conn.close()
        store = self._store(tmp_path)
        for token in (old, new.token, later):
            assert store.get_device_by_token(token) is not None, token
        store.close()
        raw = self._raw(tmp_path)
        assert old.encode() not in raw and later.encode() not in raw

    def test_secure_delete_is_on_for_what_is_deleted_later(self, tmp_path: Path):
        store = self._store(tmp_path)
        assert store._conn.execute("PRAGMA secure_delete").fetchone() == (1,)  # type: ignore[union-attr]
        store.close()

    def test_the_copy_set_aside_as_corrupt_is_removed_once_the_store_is_open(self, tmp_path: Path):
        corrupt = tmp_path / "web_devices.db.corrupt"
        corrupt.write_bytes(b"token-in-a-corrupt-copy")
        store = self._store(tmp_path)
        store.close()
        assert not corrupt.exists()

    def test_a_corrupt_file_is_set_aside_and_then_removed(self, tmp_path: Path):
        (tmp_path / "web_devices.db").write_bytes(b"not a database " * 100)
        store = self._store(tmp_path)
        device = store.add_device("iPhone", "ua", "quick", 0)
        assert store.get_device_by_token(device.token) is not None
        store.close()
        assert not (tmp_path / "web_devices.db.corrupt").exists()
