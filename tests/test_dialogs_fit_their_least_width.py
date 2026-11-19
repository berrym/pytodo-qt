"""A dialog's least width is the width its content needs.

An explicit least width on a dialog is also the most its layout may
ask for: Qt keeps the one that was set and ignores the layout's own.
A page that asks for more is cut off at the right once the dialog is
at that width. The Security tab of Settings asked for 685 px at a
least dialog width of 620, and the Trusted Connect card of Mobile
Access had a subtitle that did not wrap, at a least width of 500.
"""

from __future__ import annotations

from unittest import mock

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QScrollArea, QWidget


def _settle() -> None:
    for _ in range(8):
        QApplication.processEvents()


def _shown_at_least_width(qtbot, dialog: QWidget) -> QWidget:
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.resize(dialog.minimumWidth(), dialog.height())
    _settle()
    return dialog


class TestSettings:
    @pytest.fixture(autouse=True)
    def _nothing_is_saved(self, monkeypatch):
        monkeypatch.setattr("pytodo_qt.core.config.ConfigManager.save", lambda self: None)

    def test_every_tab_fits_the_least_width(self, qtbot):
        from pytodo_qt.gui.dialogs.settings import SettingsDialog

        dialog = _shown_at_least_width(qtbot, SettingsDialog())
        assert dialog.width() == dialog.minimumWidth()
        for index in range(dialog.tabs.count()):
            dialog.tabs.setCurrentIndex(index)
            _settle()
            area = dialog.tabs.currentWidget()
            assert isinstance(area, QScrollArea)
            page = area.widget()
            assert page is not None
            needed = max(page.minimumSizeHint().width(), page.minimumWidth())
            assert needed <= area.viewport().width(), dialog.tabs.tabText(index)


class TestMobileAccess:
    def _wizard(self, qtbot):
        from pytodo_qt.gui.dialogs import web_connect

        def _served(wizard) -> None:
            wizard._url = "https://192.0.2.10:8080"

        with (
            mock.patch.object(web_connect, "_get_lan_ip", return_value="192.0.2.10"),
            mock.patch.object(web_connect.MobileAccessWizard, "_ensure_server_running", _served),
        ):
            wizard = web_connect.MobileAccessWizard(None)
        qtbot.addWidget(wizard)
        return wizard

    def test_the_choose_page_fits_the_least_width(self, qtbot):
        from pytodo_qt.gui.dialogs import web_connect

        wizard = self._wizard(qtbot)
        _shown_at_least_width(qtbot, wizard)
        wizard._go_to_page(wizard.PAGE_CHOOSE)
        _settle()
        page = wizard._stack.currentWidget()
        assert page is not None
        cards = page.findChildren(web_connect._MethodCard)
        assert len(cards) == 2
        assert page.minimumSizeHint().width() <= wizard.width()
        for card in cards:
            assert card.x() + card.width() <= page.width()
            for label in card.findChildren(QLabel):
                if label.text() and not label.wordWrap():
                    assert label.sizeHint().width() <= label.width() + 1, label.text()

    def test_the_card_subtitle_wraps(self, qtbot):
        from pytodo_qt.gui.dialogs.web_connect import _MethodCard

        card = _MethodCard(
            icon_text="x",
            title="Trusted Connect",
            subtitle="One-time setup — seamless after that",
            description="A description.",
            badge_text="Badge",
            badge_color="#1976d2",
        )
        qtbot.addWidget(card)
        subtitles = [
            label
            for label in card.findChildren(QLabel)
            if label.text() == "One-time setup — seamless after that"
        ]
        assert len(subtitles) == 1
        assert subtitles[0].wordWrap()
