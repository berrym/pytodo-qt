"""Launch the application, quit it, and report what interpreter exit finds.

Run as a script by ``tests/test_clean_exit.py``; it is not a test module.

    python tests/exit_probe.py REPORT_PATH

The caller points ``XDG_CONFIG_HOME``, ``XDG_DATA_HOME`` and
``XDG_STATE_HOME`` at a scratch directory, so the launch reads and writes
nothing outside it. The network server, discovery and the web interface
are switched off on the command line.

Two ``atexit`` hooks bracket PyQt's own exit cleanup. ``atexit`` runs its
callbacks last-registered-first and PyQt registers its cleanup when
``PyQt6.QtCore`` is imported, so a hook registered before that import
runs after the cleanup and one registered after it runs before.

The report is JSON:

- ``windows_created`` — main windows constructed.
- ``window_alive_at_exit`` — whether any still existed when PyQt's
  cleanup was about to start.
- ``event_filter_installed_at_exit`` — whether the application-wide
  dropdown event filter was still installed at that point.
- ``app_calls_during_cleanup`` — application functions called while the
  cleanup ran, as ``file:line name`` strings.
"""

from __future__ import annotations

import atexit
import json
import os
import sys

_REPORT_PATH = sys.argv[1]
_QUIT_AFTER_MS = 500

_report: dict[str, object] = {}
_app_calls: list[str] = []


def _write_report() -> None:
    _report["app_calls_during_cleanup"] = _app_calls
    with open(_REPORT_PATH, "w", encoding="utf-8") as handle:
        json.dump(_report, handle)


def _after_cleanup() -> None:
    sys.setprofile(None)
    _write_report()


atexit.register(_after_cleanup)

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QTimer  # noqa: E402 — registers PyQt's exit cleanup

import pytodo_qt  # noqa: E402
import pytodo_qt.gui.main_window as main_window_module  # noqa: E402
import pytodo_qt.gui.styles.themes as themes  # noqa: E402

_PACKAGE_DIR = os.path.dirname(os.path.abspath(pytodo_qt.__file__))
_windows: list[main_window_module.MainWindow] = []


def _profile(frame, event, _arg) -> None:  # type: ignore[no-untyped-def]
    if event != "call":
        return
    code = frame.f_code
    if code.co_filename.startswith(_PACKAGE_DIR):
        _app_calls.append(f"{code.co_filename}:{code.co_firstlineno} {code.co_name}")


def _before_cleanup() -> None:
    _report["windows_created"] = len(_windows)
    _report["window_alive_at_exit"] = any(not sip.isdeleted(w) for w in _windows)
    _report["event_filter_installed_at_exit"] = themes._dropdown_configurator is not None
    # Written now as well, so a crash inside the cleanup still leaves a report.
    _write_report()
    sys.setprofile(_profile)


atexit.register(_before_cleanup)

_original_init = main_window_module.MainWindow.__init__


def _init_then_quit(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
    _original_init(self, *args, **kwargs)
    _windows.append(self)
    QTimer.singleShot(_QUIT_AFTER_MS, self._quit_application)


main_window_module.MainWindow.__init__ = _init_then_quit  # type: ignore[method-assign]

from pytodo_qt.__main__ import main  # noqa: E402

sys.argv = ["pytodo-qt", "--server", "no", "--discovery", "no", "--web", "no"]
main()
