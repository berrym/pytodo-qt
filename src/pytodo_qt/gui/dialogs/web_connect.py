"""web_connect.py

QR code connection dialog for mobile Web UI setup.
"""

from __future__ import annotations

import socket

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


def _get_lan_ip() -> str | None:
    """Detect the device's LAN IP via routing table probe."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            addr = s.getsockname()[0]
            if addr and addr != "0.0.0.0":
                return addr
    except OSError:
        pass
    return None


def _render_qr_pixmap(url: str, size: int = 250) -> QPixmap:
    """Generate a QR code as a QPixmap using QPainter (no PIL needed).

    Args:
        url: The URL to encode.
        size: Target pixel size for the QR image.

    Returns:
        A QPixmap containing the rendered QR code.
    """
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

    # Scale to exact target size with smooth interpolation
    if img_size != size:
        pixmap = pixmap.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    return pixmap


class WebConnectDialog(QDialog):
    """Dialog showing a QR code and pairing PIN for mobile Web UI connection."""

    def __init__(
        self,
        port: int,
        auth_token: str = "",
        pairing_pin: str = "",
        tls_enabled: bool = True,
        ca_cert_available: bool = False,
        parent: object = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Connect Mobile Device")
        self.setMinimumWidth(380)

        self._port = port
        self._auth_token = auth_token
        self._pairing_pin = pairing_pin
        self._tls = tls_enabled
        self._ca_cert = ca_cert_available
        self._lan_ip = _get_lan_ip()

        # QR encodes the server address — PIN handles authentication
        if self._lan_ip:
            scheme = "https" if tls_enabled else "http"
            self._url = f"{scheme}://{self._lan_ip}:{port}"
        else:
            self._url = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        if self._url is None:
            error_label = QLabel("Could not detect network address.")
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            error_label.setStyleSheet("color: gray;")
            layout.addWidget(error_label)

            hint = QLabel("Ensure you are connected to a local network.")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setWordWrap(True)
            hint.setStyleSheet("color: gray;")
            layout.addWidget(hint)
        else:
            # Instructions
            scan_label = QLabel("Scan with your phone camera")
            scan_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            scan_label.setStyleSheet("color: gray; font-size: 13px;")
            layout.addWidget(scan_label)

            # QR code (encodes server address — PIN handles auth)
            qr_label = QLabel()
            qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pixmap = _render_qr_pixmap(self._url, size=250)
            qr_label.setPixmap(pixmap)
            layout.addWidget(qr_label)

            # TLS first-time guidance
            if self._tls:
                if self._ca_cert:
                    tls_hint = QLabel(
                        "First time setup: install the security certificate\n"
                        "on your phone to skip browser warnings permanently."
                    )
                    tls_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    tls_hint.setWordWrap(True)
                    tls_hint.setStyleSheet("color: gray; font-size: 11px;")
                    layout.addWidget(tls_hint)

                    ca_scheme = "https" if self._tls else "http"
                    ca_url = f"{ca_scheme}://{self._lan_ip}:{self._port}/ca.pem"
                    ca_qr_label = QLabel()
                    ca_qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    ca_qr_label.setPixmap(_render_qr_pixmap(ca_url, size=120))
                    ca_qr_label.setToolTip("Scan to download CA certificate")

                    install_label = QLabel(
                        "Optional: install the CA certificate\n"
                        "to permanently remove browser warnings.\n"
                        "iOS: Settings \u2192 General \u2192 VPN & Device Mgmt\n"
                        "Android: Settings \u2192 Security \u2192 Install cert"
                    )
                    install_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    install_label.setWordWrap(True)
                    install_label.setStyleSheet("color: gray; font-size: 10px;")

                    cert_row = QHBoxLayout()
                    cert_row.addStretch()
                    cert_row.addWidget(ca_qr_label)
                    cert_col = QVBoxLayout()
                    cert_col.addWidget(install_label)
                    cert_row.addLayout(cert_col)
                    cert_row.addStretch()
                    layout.addLayout(cert_row)

                    skip_label = QLabel(
                        'Or skip this and tap "Advanced" \u2192 "Proceed"\n'
                        "on the browser warning (works but repeats each time)"
                    )
                    skip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    skip_label.setWordWrap(True)
                    skip_label.setStyleSheet("color: gray; font-size: 10px;")
                    layout.addWidget(skip_label)
                else:
                    tls_hint = QLabel(
                        'First time: tap "Advanced" then "Proceed"\n'
                        "to accept the encrypted connection"
                    )
                    tls_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    tls_hint.setWordWrap(True)
                    tls_hint.setStyleSheet("color: gray; font-size: 11px;")
                    layout.addWidget(tls_hint)

            # PIN section (below QR code)
            if self._pairing_pin:
                divider = QLabel("Then enter this PIN")
                divider.setAlignment(Qt.AlignmentFlag.AlignCenter)
                divider.setStyleSheet("color: gray; font-size: 12px; margin-top: 4px;")
                layout.addWidget(divider)

                pin_label = QLabel(self._pairing_pin)
                pin_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                pin_font = QFont("monospace", 32)
                pin_font.setBold(True)
                pin_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 8)
                pin_label.setFont(pin_font)
                pin_label.setStyleSheet("color: palette(highlight); margin: 4px 0;")
                pin_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                layout.addWidget(pin_label)

                pin_hint = QLabel("PIN expires in 5 minutes")
                pin_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
                pin_hint.setStyleSheet("color: gray; font-size: 11px;")
                layout.addWidget(pin_hint)

            # URL display (small, for reference)
            url_label = QLabel(self._url)
            url_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            url_label.setStyleSheet("color: gray; font-size: 12px; margin-top: 8px;")
            layout.addWidget(url_label)

        # Buttons
        btn_layout = QHBoxLayout()

        if self._url is not None:
            copy_btn = QPushButton("Copy URL")
            copy_btn.clicked.connect(self._copy_url)
            btn_layout.addWidget(copy_btn)

        btn_layout.addStretch()

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        btn_layout.addWidget(button_box)

        layout.addLayout(btn_layout)

    def _copy_url(self) -> None:
        """Copy the Web UI URL to the clipboard."""
        if self._url is None:
            return
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self._url)
