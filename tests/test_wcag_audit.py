"""The contrast audit, run with the tests.

`scripts/wcag_audit.py` measures the color pairs of the desktop and
of the web page against WCAG 2.1 AA: 4.5:1 for text, 3:1 for a
graphical object. A pair that falls short fails here, and so does a
group of pairs that the audit has but does not report.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "wcag_audit.py"


@pytest.fixture(scope="module")
def audit():
    spec = importlib.util.spec_from_file_location("wcag_audit", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # The script's dataclass looks its module up by name.
    import sys

    sys.modules["wcag_audit"] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop("wcag_audit", None)


def test_no_essential_pair_falls_short(audit):
    short = [
        f"[{pair.theme}] {pair.label}: {pair.fg} on {pair.bg} is "
        f"{audit.contrast_ratio(pair.fg, pair.bg):.2f}:1, needs {pair.threshold}"
        for pair in audit.collect_pairs()
        if pair.essential and audit.contrast_ratio(pair.fg, pair.bg) < pair.threshold
    ]
    assert short == []


def test_the_script_reports_success(audit, capsys):
    assert audit.main() == 0
    assert "0 fail" in capsys.readouterr().out


def test_every_group_of_pairs_is_reported_and_counted(audit, capsys):
    """A group built by the script and left out of `sections` was
    counted in the total and never measured."""
    reported = {(pair.label, pair.theme) for pair in audit.collect_pairs()}
    groups = [
        name
        for name in vars(audit)
        if name.startswith("_") and name.endswith("_pairs") and callable(getattr(audit, name))
    ]
    assert len(groups) >= 6
    for name in groups:
        for pair in getattr(audit, name)():
            assert (pair.label, pair.theme) in reported, f"{name}: {pair.label}"

    audit.main()
    out = capsys.readouterr().out
    for pair in audit.collect_pairs():
        assert pair.label in out, pair.label


def test_the_audits_ratio_is_the_applications(audit):
    """Two implementations of one formula: the script's own, and the
    one the application chooses a text color with."""
    from pytodo_qt.core import bar_palette

    for one, other in (("#ffffff", "#2563eb"), ("#000000", "#fbbf24"), ("#1a1a1a", "#64b5f6")):
        assert audit.contrast_ratio(one, other) == pytest.approx(
            bar_palette.contrast_ratio(one, other), abs=0.005
        )
