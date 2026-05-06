"""Manual visual-verification harness for the in-app notification overlay.

Walks a tester through every notification overlay scenario one at a time.
For each scenario, the harness fires a real ``NotificationOverlay`` /
``NotificationManager`` interaction and waits for a Pass / Fail / Skip
verdict plus an optional note. At the end it prints a summary and
optionally writes a timestamped results file.

This is **not** part of the pytest suite and **not** CI-gated — it
requires a human watching the screen. It exists so visual regressions in
the notification surface (sizing, scrolling, alignment, stacking, hover-
pause, queueing/reflow) can be caught by re-running this one script
whenever the overlay code changes.

Run from the repo root:

    uv run python scripts/verify_notification_overlay.py

Optional:

    uv run python scripts/verify_notification_overlay.py --record path.txt

The harness window positions itself in the lower-left of the primary
screen so it never covers the top-right notification stack. Fire-and-
verdict cycles run sequentially; Skip is recorded but does not block
progression. Closing the harness mid-walkthrough discards results.

Tracking: https://github.com/berrym/pytodo-qt/issues/28 (overlay long-body
fidelity gripe, 2026-05-02 entry).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# Imports from the project under test. Path setup mirrors the wcag_audit
# script — uv run python adds the project root to sys.path automatically.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pytodo_qt.gui.widgets.notification_overlay import NotificationManager  # noqa: E402

SHORT_BODY = "Time for a break!"

MEDIUM_BODY = (
    "Conference call with the engineering team to discuss the next sprint, "
    "the mobile roadmap, and how the new sync protocol changes affect "
    "downstream consumers."
)

CAP_BODY = (
    "Reminder: weekly planning review at 3pm. Bring last week's outcomes, "
    "the carryover list, and any blockers from the design track. Calendar "
    "shows two follow-up slots free this afternoon if discussion runs long. "
    "Notes from the prior meeting are pinned in the shared workspace."
)

PATHOLOGICAL_BODY = (
    "This is a deliberately enormous notification body that exceeds the "
    "overlay's maximum-growth cap so the scroll behavior can be exercised. "
    "The first word of the first line should be visible at the top of the "
    "scroll viewport. The vertical scroll bar should appear on the right. "
    "Dragging the scroll bar or rolling the mouse wheel should reveal the "
    "rest of the body. Nothing should clip at any edge of the overlay. "
    "The text should never look visually compressed or smooshed even when "
    "the overlay is at its maximum height. " * 6
)

NEWLINE_BODY = (
    "Line one of the notification.\n"
    "Line two — explicit newline break.\n"
    "Line three.\n"
    "\n"
    "Line five after a blank line.\n"
    "Line six closes it out."
)


@dataclass
class Verdict:
    name: str
    status: str  # "pass" | "fail" | "skip"
    note: str = ""


@dataclass
class Scenario:
    name: str
    instructions: str
    fire: Callable[[NotificationManager], None]


def _fire_short(mgr: NotificationManager) -> None:
    mgr.show("Focus session complete", SHORT_BODY, timeout_ms=0)


def _fire_medium(mgr: NotificationManager) -> None:
    mgr.show("Standup reminder", MEDIUM_BODY, timeout_ms=0)


def _fire_at_cap(mgr: NotificationManager) -> None:
    mgr.show("Meeting in 10 minutes", CAP_BODY, timeout_ms=0)


def _fire_pathological(mgr: NotificationManager) -> None:
    mgr.show("Long-body stress test", PATHOLOGICAL_BODY, timeout_ms=0)


def _fire_newlines(mgr: NotificationManager) -> None:
    mgr.show("Multi-paragraph body", NEWLINE_BODY, timeout_ms=0)


def _fire_auto_dismiss(mgr: NotificationManager) -> None:
    mgr.show("Auto-dismiss check", "This banner self-dismisses in ~2 seconds.", timeout_ms=2000)


def _fire_hover_pause(mgr: NotificationManager) -> None:
    mgr.show(
        "Hover-pause check",
        "Hover over this banner; the auto-dismiss timer should pause. Move "
        "the cursor away to resume — total timeout is 4 seconds, so a 6-second "
        "hover proves the pause works.",
        timeout_ms=4000,
    )


def _fire_stacking_mixed(mgr: NotificationManager) -> None:
    # Three banners with different heights — verify the stack uses actual
    # heights rather than a uniform assumption.
    mgr.show("Stacking 1 (short)", "Short.", timeout_ms=0)
    mgr.show("Stacking 2 (medium)", MEDIUM_BODY, timeout_ms=0)
    mgr.show("Stacking 3 (pathological)", PATHOLOGICAL_BODY, timeout_ms=0)


def _fire_queue_reflow(mgr: NotificationManager) -> None:
    # Five banners against a max_visible of 3 — the last two queue, then
    # promote as visible ones dismiss. (The harness uses a fresh manager
    # for this scenario; see HarnessWindow._run_current_scenario.)
    for i in range(1, 6):
        mgr.show(f"Queued #{i}", f"Body content for banner {i}.", timeout_ms=0)


SCENARIOS: list[Scenario] = [
    Scenario(
        "Short body (single line)",
        "Banner sits near the minimum height (88 px). No scroll bar. Text is "
        "top-left aligned with extra space below the body line.",
        _fire_short,
    ),
    Scenario(
        "Medium body (~3-5 wrapped lines)",
        "Banner expands to fit the body. No scroll bar. All text visible. "
        "Word wrap at the right edge looks clean — no compression.",
        _fire_medium,
    ),
    Scenario(
        "Body at the growth cap (~8-10 wrapped lines)",
        "Banner sits at or near the maximum height (240 px). No scroll bar "
        "yet — the body still fits. All text visible.",
        _fire_at_cap,
    ),
    Scenario(
        "Pathological body (way past the cap)",
        "Banner is capped at 240 px. Vertical scroll bar appears on the right. "
        "First word of first line is visible at the top. Dragging the scroll "
        "bar or rolling the mouse wheel reveals the rest. Nothing clips at any "
        "edge. Text never looks visually compressed.",
        _fire_pathological,
    ),
    Scenario(
        "Embedded newlines",
        "Banner respects explicit \\n breaks in the body. Line one through "
        "line six render on separate lines, including the blank line.",
        _fire_newlines,
    ),
    Scenario(
        "Auto-dismiss timer",
        "Banner appears, then slides away on its own after roughly 2 seconds. "
        "The slide-out animation is to the right.",
        _fire_auto_dismiss,
    ),
    Scenario(
        "Hover pauses the auto-dismiss timer",
        "Banner appears with a 4-second timeout. Hover the cursor over the "
        "banner for 6+ seconds — it should NOT dismiss while hovered. Move "
        "the cursor away — it should dismiss within 4 seconds after that.",
        _fire_hover_pause,
    ),
    Scenario(
        "Stacking with mixed heights",
        "Three banners stack top-to-bottom in the top-right. Each banner sits "
        "below the actual bottom edge of the one above it (not a uniform-height "
        "stride). The 10 px gap between banners is consistent.",
        _fire_stacking_mixed,
    ),
    Scenario(
        "Queueing & reflow (max_visible = 3)",
        "Five banners are submitted; only three are visible at a time. Dismiss "
        "the visible banners (close glyph or click body); queued banners are "
        "promoted into the freed slots. Remaining banners slide up smoothly to "
        "fill the gap.",
        _fire_queue_reflow,
    ),
]


class HarnessWindow(QMainWindow):
    """Sequential walkthrough UI: fires one scenario at a time, collects a
    Pass/Fail/Skip verdict, advances to the next.
    """

    def __init__(self, record_path: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Notification overlay — visual verification harness")
        self._record_path = record_path
        self._verdicts: list[Verdict] = []
        self._index = 0
        # Each scenario gets its own manager so queueing tests start from
        # a clean slate. The current manager is held here so scenarios can
        # add more notifications mid-flight if needed (none currently do).
        self._manager: NotificationManager = NotificationManager(max_visible=3)

        self._build_ui()
        self._position_lower_left()
        self._render_current()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        self._progress_label = QLabel()
        progress_font = QFont()
        progress_font.setPointSize(progress_font.pointSize() - 1)
        self._progress_label.setFont(progress_font)
        layout.addWidget(self._progress_label)

        self._name_label = QLabel()
        name_font = QFont()
        name_font.setBold(True)
        name_font.setPointSize(name_font.pointSize() + 3)
        self._name_label.setFont(name_font)
        self._name_label.setWordWrap(True)
        layout.addWidget(self._name_label)

        self._instructions_label = QLabel()
        self._instructions_label.setWordWrap(True)
        self._instructions_label.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        layout.addWidget(self._instructions_label, 1)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        notes_label = QLabel("Notes (optional):")
        layout.addWidget(notes_label)
        self._notes_edit = QPlainTextEdit()
        self._notes_edit.setFixedHeight(70)
        layout.addWidget(self._notes_edit)

        button_row = QHBoxLayout()
        self._fire_btn = QPushButton("Fire scenario")
        self._fire_btn.clicked.connect(self._on_fire)
        button_row.addWidget(self._fire_btn)

        self._dismiss_btn = QPushButton("Dismiss all")
        self._dismiss_btn.clicked.connect(self._on_dismiss_all)
        button_row.addWidget(self._dismiss_btn)

        button_row.addStretch(1)

        self._pass_btn = QPushButton("Pass")
        self._pass_btn.clicked.connect(lambda: self._record_and_advance("pass"))
        button_row.addWidget(self._pass_btn)

        self._fail_btn = QPushButton("Fail")
        self._fail_btn.clicked.connect(lambda: self._record_and_advance("fail"))
        button_row.addWidget(self._fail_btn)

        self._skip_btn = QPushButton("Skip")
        self._skip_btn.clicked.connect(lambda: self._record_and_advance("skip"))
        button_row.addWidget(self._skip_btn)

        layout.addLayout(button_row)

        self.resize(540, 380)

    def _position_lower_left(self) -> None:
        """Park the harness in the lower-left of the primary screen so it
        never covers the top-right notification stack."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geom = screen.availableGeometry()
        self.move(geom.left() + 24, geom.bottom() - self.height() - 24)

    # ------------------------------------------------------- Scenario flow

    def _render_current(self) -> None:
        if self._index >= len(SCENARIOS):
            self._finish()
            return
        scenario = SCENARIOS[self._index]
        self._progress_label.setText(f"Scenario {self._index + 1} of {len(SCENARIOS)}")
        self._name_label.setText(scenario.name)
        self._instructions_label.setText(scenario.instructions)
        self._notes_edit.clear()

    def _on_fire(self) -> None:
        # Refresh the manager so each fire-press starts from a clean stack
        # — the user may want to re-trigger the same scenario without the
        # previous run's banners interfering. The previous manager's
        # dismiss_all() releases its banners before being replaced.
        self._manager.dismiss_all()
        self._manager = NotificationManager(max_visible=3)
        scenario = SCENARIOS[self._index]
        # Defer slightly so the click animation on the Fire button isn't
        # mid-render when the banner slides in.
        QTimer.singleShot(50, lambda: scenario.fire(self._manager))

    def _on_dismiss_all(self) -> None:
        self._manager.dismiss_all()

    def _record_and_advance(self, status: str) -> None:
        scenario = SCENARIOS[self._index]
        self._verdicts.append(
            Verdict(
                name=scenario.name,
                status=status,
                note=self._notes_edit.toPlainText().strip(),
            )
        )
        self._manager.dismiss_all()
        self._index += 1
        self._render_current()

    # --------------------------------------------------------- Completion

    def _finish(self) -> None:
        summary = self._format_summary()
        # Print to stdout so the operator has a transcript regardless of
        # whether --record was passed.
        print(summary)
        if self._record_path is not None:
            self._record_path.write_text(summary)
            print(f"\nResults written to: {self._record_path}")
        # Replace the central widget with a final summary view so the
        # tester sees the result before closing the window.
        summary_widget = QPlainTextEdit()
        summary_widget.setReadOnly(True)
        summary_widget.setPlainText(summary)
        self.setCentralWidget(summary_widget)
        self.setWindowTitle("Notification overlay — verification complete")
        self.resize(720, 480)

    def _format_summary(self) -> str:
        timestamp = datetime.now().isoformat(timespec="seconds")
        lines = [
            "Notification overlay verification — " + timestamp,
            "=" * 60,
        ]
        passes = sum(1 for v in self._verdicts if v.status == "pass")
        fails = sum(1 for v in self._verdicts if v.status == "fail")
        skips = sum(1 for v in self._verdicts if v.status == "skip")
        lines.append(
            f"Total: {len(self._verdicts)}    Pass: {passes}    Fail: {fails}    Skip: {skips}"
        )
        lines.append("")
        for v in self._verdicts:
            lines.append(f"[{v.status.upper():4}] {v.name}")
            if v.note:
                for note_line in v.note.splitlines():
                    lines.append(f"        {note_line}")
        lines.append("")
        return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record",
        type=Path,
        default=None,
        help="Write a timestamped results summary to this path on completion.",
    )
    args = parser.parse_args(argv)

    app = QApplication.instance() or QApplication(sys.argv)
    window = HarnessWindow(record_path=args.record)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())


# Belt-and-suspenders against pytest collection. This script imports a
# Qt widget module and runs an event loop in main() — pytest can't safely
# pick anything up here. The literal class name pattern is what pytest
# uses for collection; the underscore prefix on Verdict / Scenario plus
# the absence of test_-prefixed top-level functions keeps it out by
# default, and pyproject's testpaths setting confines collection to
# tests/. This comment exists so a future contributor doesn't refactor
# Verdict/Scenario into Test-prefixed names without also adding a
# conftest exclusion.
__test__ = False
