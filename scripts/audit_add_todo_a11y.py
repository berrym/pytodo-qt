"""Accessibility audit for the AddTodo dialog.

Programmatic half of issue #22. Instantiates the AddTodo dialog
offscreen, expands the Advanced section so every control is realized,
walks every focusable widget, and reports the labeling / focus / tab-
order / mnemonic gaps that need fixing before screen-reader passes
(VoiceOver / Orca / NVDA) on each platform are meaningful.

Each gap class in the report maps cleanly to a follow-up GitHub issue
under the b8 milestone — fixes ride on those issues, not on #22 itself
(which stays open as the audit umbrella per the issue's stated
deliverable). The screen-reader walkthrough half is an owner-only
manual task and is not driven by this script.

Run from the repo root:

    uv run python scripts/audit_add_todo_a11y.py
    uv run python scripts/audit_add_todo_a11y.py --output docs/a11y-add-todo.txt

Exits 1 if any gap is flagged so CI / pre-commit invocations can detect
new regressions; exits 0 when the audit finds nothing to fix.

Tracking: https://github.com/berrym/pytodo-qt/issues/22
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Force the offscreen Qt platform before importing PyQt — the audit
# never paints anything but constructing widgets requires a running
# QApplication, and offscreen avoids opening a real window on the
# operator's display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QToolButton,
    QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pytodo_qt.gui.dialogs.add_todo import AddTodoDialog  # noqa: E402

# ---------------------------------------------------------------------- types


@dataclass
class Gap:
    category: str
    detail: str
    widget_id: str


@dataclass
class Report:
    gaps: list[Gap] = field(default_factory=list)
    focusable_count: int = 0
    tab_chain: list[str] = field(default_factory=list)

    def add(self, category: str, detail: str, widget: QWidget) -> None:
        self.gaps.append(Gap(category, detail, _widget_id(widget)))


def _widget_id(w: QWidget) -> str:
    """Stable, human-meaningful identifier for a widget — class + the
    most-disambiguating attribute available."""
    cls = w.__class__.__name__
    name = w.objectName()
    if name:
        return f"{cls}#{name}"
    text = ""
    for attr in ("text", "currentText", "placeholderText", "title"):
        if hasattr(w, attr):
            try:
                got = getattr(w, attr)()
                if got:
                    text = str(got)
                    break
            except Exception:
                pass
    if text:
        return f"{cls}({text!r})"
    return f"{cls}@0x{id(w):x}"


# ----------------------------------------------------------------- collectors


def _is_qt_internal(w: QWidget) -> bool:
    """Filter out widgets the user never interacts with directly even
    though they show up under findChildren — popup item views owned by
    QComboBox, the embedded QLineEdit inside a QSpinBox / QDateEdit, etc.
    Their accessibility is the responsibility of their compound parent."""
    name = w.objectName()
    if name.startswith("qt_"):
        return True
    if isinstance(w, QAbstractItemView):
        # Combo dropdown / completer popups — only relevant while open.
        return True
    parent = w.parentWidget()
    while parent is not None:
        if isinstance(parent, (QComboBox, QSpinBox, QDateTimeEdit)):
            return True
        parent = parent.parentWidget()
    return False


def _is_focusable(w: QWidget) -> bool:
    if _is_qt_internal(w):
        return False
    return w.focusPolicy() != Qt.FocusPolicy.NoFocus and w.isVisibleTo(w.window())


def _has_explicit_accessible_name(w: QWidget) -> bool:
    return bool(w.accessibleName())


def _has_explicit_accessible_description(w: QWidget) -> bool:
    return bool(w.accessibleDescription())


def _has_text_label(w: QWidget) -> bool:
    """Widgets that carry their own visible label text in `text()` /
    `title()` get a free accessibleName via Qt's accessibility bridge —
    QPushButton, QCheckBox, QRadioButton, QToolButton, QGroupBox.
    """
    for attr in ("text", "title"):
        if hasattr(w, attr):
            try:
                if getattr(w, attr)():
                    return True
            except Exception:
                pass
    return False


def _find_buddy_label(w: QWidget, all_labels: list[QLabel]) -> QLabel | None:
    for lbl in all_labels:
        if lbl.buddy() is w:
            return lbl
    return None


def _form_row_label(w: QWidget) -> str | None:
    """If the widget lives directly inside a QFormLayout row, return the
    row label's text (with any `&` mnemonic stripped). Returns None when
    the widget is in a nested layout or sits outside any form."""
    parent = w.parentWidget()
    while parent is not None:
        layout = parent.layout()
        if isinstance(layout, QFormLayout):
            for row in range(layout.rowCount()):
                field_item = layout.itemAt(row, QFormLayout.ItemRole.FieldRole)
                if field_item is None:
                    continue
                field_widget = field_item.widget()
                if field_widget is w:
                    label_item = layout.itemAt(row, QFormLayout.ItemRole.LabelRole)
                    if label_item is not None:
                        label_widget = label_item.widget()
                        if isinstance(label_widget, QLabel):
                            return label_widget.text().replace("&", "")
            return None
        parent = parent.parentWidget()
    return None


def _siblings_in_row(w: QWidget) -> list[QWidget]:
    """Return focusable siblings inside the same QHBoxLayout — used to
    detect paired-control rows where a single QFormLayout label cannot
    disambiguate which widget is which (checkbox + edit, spinbox + unit
    combo, etc.)."""
    parent = w.parentWidget()
    if parent is None:
        return []
    layout = parent.layout()
    if layout is None:
        return []
    siblings: list[QWidget] = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        widget = item.widget() if item is not None else None
        if widget is not None and widget is not w and _is_focusable(widget):
            siblings.append(widget)
    return siblings


def _walk_focusable(root: QWidget) -> list[QWidget]:
    out: list[QWidget] = []
    for w in root.findChildren(QWidget):
        if _is_focusable(w):
            out.append(w)
    return out


def _walk_tab_chain(root: QWidget, limit: int = 200) -> list[QWidget]:
    """Walk Qt's focus chain starting from root.focusWidget() (or the
    first child if none) and collect focusable widgets in tab order."""
    seen: list[QWidget] = []
    seen_ids: set[int] = set()
    current = root.focusWidget()
    if current is None:
        focusable = _walk_focusable(root)
        if not focusable:
            return seen
        current = focusable[0]
    while current is not None and len(seen) < limit:
        if id(current) in seen_ids:
            break
        if _is_focusable(current):
            seen.append(current)
            seen_ids.add(id(current))
        current = current.nextInFocusChain()
        if current is root:
            break
    return seen


# ------------------------------------------------------------------- audits


def audit(dialog: AddTodoDialog) -> Report:
    report = Report()
    all_labels = dialog.findChildren(QLabel)
    all_groupboxes = dialog.findChildren(QGroupBox)
    focusable = _walk_focusable(dialog)
    report.focusable_count = len(focusable)

    # ---- Tab chain
    chain = _walk_tab_chain(dialog)
    report.tab_chain = [_widget_id(w) for w in chain]
    chain_ids = {id(w) for w in chain}
    for w in focusable:
        if id(w) not in chain_ids:
            report.add(
                "tab-order",
                "focusable widget is not reachable through the dialog's tab chain",
                w,
            )

    # ---- Group box mnemonics
    for gb in all_groupboxes:
        title = gb.title()
        if not title:
            report.add("groupbox-title", "QGroupBox has no title", gb)
            continue
        if "&" not in title:
            report.add(
                "groupbox-mnemonic",
                f"group title {title!r} has no Alt+letter mnemonic (use & prefix)",
                gb,
            )

    # ---- Form-row label mnemonics
    for lbl in all_labels:
        # Skip labels that are not buddies of an interactive widget
        # (decorative labels like the "Every" / "times" inline text).
        buddy = lbl.buddy()
        if buddy is None:
            continue
        if "&" not in lbl.text():
            report.add(
                "form-label-mnemonic",
                f"form-row label {lbl.text()!r} has no Alt+letter mnemonic",
                lbl,
            )

    # ---- Per-widget labeling
    for w in focusable:
        cls = w.__class__.__name__

        # Skip widgets that carry their own visible text — Qt's
        # accessibility bridge announces text() / title() as the name
        # automatically. (The mnemonic check above handles the
        # group-box / form-label cases independently.)
        text_labeled = isinstance(w, (QPushButton, QCheckBox, QRadioButton, QGroupBox))
        if text_labeled:
            continue

        # Quick-action QToolButtons carry a "Priority ▾" / "Date ▾"
        # text() that includes the U+25BE BLACK DOWN-POINTING SMALL
        # TRIANGLE glyph. Screen readers announce that codepoint
        # literally — needs an explicit accessibleName scrubbed of
        # the decoration.
        if isinstance(w, QToolButton):
            text = w.text()
            decorated = "▾" in text or "▼" in text or "▶" in text
            if decorated and not _has_explicit_accessible_name(w):
                report.add(
                    "decorative-glyph-in-name",
                    f"QToolButton text {text!r} contains a decorative arrow "
                    f"glyph; set an explicit accessibleName without it",
                    w,
                )
            continue

        # All other focusable widgets need explicit accessibleName
        # OR a buddy QLabel mapped via setBuddy. QFormLayout creates
        # the QLabel but does NOT call setBuddy, so we never get the
        # buddy bridge "for free" — every form-row field below must
        # be flagged unless it has an explicit accessibleName.
        if _has_explicit_accessible_name(w):
            continue
        buddy = _find_buddy_label(w, all_labels)
        if buddy is not None:
            continue
        row_label = _form_row_label(w)
        if row_label is None:
            report.add(
                "missing-accessible-name",
                f"{cls} has no accessibleName, no buddy QLabel, and no QFormLayout row label",
                w,
            )
            continue
        # Form-row label exists but no buddy — still a labeling gap on
        # platforms that don't auto-bridge form labels to fields.
        report.add(
            "form-row-buddy-not-set",
            f"{cls} relies on QFormLayout row label {row_label!r} but the "
            f"label is not its buddy and no explicit accessibleName is set",
            w,
        )

    # ---- Paired-row disambiguation
    # Rows with multiple focusable widgets share one QFormLayout label;
    # screen readers can't tell the controls apart by name alone.
    seen_ids: set[int] = set()
    for w in focusable:
        if id(w) in seen_ids:
            continue
        siblings = _siblings_in_row(w)
        # Only consider rows with at least two focusable siblings inside
        # an inline QHBoxLayout that lives in a QFormLayout row.
        parent = w.parentWidget()
        row_label = _form_row_label(parent) if parent is not None else None
        if not siblings or row_label is None:
            continue
        # Skip if every member of the pair has an explicit accessibleName
        # — they're already disambiguated.
        members = [w, *siblings]
        if all(_has_explicit_accessible_name(m) for m in members):
            for m in members:
                seen_ids.add(id(m))
            continue
        for m in members:
            if not _has_explicit_accessible_name(m):
                report.add(
                    "paired-row-ambiguous",
                    f"{m.__class__.__name__} shares row label {row_label!r} "
                    f"with {len(members) - 1} other focusable sibling(s); "
                    f"screen reader will announce the same label for each",
                    m,
                )
            seen_ids.add(id(m))

    # ---- Pair-specific descriptions (duration value + unit, etc.)
    pairs_needing_descriptions = (
        ("duration_value_spin", "duration_unit_combo", "Duration value and unit"),
        ("interval_spin", "type_combo", "Recurrence interval and type"),
    )
    for value_attr, unit_attr, desc in pairs_needing_descriptions:
        val = getattr(dialog, value_attr, None)
        unit = getattr(dialog, unit_attr, None)
        if val is None or unit is None:
            continue
        if not _has_explicit_accessible_description(
            val
        ) or not _has_explicit_accessible_description(unit):
            report.add(
                "missing-pair-description",
                f"{desc} pair lacks accessibleDescription on at least one side; "
                f"screen reader cannot tie the value to its unit",
                val,
            )

    # ---- Keyboard-inaccessible disclosure surfaces
    # The Advanced toggle is a QLabel with linkActivated. QLabel cannot
    # accept focus by default and links inside it are not in the tab
    # chain, so keyboard-only users have no path to expand the dialog.
    advanced_toggle = getattr(dialog, "_advanced_toggle", None)
    if (
        isinstance(advanced_toggle, QLabel)
        and advanced_toggle.focusPolicy() == Qt.FocusPolicy.NoFocus
    ):
        report.add(
            "keyboard-inaccessible-disclosure",
            "Advanced disclosure is a QLabel with linkActivated; not "
            "keyboard-reachable. Use a QPushButton / QToolButton with "
            "checkable=True or a QCommandLinkButton instead",
            advanced_toggle,
        )

    return report


# ----------------------------------------------------------------- rendering


def render(report: Report, dialog: AddTodoDialog) -> str:
    timestamp = datetime.now().isoformat(timespec="seconds")
    lines = [
        "AddTodo dialog accessibility audit — " + timestamp,
        "Tracking: https://github.com/berrym/pytodo-qt/issues/22",
        "=" * 72,
        "",
        f"Focusable widgets: {report.focusable_count}",
        f"Tab-chain length:  {len(report.tab_chain)}",
        f"Gaps reported:     {len(report.gaps)}",
        "",
    ]
    if not report.gaps:
        lines.append("No accessibility gaps detected.")
        return "\n".join(lines)

    by_category: dict[str, list[Gap]] = {}
    for g in report.gaps:
        by_category.setdefault(g.category, []).append(g)

    lines.append("Gap classes (each maps to a follow-up issue):")
    lines.append("")
    for category, gaps in sorted(by_category.items()):
        lines.append(f"## {category} ({len(gaps)})")
        lines.append("")
        seen_details: set[str] = set()
        for g in gaps:
            entry = f"  - {g.widget_id}: {g.detail}"
            # Collapse exact duplicates (same widget id + detail)
            if entry in seen_details:
                continue
            seen_details.add(entry)
            lines.append(entry)
        lines.append("")

    lines.append("Tab chain (in order):")
    for i, wid in enumerate(report.tab_chain, start=1):
        lines.append(f"  {i:>3}. {wid}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the rendered report to this path in addition to stdout.",
    )
    args = parser.parse_args(argv)

    app = QApplication.instance() or QApplication(sys.argv)
    dialog = AddTodoDialog(columns=["Backlog", "Today", "Done"])
    # Expand the Advanced section so every control is realized and
    # findChildren picks them up. Driven through the toggle button's
    # checked state so the regular toggled-signal path runs.
    dialog._advanced_toggle.setChecked(True)
    # Ensure the layout has resolved before walking — without this,
    # findChildren still works (parent/child hierarchy is set at
    # construction) but visibility-based filtering can be off.
    dialog.adjustSize()

    report = audit(dialog)
    rendered = render(report, dialog)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
        print(f"\nReport written to: {args.output}")

    dialog.deleteLater()
    del app
    return 1 if report.gaps else 0


if __name__ == "__main__":
    raise SystemExit(main())


__test__ = False
