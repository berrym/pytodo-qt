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
    """Dialog showing a QR code for mobile Web UI connection."""

    def __init__(self, port: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connect Mobile Device")
        self.setMinimumWidth(350)

        self._port = port
        self._lan_ip = _get_lan_ip()
        self._url = f"http://{self._lan_ip}:{port}" if self._lan_ip else None

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        if self._url is None:
            # No network detected
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
            # QR code
            qr_label = QLabel()
            qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pixmap = _render_qr_pixmap(self._url, size=250)
            qr_label.setPixmap(pixmap)
            layout.addWidget(qr_label)

            # URL display
            url_label = QLabel(self._url)
            url_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            url_font = QFont()
            url_font.setPointSize(13)
            url_label.setFont(url_font)
            layout.addWidget(url_label)

            # Instructions
            instructions = QLabel("Scan with your phone camera to open the Web UI.")
            instructions.setAlignment(Qt.AlignmentFlag.AlignCenter)
            instructions.setWordWrap(True)
            instructions.setStyleSheet("color: gray;")
            layout.addWidget(instructions)

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
