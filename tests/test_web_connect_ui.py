"""UI-level tests for the Mobile Access Wizard device rows.

Most of the wizard is covered end-to-end by the web API tests and
the device store tests. These tests specifically pin down the
Rename button behavior added for the v0.3.11 polish pass so the
wiring between _DeviceRow and MobileAccessWizard._on_rename_device
doesn't regress.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QPushButton

from pytodo_qt.gui.dialogs.web_connect import _DeviceRow
from pytodo_qt.web.device_store import PairedDevice


@pytest.fixture(scope="session")
def app():
    _app = QApplication.instance()
    if _app is None:
        _app = QApplication([])
    return _app


def _make_device(name: str = "Test Phone") -> PairedDevice:
    import time as _time

    now_ms = int(_time.time() * 1000)
    return PairedDevice(
        id="device-abc",
        token="tok-xyz",
        device_name=name,
        user_agent="TestBrowser/1.0",
        pairing_method="quick",
        ca_generation=0,
        paired_at=now_ms,
        last_seen=now_ms,
    )


def _find_button(row: _DeviceRow, text: str) -> QPushButton | None:
    for child in row.findChildren(QPushButton):
        if child.text() == text:
            return child
    return None


class TestDeviceRowRenameButton:
    """Rename button visibility + click wiring in _DeviceRow."""

    def test_rename_button_present_when_callback_provided(self, app):
        clicked = []

        row = _DeviceRow(
            device=_make_device(),
            is_stale=False,
            on_forget=lambda *_: None,
            on_rename=lambda *_: clicked.append(True),
        )
        btn = _find_button(row, "Rename")
        assert btn is not None, "Rename button should be present when on_rename is provided"
        btn.click()
        assert clicked == [True]

    def test_rename_button_absent_when_callback_omitted(self, app):
        """The reconfigure page creates _DeviceRow without on_rename
        — the button must not appear in that context."""
        row = _DeviceRow(
            device=_make_device(),
            is_stale=True,
            on_forget=lambda *_: None,
            # on_rename intentionally omitted
        )
        assert _find_button(row, "Rename") is None

    def test_rename_button_present_alongside_reconnect_and_forget(self, app):
        """Triple-button row (stale device that can be reconnected):
        Reconnect, Rename, and Forget all coexist."""
        row = _DeviceRow(
            device=_make_device(),
            is_stale=False,
            on_forget=lambda *_: None,
            on_reconnect=lambda *_: None,
            on_rename=lambda *_: None,
        )
        assert _find_button(row, "Reconnect") is not None
        assert _find_button(row, "Rename") is not None
        assert _find_button(row, "Forget") is not None


class TestMobileAccessWizardRenameHandler:
    """The wizard's _on_rename_device method — prompts for a new
    name and calls WebServer.rename_device, then refreshes the
    device list."""

    def test_handler_calls_web_server_rename(self, app, monkeypatch):
        from pytodo_qt.gui.dialogs.web_connect import MobileAccessWizard

        wiz = MobileAccessWizard.__new__(MobileAccessWizard)
        # Stub out Qt state enough to let _on_rename_device run

        class _FakeServer:
            rename_calls: list = []

            def rename_device(self, device_id: str, new_name: str) -> bool:
                type(self).rename_calls.append((device_id, new_name))
                return True

        class _FakeMW:
            _web_server = _FakeServer()

        wiz._main_window = _FakeMW()
        wiz._populate_device_list = lambda: None  # no-op refresh

        import pytodo_qt.gui.dialogs.web_connect as wc_mod

        monkeypatch.setattr(
            wc_mod.QInputDialog,
            "getText",
            staticmethod(lambda *args, **kwargs: ("Bedroom Phone", True)),
        )

        wiz._on_rename_device("device-abc", "Old Name")
        assert _FakeServer.rename_calls == [("device-abc", "Bedroom Phone")]

    def test_handler_skips_on_cancel(self, app, monkeypatch):
        from pytodo_qt.gui.dialogs.web_connect import MobileAccessWizard

        wiz = MobileAccessWizard.__new__(MobileAccessWizard)

        class _FakeServer:
            rename_calls: list = []

            def rename_device(self, device_id: str, new_name: str) -> bool:
                type(self).rename_calls.append((device_id, new_name))
                return True

        class _FakeMW:
            _web_server = _FakeServer()

        wiz._main_window = _FakeMW()
        wiz._populate_device_list = lambda: None

        import pytodo_qt.gui.dialogs.web_connect as wc_mod

        # User cancels the input dialog
        monkeypatch.setattr(
            wc_mod.QInputDialog,
            "getText",
            staticmethod(lambda *args, **kwargs: ("", False)),
        )

        wiz._on_rename_device("device-abc", "Old Name")
        assert _FakeServer.rename_calls == []

    def test_handler_skips_on_empty_or_unchanged_name(self, app, monkeypatch):
        from pytodo_qt.gui.dialogs.web_connect import MobileAccessWizard

        wiz = MobileAccessWizard.__new__(MobileAccessWizard)

        class _FakeServer:
            rename_calls: list = []

            def rename_device(self, device_id: str, new_name: str) -> bool:
                type(self).rename_calls.append((device_id, new_name))
                return True

        class _FakeMW:
            _web_server = _FakeServer()

        wiz._main_window = _FakeMW()
        wiz._populate_device_list = lambda: None

        import pytodo_qt.gui.dialogs.web_connect as wc_mod

        # Whitespace-only result
        monkeypatch.setattr(
            wc_mod.QInputDialog,
            "getText",
            staticmethod(lambda *args, **kwargs: ("   ", True)),
        )
        wiz._on_rename_device("device-abc", "Old Name")
        assert _FakeServer.rename_calls == []

        # Unchanged name (same as current) is also a no-op
        monkeypatch.setattr(
            wc_mod.QInputDialog,
            "getText",
            staticmethod(lambda *args, **kwargs: ("Old Name", True)),
        )
        wiz._on_rename_device("device-abc", "Old Name")
        assert _FakeServer.rename_calls == []
