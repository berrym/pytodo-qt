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

    def test_get_active_tokens(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        d1 = store.add_device("A", "ua1", "quick", 0)
        d2 = store.add_device("B", "ua2", "trusted", 0)
        tokens = store.get_active_tokens()
        assert tokens == {d1.token, d2.token}
        store.close()

    def test_get_active_tokens_empty(self, tmp_path: Path):
        store = self._make_store(tmp_path)
        assert store.get_active_tokens() == set()
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

        # Corrupt file was renamed
        assert (tmp_path / "web_devices.db.corrupt").exists()

        # Fresh store works
        device = store.add_device("Test", "ua", "quick", 0)
        assert store.get_device_by_token(device.token) is not None
        store.close()

    def test_remove_device_token_no_longer_active(self, tmp_path: Path):
        """Removing a device means its token is no longer in active tokens."""
        store = self._make_store(tmp_path)
        device = store.add_device("iPhone", "ua", "quick", 0)
        assert device.token in store.get_active_tokens()

        store.remove_device(device.id)
        assert device.token not in store.get_active_tokens()
        store.close()
