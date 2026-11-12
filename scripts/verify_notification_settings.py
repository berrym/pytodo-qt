"""Manual visual-verification harness for the Notifications settings tab.

Opens the real Settings dialog on a scratch configuration, so the
regrouped Notifications tab can be checked — and saved from — without
touching the real configuration, database or keyring. The scratch
configuration starts from a ``[notifications]`` section written before
the current keys existed, which shows how such a section is read.

This is **not** part of the pytest suite and **not** CI-gated — it
requires a human watching the screen.

Run from the repo root:

    uv run python scripts/verify_notification_settings.py

Other starting points:

    uv run python scripts/verify_notification_settings.py --seed fresh
    uv run python scripts/verify_notification_settings.py --seed summary-off

The small window beside the dialog shows the section as it was at the
start, what the application read it as, and the section as it is in the
scratch file now; the last one changes on Apply or OK.

What to check on the Notifications tab:

- Four groups: General, Daily summary, Timed reminders, Quiet time.
- With the default seed the summary time reads 06:00 (from
  ``check_hour = 6``) and a hint says it is delivered at 07:00.
- Unticking "Enable task notifications" greys the three groups below it.
- Unticking a group's own checkbox greys only what it governs; "Hold
  the summary while a focus session runs" stays live when quiet hours
  are off.
- Setting quiet hours to start and end at the same time shows a hint.
- The time fields follow Appearance → Time format, live.
- The time fields look like the spin boxes beside them, in the light
  and the dark theme (Appearance → Theme).
- After Apply, the "now" pane holds only the current keys:
  no ``check_hour``, ``notify_overdue``, ``notify_due_today`` or
  ``upcoming_days``.

Tracking: https://github.com/berrym/pytodo-qt/issues/58
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

_SEEDS = {
    "legacy": (
        "[notifications]\n"
        "enabled = true\n"
        "upcoming_days = 5\n"
        "check_hour = 6\n"
        "notify_overdue = false\n"
        "notify_due_today = true\n"
    ),
    "summary-off": (
        "[notifications]\n"
        "enabled = true\n"
        "upcoming_days = 3\n"
        "check_hour = 9\n"
        "notify_overdue = false\n"
        "notify_due_today = false\n"
    ),
    "fresh": "",
}


def _use_scratch_directories() -> Path:
    """Point configuration, data, state and the keyring away from the
    real ones. Must run before anything from the application is imported."""
    root = Path(tempfile.mkdtemp(prefix="pytodo-settings-"))
    os.environ["XDG_CONFIG_HOME"] = str(root / "config")
    os.environ["XDG_DATA_HOME"] = str(root / "data")
    os.environ["XDG_STATE_HOME"] = str(root / "state")
    # The Security tab reads the device identity; keep it out of the
    # system keyring.
    os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    return root


def _notifications_section(config_file: Path) -> str:
    """The ``[notifications]`` section of a config file, as text."""
    if not config_file.exists():
        return "(no configuration file)"
    lines: list[str] = []
    inside = False
    for line in config_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("["):
            inside = line.strip() == "[notifications]"
        if inside and line.strip():
            lines.append(line)
    return "\n".join(lines) or "(no [notifications] section)"


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--seed",
        choices=sorted(_SEEDS),
        default="legacy",
        help="the [notifications] section the scratch configuration starts with",
    )
    args = parser.parse_args()

    scratch_root = _use_scratch_directories()
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import (
        QApplication,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QPlainTextEdit,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    from pytodo_qt.core.config import get_config_manager
    from pytodo_qt.gui.dialogs.settings import SettingsDialog
    from pytodo_qt.gui.styles import apply_current_theme
    from pytodo_qt.gui.styles.themes import apply_font_setting, load_bundled_fonts

    seed = _SEEDS[args.seed]
    manager = get_config_manager()
    if seed:
        manager.config_file.parent.mkdir(parents=True, exist_ok=True)
        manager.config_file.write_text(seed, encoding="utf-8")
    config = manager.load()

    app = QApplication(sys.argv[:1])
    load_bundled_fonts()
    apply_font_setting(app, config.appearance.font)
    apply_current_theme()

    def pane(text: str = "", lines: int = 13) -> QPlainTextEdit:
        box = QPlainTextEdit(text)
        box.setReadOnly(True)
        box.setFixedHeight(box.fontMetrics().lineSpacing() * lines + 40)
        return box

    read_as = "\n".join(config.notifications.to_toml_lines())
    now_pane = pane()

    window = QMainWindow()
    window.setWindowTitle("Notification settings verification")
    central = QWidget()
    layout = QVBoxLayout(central)
    note = QLabel(
        f"Scratch configuration: <b>{manager.config_file}</b><br>"
        "The real configuration, database and keyring are not used."
    )
    note.setWordWrap(True)
    layout.addWidget(note)
    layout.addWidget(QLabel("<b>[notifications] at the start</b>"))
    layout.addWidget(pane(seed.strip() or "(no configuration file: a fresh install)", lines=7))
    read_column = QVBoxLayout()
    read_column.addWidget(QLabel("<b>Read by the application as</b>"))
    read_column.addWidget(pane(read_as))
    now_column = QVBoxLayout()
    now_column.addWidget(QLabel("<b>In the scratch file now</b> (after Apply or OK)"))
    now_column.addWidget(now_pane)
    side_by_side = QHBoxLayout()
    side_by_side.addLayout(read_column)
    side_by_side.addLayout(now_column)
    layout.addLayout(side_by_side)
    open_button = QPushButton("Open Settings")
    layout.addWidget(open_button)
    layout.addStretch(1)
    window.setCentralWidget(central)

    dialogs: list[SettingsDialog] = []

    def open_settings() -> None:
        dialog = SettingsDialog(window)
        for index in range(dialog.tabs.count()):
            if dialog.tabs.tabText(index) == "Notifications":
                dialog.tabs.setCurrentIndex(index)
        dialogs.append(dialog)
        dialog.show()
        dialog.raise_()

    def refresh() -> None:
        text = _notifications_section(manager.config_file)
        if now_pane.toPlainText() != text:
            now_pane.setPlainText(text)

    open_button.clicked.connect(open_settings)
    timer = QTimer(window)
    timer.timeout.connect(refresh)
    timer.start(500)
    refresh()

    window.resize(720, 0)
    window.show()
    screen = app.primaryScreen()
    if screen is not None:
        area = screen.availableGeometry()
        window.move(area.left() + 40, area.top() + 60)
    open_settings()

    print(f"Scratch directory: {scratch_root}")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
