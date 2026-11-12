"""The application process exits cleanly after the main window closes.

At interpreter exit PyQt deletes every QObject Python still owns while
walking sip's table of wrappers. sip replaces that table when a wrapper
is added to a nearly full one, and the walk goes on reading the old
table. Application code that runs during the walk — an event filter, a
reimplemented event handler — wraps its arguments, so it can crash the
process after everything has been saved.

Whether a given exit crashes depends on how full the table happens to
be, so the exit code alone does not catch a regression. These tests
launch the real application in a subprocess and also check the
conditions that make the walk safe: the main window is already
destroyed, the application-wide event filter is already removed, and no
application code runs while the walk is in progress.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_PROBE = Path(__file__).parent / "exit_probe.py"
_TIMEOUT_SECONDS = 180


@pytest.fixture(scope="module")
def exit_report(tmp_path_factory: pytest.TempPathFactory) -> tuple[int, dict, str]:
    """Launch and quit the application once; return (exit code, report, stderr)."""
    root = tmp_path_factory.mktemp("clean_exit")
    report_path = root / "report.json"
    env = dict(os.environ)
    env.update(
        XDG_CONFIG_HOME=str(root / "config"),
        XDG_DATA_HOME=str(root / "data"),
        XDG_STATE_HOME=str(root / "state"),
        QT_QPA_PLATFORM="offscreen",
        # No secrets are read from or written to the real system keyring.
        PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
    )
    result = subprocess.run(
        [sys.executable, str(_PROBE), str(report_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    return result.returncode, report, result.stderr[-4000:]


def test_process_exits_with_status_zero(exit_report: tuple[int, dict, str]) -> None:
    code, _report, stderr = exit_report
    assert code == 0, f"exit status {code}; stderr tail:\n{stderr}"


def test_a_main_window_was_launched(exit_report: tuple[int, dict, str]) -> None:
    _code, report, stderr = exit_report
    assert report.get("windows_created") == 1, f"report {report}; stderr tail:\n{stderr}"


def test_main_window_is_destroyed_before_interpreter_exit(
    exit_report: tuple[int, dict, str],
) -> None:
    _code, report, _stderr = exit_report
    assert report.get("window_alive_at_exit") is False


def test_event_filter_is_removed_before_interpreter_exit(
    exit_report: tuple[int, dict, str],
) -> None:
    _code, report, _stderr = exit_report
    assert report.get("event_filter_installed_at_exit") is False


def test_no_application_code_runs_during_exit_cleanup(
    exit_report: tuple[int, dict, str],
) -> None:
    _code, report, _stderr = exit_report
    assert report.get("app_calls_during_cleanup") == []
