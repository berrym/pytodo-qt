"""web_connect.py

Mobile Access Wizard — guided connection setup for phones and tablets.
Self-contained: starts the web server, generates certificates, and
handles all setup without requiring the user to configure anything first.

Stateful: detects existing paired devices and adapts the UI accordingly.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from ...web.device_store import PairedDevice
    from ..main_window import MainWindow


def _get_lan_ip() -> str | None:
    """Detect the device's LAN IP via routing table probe."""
    from ...core.network import get_lan_ip

    return get_lan_ip()


def _get_local_hostname() -> str | None:
    """Return the mDNS .local hostname, or None."""
    from ...core.network import get_local_hostname

    return get_local_hostname()


def _render_qr_pixmap(url: str, size: int = 250) -> QPixmap:
    """Generate a QR code as a QPixmap using QPainter (no PIL needed)."""
    import qrcode

    qr = qrcode.QRCode(box_size=1, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    matrix = qr.get_matrix()

    modules = len(matrix)
    scale = max(1, size // modules)
    img_size = modules * scale

    pixmap = QPixmap(img_size, img_size)
    pixmap.fill(QColor(255, 255, 255))

    painter = QPainter(pixmap)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0))

    for y, row in enumerate(matrix):
        for x, cell in enumerate(row):
            if cell:
                painter.drawRect(x * scale, y * scale, scale, scale)

    painter.end()

    if img_size != size:
        pixmap = pixmap.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return pixmap


def _shadow(parent: QWidget) -> QGraphicsDropShadowEffect:
    effect = QGraphicsDropShadowEffect(parent)
    effect.setBlurRadius(12)
    effect.setOffset(0, 2)
    effect.setColor(QColor(0, 0, 0, 30))
    return effect


class _StepCircle(QWidget):
    """A numbered circle widget that paints itself reliably."""

    def __init__(self, number: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._number = str(number)
        self.setFixedSize(28, 28)

    def paintEvent(self, a0) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1976D2"))
        painter.drawEllipse(0, 0, self.width(), self.height())

        painter.setPen(QColor(255, 255, 255))
        font = painter.font()
        font.setPixelSize(14)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            0,
            0,
            self.width(),
            self.height(),
            Qt.AlignmentFlag.AlignCenter,
            self._number,
        )
        painter.end()


def _step_circle(number: int) -> _StepCircle:
    return _StepCircle(number)


def _step_row(number: int, title: str, description: str, widget: QWidget | None = None) -> QFrame:
    frame = QFrame()
    frame.setStyleSheet(
        "QFrame { background: palette(base); border: 1px solid palette(mid);"
        " border-radius: 8px; padding: 12px; }"
    )
    row = QHBoxLayout(frame)
    row.setContentsMargins(12, 10, 12, 10)
    row.setSpacing(12)
    row.addWidget(_step_circle(number), 0, Qt.AlignmentFlag.AlignTop)

    content = QVBoxLayout()
    content.setSpacing(4)
    title_lbl = QLabel(title)
    title_lbl.setStyleSheet("font-weight: bold; font-size: 13px; border: none; background: none;")
    content.addWidget(title_lbl)
    if description:
        desc_lbl = QLabel(description)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("font-size: 11px; border: none; background: none;")
        content.addWidget(desc_lbl)
    if widget is not None:
        content.addWidget(widget)
    row.addLayout(content, 1)
    return frame


def _security_badge(text: str, color: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setFixedHeight(22)
    lbl.setStyleSheet(
        f"background: {color}; color: white; font-size: 10px; font-weight: bold;"
        f" border-radius: 11px; padding: 0 10px;"
    )
    return lbl


def _qr_widget(url: str, size: int = 280) -> QLabel:
    lbl = QLabel()
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setPixmap(_render_qr_pixmap(url, size))
    lbl.setStyleSheet(
        "background: white; border: 1px solid #e0e0e0; border-radius: 8px; padding: 8px;"
    )
    lbl.setGraphicsEffect(_shadow(lbl))
    return lbl


def _pin_widget(pin: str) -> QLabel:
    # Use the MONO_FONT_FAMILIES stack via setFamilies() rather than
    # the generic "monospace" constructor argument — the latter
    # triggers a Qt font-alias resolution cost and a console warning
    # on systems where it doesn't resolve to an installed family.
    from ..styles.themes import MONO_FONT_FAMILIES

    lbl = QLabel(pin)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    font = QFont()
    font.setFamilies(MONO_FONT_FAMILIES)
    font.setPointSize(32)
    font.setBold(True)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 8)
    lbl.setFont(font)
    lbl.setStyleSheet("color: palette(highlight); margin: 4px 0; border: none; background: none;")
    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lbl


def _browser_warning_visual(ip: str) -> QFrame:
    """Create a mock browser security warning with step-by-step guidance."""
    _tr = QApplication.translate
    frame = QFrame()
    frame.setStyleSheet(
        "QFrame { background: palette(window); border: 1px solid palette(mid);"
        " border-radius: 6px; padding: 8px; }"
    )
    layout = QVBoxLayout(frame)
    layout.setSpacing(6)
    layout.setContentsMargins(10, 8, 10, 8)

    warning_bar = QLabel(_tr("MobileAccessWizard", "\u26a0 Your connection is not private"))
    warning_bar.setStyleSheet(
        "font-weight: bold; font-size: 12px; color: palette(windowText);"
        " border: none; background: none;"
    )
    layout.addWidget(warning_bar)

    steps = [
        _tr("MobileAccessWizard", '1. Look for "Advanced" or "Show Details" at the bottom'),
        _tr("MobileAccessWizard", f'2. Tap "Proceed to {ip}" or "Visit this website"'),
    ]
    for step in steps:
        step_lbl = QLabel(step)
        step_lbl.setStyleSheet("font-size: 11px; border: none; background: none;")
        layout.addWidget(step_lbl)

    reassurance = QLabel(
        _tr(
            "MobileAccessWizard",
            "This warning appears because the certificate was created by "
            "your own computer, not a commercial authority. "
            "Your connection is fully encrypted.",
        )
    )
    reassurance.setWordWrap(True)
    reassurance.setStyleSheet(
        "font-size: 10px; font-style: italic; border: none; background: none;"
    )
    layout.addWidget(reassurance)

    return frame


def _time_ago(timestamp_ms: int) -> str:
    """Format a millisecond timestamp as a human-readable relative time."""
    _tr = QApplication.translate
    diff = time.time() - timestamp_ms / 1000
    if diff < 60:
        return _tr("MobileAccessWizard", "just now")
    if diff < 3600:
        m = int(diff / 60)
        return _tr("MobileAccessWizard", f"{m} min{'s' if m != 1 else ''} ago")
    if diff < 86400:
        h = int(diff / 3600)
        return _tr("MobileAccessWizard", f"{h} hour{'s' if h != 1 else ''} ago")
    d = int(diff / 86400)
    return _tr("MobileAccessWizard", f"{d} day{'s' if d != 1 else ''} ago")


class _MethodCard(QFrame):
    def __init__(
        self,
        icon_text: str,
        title: str,
        subtitle: str,
        description: str,
        badge_text: str,
        badge_color: str,
        recommended: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setGraphicsEffect(_shadow(self))
        self.setStyleSheet(
            "QFrame { background: palette(base); border: 1px solid palette(mid);"
            " border-radius: 12px; }"
            " QFrame:hover { border-color: palette(highlight); }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        if recommended:
            ribbon = QLabel(self.tr("Recommended"))
            ribbon.setStyleSheet(
                "background: palette(highlight); color: white; font-size: 9px;"
                " font-weight: bold; border-radius: 4px; padding: 2px 8px;"
            )
            ribbon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(ribbon)

        icon_lbl = QLabel(icon_text)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 32px; border: none;")
        layout.addWidget(icon_lbl)

        title_lbl = QLabel(title)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setStyleSheet("font-size: 15px; font-weight: bold; border: none;")
        layout.addWidget(title_lbl)

        sub_lbl = QLabel(subtitle)
        sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_lbl.setStyleSheet("font-size: 11px; border: none;")
        layout.addWidget(sub_lbl)

        desc_lbl = QLabel(description)
        desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("font-size: 12px; border: none;")
        layout.addWidget(desc_lbl)

        badge_row = QHBoxLayout()
        badge_row.addStretch()
        badge_row.addWidget(_security_badge(badge_text, badge_color))
        badge_row.addStretch()
        layout.addLayout(badge_row)

        btn = QPushButton(self.tr("Start \u2192"))
        btn.setStyleSheet(
            "QPushButton { background: palette(highlight); color: white; border: none;"
            " border-radius: 6px; padding: 8px 16px; font-weight: bold; font-size: 13px; }"
        )
        self._start_btn = btn
        layout.addWidget(btn)

    @property
    def start_button(self) -> QPushButton:
        return self._start_btn


class _DeviceRow(QFrame):
    """A single paired device in the device list."""

    def __init__(
        self,
        device: PairedDevice,
        is_stale: bool,
        on_forget: object,
        on_reconnect: object | None = None,
        on_rename: object | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame { background: palette(base); border: 1px solid palette(mid);"
            " border-radius: 8px; padding: 8px; }"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(10)

        # Status dot
        recently_seen = (time.time() - device.last_seen / 1000) < 86400
        dot_color = "#69f0ae" if recently_seen else "#888"
        dot = QLabel("\u2022")
        dot.setFixedWidth(14)
        dot.setStyleSheet(f"font-size: 18px; color: {dot_color}; border: none; background: none;")
        dot.setToolTip(self.tr("Active") if recently_seen else self.tr("Not seen recently"))
        row.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)

        # Device name + details
        info = QVBoxLayout()
        info.setSpacing(2)
        display_name = device.device_name
        if not display_name or display_name == "Unknown device":
            display_name = self.tr("Mobile device")
        name_lbl = QLabel(display_name)
        name_lbl.setStyleSheet(
            "font-weight: bold; font-size: 13px; border: none; background: none;"
        )
        info.addWidget(name_lbl)

        detail_parts = []
        method_label = (
            self.tr("Trusted") if device.pairing_method == "trusted" else self.tr("Quick")
        )
        detail_parts.append(method_label)
        detail_parts.append(self.tr(f"paired {_time_ago(device.paired_at)}"))
        detail_parts.append(self.tr(f"last seen {_time_ago(device.last_seen)}"))
        detail_lbl = QLabel(" \u2022 ".join(detail_parts))
        detail_lbl.setStyleSheet(
            "font-size: 10px; color: palette(placeholderText); border: none; background: none;"
        )
        info.addWidget(detail_lbl)

        if is_stale:
            stale_lbl = QLabel(self.tr("\u26a0 Needs certificate reinstall"))
            stale_lbl.setStyleSheet(
                "font-size: 10px; color: #e67e22; font-weight: bold;"
                " border: none; background: none;"
            )
            info.addWidget(stale_lbl)
        elif not recently_seen:
            hint_lbl = QLabel(self.tr("May need to reconnect"))
            hint_lbl.setStyleSheet(
                "font-size: 10px; color: palette(placeholderText);"
                " font-style: italic; border: none; background: none;"
            )
            info.addWidget(hint_lbl)

        row.addLayout(info, 1)

        # Action buttons
        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)

        if on_reconnect:
            reconnect_btn = QPushButton(self.tr("Reconnect"))
            reconnect_btn.setFixedWidth(72)
            reconnect_btn.setStyleSheet(
                "QPushButton { color: palette(highlight); font-size: 11px;"
                " border: 1px solid palette(highlight);"
                " border-radius: 4px; padding: 4px 8px; background: none; }"
                " QPushButton:hover { background: palette(highlight); color: white; }"
            )
            reconnect_btn.clicked.connect(on_reconnect)
            btn_col.addWidget(reconnect_btn)

        if on_rename:
            rename_btn = QPushButton(self.tr("Rename"))
            rename_btn.setFixedWidth(72)
            rename_btn.setObjectName("rename_btn")
            rename_btn.setStyleSheet(
                "QPushButton { color: palette(text); font-size: 11px;"
                " border: 1px solid palette(mid);"
                " border-radius: 4px; padding: 4px 8px; background: none; }"
                " QPushButton:hover { background: palette(mid); color: palette(text); }"
            )
            rename_btn.clicked.connect(on_rename)
            btn_col.addWidget(rename_btn)

        forget_btn = QPushButton(self.tr("Forget"))
        forget_btn.setFixedWidth(72)
        forget_btn.setStyleSheet(
            "QPushButton { color: #c0392b; font-size: 11px; border: 1px solid #c0392b;"
            " border-radius: 4px; padding: 4px 8px; background: none; }"
            " QPushButton:hover { background: #c0392b; color: white; }"
        )
        forget_btn.clicked.connect(on_forget)
        btn_col.addWidget(forget_btn)

        row.addLayout(btn_col, 0)


class MobileAccessWizard(QDialog):
    """Guided wizard for connecting mobile devices to the web UI.

    Self-contained: starts the web server and generates certificates
    automatically if not already configured.

    Stateful: detects existing paired devices and shows the appropriate
    flow — device list, first-time setup, or reconfiguration guidance.
    """

    PAGE_DEVICE_LIST = 0
    PAGE_CHOOSE = 1
    PAGE_QUICK = 2
    PAGE_TRUSTED = 3
    PAGE_RECONFIGURE = 4
    PAGE_RECONNECT = 5

    def __init__(self, parent: MainWindow | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Mobile Access"))
        self.setAccessibleName(self.tr("Mobile Access"))
        self.setMinimumSize(500, 580)

        self._main_window: MainWindow | None = parent
        self._lan_ip = _get_lan_ip()
        self._local_hostname = _get_local_hostname()
        self._url: str | None = None
        self._url_ip: str | None = None
        self._pairing_pin = ""
        self._remembered = ""
        self._reconnect_device_name = ""

        self._ensure_server_running()
        self._setup_ui()
        self._navigate_to_initial_page()

    def _ensure_server_running(self) -> None:
        """Start the web server and generate certs if needed."""
        mw = self._main_window
        if mw is None:
            return

        if mw._web_server is None:
            mw._config.web.enabled = True
            mw._config.web.tls_enabled = True
            mw._config_manager.save()
            mw._start_web_server()
            QApplication.processEvents()

        if mw._web_server is not None:
            self._pairing_pin = mw._web_server.pairing_pin
            port = mw._config.web.port
            # Prefer .local hostname (IP-change resilient), fall back to IP
            if self._local_hostname:
                self._url = f"https://{self._local_hostname}:{port}"
                if self._lan_ip:
                    self._url_ip = f"https://{self._lan_ip}:{port}"
            elif self._lan_ip:
                self._url = f"https://{self._lan_ip}:{port}"

    def _navigate_to_initial_page(self) -> None:
        """Detect state and show the appropriate page."""
        mw = self._main_window
        if mw is None or mw._web_server is None:
            self._go_to_page(self.PAGE_CHOOSE)
            return

        devices = mw._web_server.get_paired_devices()
        ca_gen = mw._config.web.ca_generation

        if not devices:
            # First-time: check for remembered method
            method = mw._config.web.connect_method
            if method == "quick" and self._url:
                self._go_to_page(self.PAGE_QUICK)
            elif method == "trusted" and self._url:
                self._go_to_page(self.PAGE_TRUSTED)
            else:
                self._go_to_page(self.PAGE_CHOOSE)
        else:
            stale = [d for d in devices if d.ca_generation < ca_gen]
            if stale:
                self._go_to_page(self.PAGE_RECONFIGURE)
            else:
                self._go_to_page(self.PAGE_DEVICE_LIST)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_device_list_page())  # 0
        self._stack.addWidget(self._build_choose_page())  # 1
        self._stack.addWidget(self._build_quick_steps_page())  # 2
        self._stack.addWidget(self._build_trusted_steps_page())  # 3
        self._stack.addWidget(self._build_reconfigure_page())  # 4
        self._stack.addWidget(self._build_reconnect_page())  # 5
        layout.addWidget(self._stack, 1)

        # Bottom bar
        bottom = QFrame()
        bottom.setStyleSheet("QFrame { border-top: 1px solid palette(mid); }")
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(16, 8, 16, 8)

        self._back_btn = QPushButton(self.tr("\u2190 Back"))
        self._back_btn.clicked.connect(self._on_back)
        self._back_btn.setVisible(False)
        bottom_layout.addWidget(self._back_btn)

        self._change_link = QPushButton(self.tr("Change method"))
        self._change_link.setFlat(True)
        self._change_link.setStyleSheet("color: palette(highlight); font-size: 11px;")
        self._change_link.clicked.connect(self._on_change_method)
        self._change_link.setVisible(False)
        bottom_layout.addWidget(self._change_link)

        bottom_layout.addStretch()

        if self._url:
            copy_btn = QPushButton(self.tr("Copy URL"))
            copy_btn.clicked.connect(self._copy_url)
            bottom_layout.addWidget(copy_btn)

        if self._url_ip and self._url_ip != self._url:
            copy_ip_btn = QPushButton(self.tr("Copy IP URL"))
            copy_ip_btn.setToolTip(self._url_ip)
            copy_ip_btn.clicked.connect(self._copy_ip_url)
            bottom_layout.addWidget(copy_ip_btn)

        done_btn = QPushButton(self.tr("Done"))
        done_btn.setDefault(True)
        done_btn.clicked.connect(self._on_done)
        bottom_layout.addWidget(done_btn)

        layout.addWidget(bottom)

    # --- Page builders ---

    def _build_device_list_page(self) -> QWidget:
        page = QWidget()
        self._device_list_scroll = QScrollArea()
        self._device_list_scroll.setWidgetResizable(True)
        self._device_list_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._populate_device_list()

        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(self._device_list_scroll)
        return page

    def _populate_device_list(self) -> None:
        """Build a fresh device list widget and set it on the scroll area."""
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)

        title = QLabel(self.tr("Connected Devices"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 17px; font-weight: 600;")
        layout.addWidget(title)

        subtitle = QLabel(
            self.tr(
                "Devices currently paired to this app."
                " Open the wizard again any time to add more or reconnect."
            )
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 11px; color: palette(placeholderText);")
        layout.addWidget(subtitle)

        mw = self._main_window
        if mw and mw._web_server:
            devices = mw._web_server.get_paired_devices()
            ca_gen = mw._config.web.ca_generation
        else:
            devices = []
            ca_gen = 0

        if not devices:
            empty = QLabel(self.tr("No devices connected yet."))
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(
                "font-size: 13px; color: palette(placeholderText); padding: 20px;"
            )
            layout.addWidget(empty)
        else:
            for device in devices:
                is_stale = device.ca_generation < ca_gen
                display_name = device.device_name
                if not display_name or display_name == "Unknown device":
                    display_name = self.tr("Mobile device")
                row = _DeviceRow(
                    device,
                    is_stale=is_stale,
                    on_forget=lambda _checked=False, d=device: self._on_forget_device(d.id),
                    on_reconnect=lambda _checked=False, n=display_name: self._on_reconnect_device(
                        n
                    ),
                    on_rename=lambda _checked=False, d=device, n=display_name: (
                        self._on_rename_device(d.id, n)
                    ),
                )
                layout.addWidget(row)

        # Add another device button
        add_btn = QPushButton(self.tr("+ Add another device"))
        add_btn.setStyleSheet(
            "QPushButton { background: palette(highlight); color: white; border: none;"
            " border-radius: 6px; padding: 10px 20px; font-weight: bold; font-size: 13px; }"
        )
        add_btn.clicked.connect(lambda: self._go_to_page(self.PAGE_CHOOSE))
        layout.addWidget(add_btn)

        if devices:
            revoke_btn = QPushButton(self.tr("Forget all devices"))
            revoke_btn.setFlat(True)
            revoke_btn.setStyleSheet("color: #c0392b; font-size: 11px; padding: 4px;")
            revoke_btn.clicked.connect(self._on_revoke_all)
            revoke_row = QHBoxLayout()
            revoke_row.addStretch()
            revoke_row.addWidget(revoke_btn)
            revoke_row.addStretch()
            layout.addLayout(revoke_row)

        layout.addStretch()
        self._device_list_scroll.setWidget(content)

    def _build_choose_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(12)

        if self._url is None:
            error = QLabel(
                self.tr(
                    "Could not detect network address.\nEnsure you are connected to a local network."
                )
            )
            error.setAlignment(Qt.AlignmentFlag.AlignCenter)
            error.setWordWrap(True)
            error.setStyleSheet("font-size: 14px;")
            layout.addWidget(error)
            layout.addStretch()
            return page

        title = QLabel(self.tr("Connect a Mobile Device"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel(self.tr("Choose how to connect your phone, tablet, or other device"))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 12px;")
        layout.addWidget(subtitle)

        layout.addSpacing(8)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)

        quick_card = _MethodCard(
            icon_text="\u26a1",
            title=self.tr("Quick Connect"),
            subtitle=self.tr("Fastest setup \u2014 scan and go"),
            description=self.tr(
                "Your browser will show a one-time security warning."
                " All traffic is still fully encrypted."
            ),
            badge_text=self.tr("\U0001f512 Encrypted"),
            badge_color="#4CAF50",
        )
        quick_card.start_button.clicked.connect(lambda: self._go_to_page(self.PAGE_QUICK))
        cards_row.addWidget(quick_card)

        trusted_card = _MethodCard(
            icon_text="\U0001f6e1",
            title=self.tr("Trusted Connect"),
            subtitle=self.tr("One-time setup \u2014 seamless after that"),
            description=self.tr(
                "Install a security certificate on your device."
                " No browser warnings until your network address"
                " or certificate changes."
            ),
            badge_text=self.tr("\U0001f512 Encrypted + Trusted"),
            badge_color="#1976D2",
            recommended=True,
        )
        trusted_card.start_button.clicked.connect(lambda: self._go_to_page(self.PAGE_TRUSTED))
        cards_row.addWidget(trusted_card)

        layout.addLayout(cards_row)
        layout.addSpacing(4)

        self._remember_check = QCheckBox(self.tr("Remember my choice"))
        mw = self._main_window
        if mw:
            self._remember_check.setChecked(bool(mw._config.web.connect_method))
        self._remember_check.setStyleSheet("font-size: 11px;")
        remember_row = QHBoxLayout()
        remember_row.addStretch()
        remember_row.addWidget(self._remember_check)
        remember_row.addStretch()
        layout.addLayout(remember_row)

        layout.addStretch()
        return page

    def _build_quick_steps_page(self) -> QWidget:
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)

        header = QLabel(self.tr("Quick Connect"))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(header)

        if self._url and self._lan_ip:
            # Step 1: Scan QR (with IP fallback toggle)
            qr_container = QWidget()
            qr_layout = QVBoxLayout(qr_container)
            qr_layout.setContentsMargins(0, 0, 0, 0)

            qr = _qr_widget(self._url, 260)
            qr_layout.addWidget(qr)

            url_lbl = QLabel(self._url)
            url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            url_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            url_lbl.setStyleSheet("font-size: 11px; border: none; background: none;")
            qr_layout.addWidget(url_lbl)

            if self._url_ip and self._url_ip != self._url:
                ip_toggle = QPushButton(self.tr("QR not working? Use IP address instead"))
                ip_toggle.setStyleSheet(
                    "font-size: 10px; color: palette(highlight); "
                    "border: none; background: none; text-decoration: underline;"
                )
                ip_toggle.setCursor(Qt.CursorShape.PointingHandCursor)

                def _swap_qr(btn=ip_toggle, lbl=url_lbl, container=qr_layout) -> None:
                    """Toggle between hostname and IP QR codes."""
                    assert self._url_ip is not None
                    using_ip = lbl.text() == self._url_ip
                    target = self._url if using_ip else self._url_ip
                    assert target is not None
                    lbl.setText(target)
                    new_qr = _qr_widget(target, 260)
                    old_item = container.itemAt(0)
                    old_qr = old_item.widget() if old_item is not None else None
                    if old_qr:
                        container.replaceWidget(old_qr, new_qr)
                        old_qr.deleteLater()
                    btn.setText(
                        self.tr("Switch back to .local hostname")
                        if not using_ip
                        else self.tr("QR not working? Use IP address instead")
                    )

                ip_toggle.clicked.connect(_swap_qr)
                qr_layout.addWidget(ip_toggle)

            layout.addWidget(
                _step_row(1, self.tr("Scan this QR code with your device camera"), "", qr_container)
            )

            # Step 2: Accept warning
            warning_visual = _browser_warning_visual(self._lan_ip)
            layout.addWidget(
                _step_row(
                    2,
                    self.tr("Accept the security warning"),
                    self.tr(
                        "Your browser will show a certificate warning."
                        " If you previously used Trusted Connect, you may"
                        " need to clear this site's data in your browser"
                        " settings first."
                    ),
                    warning_visual,
                )
            )

            # Step 3: Enter PIN
            if self._pairing_pin:
                layout.addWidget(self._build_pin_step(3))

            # Step 4: Install to home screen
            layout.addWidget(self._build_install_step(4))

        layout.addStretch()
        scroll.setWidget(content)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(scroll)
        return page

    def _build_trusted_steps_page(self) -> QWidget:
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)

        header = QLabel(self.tr("Trusted Connect"))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(header)

        if self._url and self._lan_ip:
            mw = self._main_window
            port = mw._config.web.port if mw else 8080
            ca_url = f"https://{self._lan_ip}:{port}/ca.pem"

            # Step 1: Install certificate
            ca_qr = _qr_widget(ca_url, 200)

            tabs = QTabWidget()
            tabs.setStyleSheet(
                "QTabWidget { border: none; background: none; } QTabBar { font-size: 11px; }"
            )

            ios_widget = QWidget()
            ios_layout = QVBoxLayout(ios_widget)
            ios_layout.setContentsMargins(8, 8, 8, 8)
            ios_layout.setSpacing(4)
            for i, text in enumerate(
                [
                    "Scan the QR code \u2014 tap Allow when prompted",
                    "Open Settings \u2192 General \u2192 VPN & Device Management",
                    "Tap the PyTodo-Qt profile \u2192 Install \u2192 Enter passcode",
                    "Settings \u2192 General \u2192 About \u2192"
                    " Certificate Trust Settings \u2192 Enable",
                ],
                1,
            ):
                lbl = QLabel(f"{i}. {text}")
                lbl.setWordWrap(True)
                lbl.setStyleSheet("font-size: 11px; padding: 4px 0;")
                ios_layout.addWidget(lbl)
            ios_layout.addStretch()
            tabs.addTab(ios_widget, self.tr("iOS / iPadOS"))

            android_widget = QWidget()
            android_layout = QVBoxLayout(android_widget)
            android_layout.setContentsMargins(8, 8, 8, 8)
            android_layout.setSpacing(4)
            for i, text in enumerate(
                [
                    "Scan the QR code to download the certificate",
                    'Open Settings \u2192 search for "certificate"',
                    "Choose CA certificate \u2192 select the downloaded file \u2192 Install",
                ],
                1,
            ):
                lbl = QLabel(f"{i}. {text}")
                lbl.setWordWrap(True)
                lbl.setStyleSheet("font-size: 11px; padding: 4px 0;")
                android_layout.addWidget(lbl)

            android_caveat = QLabel(
                self.tr(
                    "Steps vary by manufacturer and Android version."
                    ' If these don\'t match, search Settings for "certificate".'
                )
            )
            android_caveat.setWordWrap(True)
            android_caveat.setStyleSheet("font-size: 10px; font-style: italic; padding: 4px 0;")
            android_layout.addWidget(android_caveat)
            android_layout.addStretch()
            tabs.addTab(android_widget, self.tr("Android"))

            cert_container = QWidget()
            cert_layout = QVBoxLayout(cert_container)
            cert_layout.setContentsMargins(0, 0, 0, 0)
            cert_layout.addWidget(ca_qr)
            cert_layout.addWidget(tabs)

            layout.addWidget(
                _step_row(
                    1,
                    self.tr("Install the security certificate"),
                    self.tr(
                        "One-time setup per device. Allows encrypted connections"
                        " without browser warnings."
                    ),
                    cert_container,
                )
            )

            # Step 2: Open the app
            app_qr = _qr_widget(self._url, 200)
            layout.addWidget(
                _step_row(
                    2,
                    self.tr("Open the app \u2014 no warning this time"),
                    self.tr("Scan this QR code to open the web app."),
                    app_qr,
                )
            )

            # Step 3: Enter PIN
            if self._pairing_pin:
                layout.addWidget(self._build_pin_step(3))

            # Step 4: Install to home screen
            layout.addWidget(self._build_install_step(4))

            # Regenerate certificate option
            regen_btn = QPushButton(self.tr("Regenerate certificate"))
            regen_btn.setFlat(True)
            regen_btn.setStyleSheet("color: palette(highlight); font-size: 11px;")
            regen_btn.clicked.connect(self._on_regenerate_certs)
            regen_row = QHBoxLayout()
            regen_row.addStretch()
            regen_row.addWidget(regen_btn)
            regen_row.addStretch()
            layout.addLayout(regen_row)

        layout.addStretch()
        scroll.setWidget(content)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(scroll)
        return page

    def _build_reconfigure_page(self) -> QWidget:
        """Page shown when CA was regenerated and devices need cert reinstall."""
        page = QWidget()
        self._reconfigure_scroll = QScrollArea()
        self._reconfigure_scroll.setWidgetResizable(True)
        self._reconfigure_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._populate_reconfigure()

        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(self._reconfigure_scroll)
        return page

    def _populate_reconfigure(self) -> None:
        """Build a fresh reconfigure widget and set it on the scroll area."""
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)

        title = QLabel(self.tr("\u26a0 Certificate Changed"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #e67e22;")
        layout.addWidget(title)

        explanation = QLabel(
            self.tr(
                "The security certificate was regenerated. Devices that used"
                " Trusted Connect need to install the new certificate to"
                " reconnect without browser warnings.\n\n"
                "Quick Connect devices can reconnect by accepting the new"
                " browser warning \u2014 no action needed."
            )
        )
        explanation.setWordWrap(True)
        explanation.setAlignment(Qt.AlignmentFlag.AlignCenter)
        explanation.setStyleSheet("font-size: 12px; padding: 0 12px;")
        layout.addWidget(explanation)

        mw = self._main_window
        if mw and mw._web_server:
            ca_gen = mw._config.web.ca_generation
            devices = mw._web_server.get_paired_devices()
            stale = [d for d in devices if d.ca_generation < ca_gen]

            if stale:
                n = len(stale)
                affected_label = QLabel(
                    f"{n} device{'s' if n != 1 else ''} need{'s' if n == 1 else ''} updating:"
                )
                affected_label.setStyleSheet("font-weight: bold; font-size: 13px;")
                layout.addWidget(affected_label)

                for device in stale:
                    row = _DeviceRow(
                        device,
                        is_stale=True,
                        on_forget=lambda _checked=False, d=device: self._on_forget_device(
                            d.id, refresh_reconfigure=True
                        ),
                    )
                    layout.addWidget(row)

            # Action buttons
            reinstall_btn = QPushButton(self.tr("Show certificate install steps"))
            reinstall_btn.setStyleSheet(
                "QPushButton { background: #1976D2; color: white; border: none;"
                " border-radius: 6px; padding: 10px 20px; font-weight: bold; }"
            )
            reinstall_btn.clicked.connect(lambda: self._go_to_page(self.PAGE_TRUSTED))
            layout.addWidget(reinstall_btn)

        layout.addStretch()
        self._reconfigure_scroll.setWidget(content)

    def _build_reconnect_page(self) -> QWidget:
        """Page showing a QR code for reconnecting an existing device."""
        page = QWidget()
        self._reconnect_scroll = QScrollArea()
        self._reconnect_scroll.setWidgetResizable(True)
        self._reconnect_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._populate_reconnect()

        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(self._reconnect_scroll)
        return page

    def _populate_reconnect(self) -> None:
        """Build the reconnect page content."""
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        title = QLabel(self.tr(f"Reconnect {self._reconnect_device_name}"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 17px; font-weight: 600;")
        title.setWordWrap(True)
        layout.addWidget(title)

        instruction = QLabel(
            self.tr("Scan this QR code on the device to reconnect.\nNo re-pairing needed.")
        )
        instruction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        instruction.setWordWrap(True)
        instruction.setStyleSheet(
            "font-size: 12px; color: palette(placeholderText); padding: 0 12px;"
        )
        layout.addWidget(instruction)

        if self._url:
            qr = _qr_widget(self._url, 280)
            layout.addWidget(qr)

            url_lbl = QLabel(self._url)
            url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            url_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            url_lbl.setStyleSheet("font-size: 11px;")
            layout.addWidget(url_lbl)

            # Show IP fallback if using .local
            if self._url_ip and self._url_ip != self._url:
                fallback_lbl = QLabel(self.tr(f"IP address: {self._url_ip}"))
                fallback_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                fallback_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                fallback_lbl.setStyleSheet("font-size: 10px; color: palette(placeholderText);")
                layout.addWidget(fallback_lbl)

        layout.addStretch()
        self._reconnect_scroll.setWidget(content)

    def _build_pin_step(self, step_number: int) -> QFrame:
        """Build the reusable PIN entry step."""
        pin_container = QWidget()
        pin_layout = QVBoxLayout(pin_container)
        pin_layout.setContentsMargins(0, 0, 0, 0)
        pin_layout.addWidget(_pin_widget(self._pairing_pin))
        pin_hint = QLabel(self.tr("PIN expires in 5 minutes \u2022 Auto-submits at 6 digits"))
        pin_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pin_hint.setStyleSheet("font-size: 10px; border: none; background: none;")
        pin_layout.addWidget(pin_hint)
        return _step_row(
            step_number, self.tr("Enter this PIN on the login page"), "", pin_container
        )

    def _build_install_step(self, step_number: int) -> QFrame:
        """Build the reusable PWA install step."""
        install_info = QLabel(
            self.tr(
                "iOS: Tap Share \u2192 Add to Home Screen\n"
                "Android: Tap browser menu (\u22ee) \u2192 Install app"
            )
        )
        install_info.setStyleSheet("font-size: 11px; border: none; background: none;")
        return _step_row(
            step_number,
            self.tr("Add to Home Screen (optional)"),
            self.tr("For quick access without scanning the QR code again."),
            install_info,
        )

    # --- Navigation ---

    def _go_to_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)

        is_steps = index in (self.PAGE_QUICK, self.PAGE_TRUSTED)
        is_reconfigure = index == self.PAGE_RECONFIGURE
        is_device_list = index == self.PAGE_DEVICE_LIST
        is_reconnect = index == self.PAGE_RECONNECT

        mw = self._main_window
        has_remembered = bool(mw and mw._config.web.connect_method) if mw else False

        # Back button: shown on step pages, reconfigure, and reconnect
        self._back_btn.setVisible(
            (is_steps and not has_remembered) or is_reconfigure or is_reconnect
        )
        # Change method link: shown when user has a remembered method
        self._change_link.setVisible(is_steps and has_remembered)

        if index == self.PAGE_QUICK:
            self._remembered = "quick"
        elif index == self.PAGE_TRUSTED:
            self._remembered = "trusted"
        else:
            self._remembered = ""

        # Refresh dynamic pages when navigating to them
        if is_device_list:
            self._populate_device_list()
        elif is_reconfigure:
            self._populate_reconfigure()
        elif is_reconnect:
            self._populate_reconnect()

    def _on_back(self) -> None:
        """Navigate back — to device list if devices exist, else choose."""
        mw = self._main_window
        has_devices = bool(mw and mw._web_server and mw._web_server.get_paired_devices())
        if has_devices:
            self._go_to_page(self.PAGE_DEVICE_LIST)
        else:
            self._go_to_page(self.PAGE_CHOOSE)

    def _on_change_method(self) -> None:
        if self._main_window:
            self._main_window._config.web.connect_method = ""
            self._main_window._config_manager.save()
        self._go_to_page(self.PAGE_CHOOSE)

    # --- Actions ---

    def _on_reconnect_device(self, device_name: str) -> None:
        """Show reconnect QR code for an existing device."""
        self._reconnect_device_name = device_name
        self._go_to_page(self.PAGE_RECONNECT)

    def _on_rename_device(self, device_id: str, current_name: str) -> None:
        """Prompt for a new device name and call through to the web
        server's rename_device passthrough, then refresh the list.

        Empty or whitespace-only names are rejected (the user can
        cancel the dialog instead). The rename is local-only — the
        device itself keeps using its existing token, only the
        human-visible label changes.
        """
        mw = self._main_window
        if not (mw and mw._web_server):
            return
        new_name, ok = QInputDialog.getText(
            self,
            self.tr("Rename Device"),
            self.tr("New name:"),
            text=current_name,
        )
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == current_name:
            return
        mw._web_server.rename_device(device_id, new_name)
        self._populate_device_list()

    def _on_forget_device(self, device_id: str, *, refresh_reconfigure: bool = False) -> None:
        mw = self._main_window
        if mw and mw._web_server:
            mw._web_server.remove_device(device_id)

        if refresh_reconfigure:
            self._populate_reconfigure()
            # If no more stale devices, go to device list
            if mw and mw._web_server:
                ca_gen = mw._config.web.ca_generation
                stale = mw._web_server.device_store
                if stale and not stale.get_stale_devices(ca_gen):
                    self._go_to_page(self.PAGE_DEVICE_LIST)
        else:
            self._populate_device_list()
            # If no devices left, go to choose page
            if mw and mw._web_server and not mw._web_server.get_paired_devices():
                self._go_to_page(self.PAGE_CHOOSE)

    def _on_revoke_all(self) -> None:
        mw = self._main_window
        if not mw or not mw._web_server:
            return
        if (
            QMessageBox.question(
                self,
                self.tr("Forget All Devices"),
                self.tr(
                    "This will disconnect all phones and tablets.\n"
                    "They will need to re-pair using a new PIN.\n\nContinue?"
                ),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        mw._web_server.revoke_all_devices()
        self._go_to_page(self.PAGE_CHOOSE)

    def _on_done(self) -> None:
        mw = self._main_window
        if mw and hasattr(self, "_remember_check") and self._remember_check.isChecked():
            if self._remembered and self._remembered != mw._config.web.connect_method:
                mw._config.web.connect_method = self._remembered
                mw._config_manager.save()
        elif (
            mw
            and hasattr(self, "_remember_check")
            and not self._remember_check.isChecked()
            and mw._config.web.connect_method
        ):
            mw._config.web.connect_method = ""
            mw._config_manager.save()
        self.accept()

    def _on_regenerate_certs(self) -> None:
        mw = self._main_window
        if mw and mw._web_server:
            mw._web_server.regenerate_certs()
            QMessageBox.information(
                self,
                self.tr("Certificate Regenerated"),
                self.tr(
                    "A new certificate has been generated.\n"
                    "Devices using Trusted Connect will need to\n"
                    "install the new certificate to reconnect\n"
                    "without browser warnings.\n\n"
                    "Quick Connect devices just need to accept\n"
                    "the new browser warning."
                ),
            )
            # Check if any devices are now stale
            if mw._web_server.get_paired_devices():
                self._go_to_page(self.PAGE_RECONFIGURE)

    def _copy_url(self) -> None:
        if self._url is None:
            return
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self._url)

    def _copy_ip_url(self) -> None:
        if self._url_ip is None:
            return
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self._url_ip)
