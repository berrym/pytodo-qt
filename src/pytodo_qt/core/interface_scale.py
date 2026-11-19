"""interface_scale.py

The size of the whole interface, as a percentage.

Qt can draw an application larger than its own measures say: text,
spacing, icons and fixed sizes alike, with the layout it has at 100%.
It reads the factor from the environment variable ``QT_SCALE_FACTOR``
when the application object is made, and not again. The setting is
therefore applied before that object exists, and a change of it takes
effect the next time the application starts.

So that a new size shows at once, the application starts itself again
when one is accepted: it quits in the ordinary way, and once its event
loop has ended and its lock is free, it starts a new process that draws
at the new size, with the window where it was.

Nothing here needs Qt.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping, MutableMapping, Sequence

from .logger import Logger

logger = Logger(__name__)

# The sizes offered, in percent. 200 is what WCAG 1.4.4 asks text to be
# resizable to.
SCALES: tuple[int, ...] = (100, 110, 125, 150, 175, 200)
DEFAULT_SCALE = 100

_FACTOR_VARIABLE = "QT_SCALE_FACTOR"
_ROUNDING_VARIABLE = "QT_SCALE_FACTOR_ROUNDING_POLICY"

# What decided the size of this run: the setting, the environment the
# application was started in, or nothing (100%).
FROM_SETTING = "setting"
FROM_ENVIRONMENT = "environment"
FROM_NOTHING = "none"

_source = FROM_NOTHING
# Whether the rounding policy in the environment was put there by apply().
_rounding_is_ours = False
# Whether the size of this run was given with ``--scale`` in place of
# the stored one.
_overridden = False

# The window's place and size, handed to the process that is started
# again: "x,y,width,height,maximized" in the screen's own pixels, which
# stay what they are when the size of the interface changes.
_WINDOW_VARIABLE = "PYTODO_QT_RESTORE_WINDOW"

_restart_requested = False
_restart_window: str | None = None


def normalized(value: object) -> int:
    """A stored value as one of the sizes offered.

    A value that is not one of them, as a hand-edited configuration may
    hold, becomes the nearest; one that is no number becomes 100.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return DEFAULT_SCALE
    return min(SCALES, key=lambda scale: (abs(scale - value), scale))


def apply(
    scale: int, environ: MutableMapping[str, str] | None = None, *, overridden: bool = False
) -> str:
    """Set the size for the application object that is about to be made.

    A factor already in the environment is left alone and decides: who
    starts the application with ``QT_SCALE_FACTOR`` set has asked for
    that. ``overridden`` says that the size was given with ``--scale``
    and is not the stored one. Returns what decided the size.
    """
    global _source, _rounding_is_ours, _overridden
    _overridden = overridden
    env = os.environ if environ is None else environ
    if env.get(_FACTOR_VARIABLE):
        _source = FROM_ENVIRONMENT
        logger.log.info(
            "Interface size left to %s=%s from the environment",
            _FACTOR_VARIABLE,
            env[_FACTOR_VARIABLE],
        )
        return _source

    scale = normalized(scale)
    if scale == DEFAULT_SCALE:
        _source = FROM_NOTHING
        return _source

    env[_FACTOR_VARIABLE] = f"{scale / 100:g}"
    # A factor such as 1.25 is used as it is, not rounded to a whole one.
    if _ROUNDING_VARIABLE not in env:
        env[_ROUNDING_VARIABLE] = "PassThrough"
        _rounding_is_ours = True
    _source = FROM_SETTING
    logger.log.info("Interface size %d%%", scale)
    return _source


def source() -> str:
    """What decided the size of this run."""
    return _source


def overridden() -> bool:
    """Whether this run's size was given with ``--scale``.

    The stored size is then another on purpose: it is not one that
    waits for a restart.
    """
    return _overridden


def active_factor(environ: MutableMapping[str, str] | None = None) -> float:
    """The factor this run is drawn at: 1.0 at 100%."""
    env = os.environ if environ is None else environ
    try:
        factor = float(env.get(_FACTOR_VARIABLE, "") or 1.0)
    except ValueError:
        return 1.0
    return factor if factor > 0 else 1.0


def fits(scale: int, available: tuple[float, float], least: tuple[int, int]) -> bool:
    """Whether a window of the size ``least`` has room at ``scale``.

    ``available`` is the screen's room at 100%. A larger interface
    leaves the window fewer of its own pixels: at 200% a screen of
    1600 x 1000 holds a window of 800 x 500.
    """
    factor = scale / 100
    return available[0] / factor >= least[0] and available[1] / factor >= least[1]


# ---------------------------------------------------------------------------
# Starting again at a new size
# ---------------------------------------------------------------------------


def encode_window(
    x: int, y: int, width: int, height: int, maximized: bool, factor: float | None = None
) -> str:
    """A window's place and size in the screen's own pixels.

    The window counts in the pixels of the size it is drawn at: at 150%
    a width of 1000 covers 1500 of the screen's. The screen's are kept,
    so that the window comes back as large on the screen as it was.
    """
    scale = active_factor() if factor is None else factor
    numbers = (round(x * scale), round(y * scale), round(width * scale), round(height * scale))
    return ",".join(str(n) for n in (*numbers, int(maximized)))


def decode_window(text: str, factor: float | None = None) -> tuple[int, int, int, int, bool] | None:
    """The place and size for a window of this run, or None for what cannot be read."""
    scale = active_factor() if factor is None else factor
    try:
        x, y, width, height, maximized = (int(part) for part in text.split(","))
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return (
        round(x / scale),
        round(y / scale),
        round(width / scale),
        round(height / scale),
        bool(maximized),
    )


def window_to_restore(
    environ: MutableMapping[str, str] | None = None,
) -> tuple[int, int, int, int, bool] | None:
    """The window handed over by the process that started this one, once."""
    env = os.environ if environ is None else environ
    text = env.pop(_WINDOW_VARIABLE, None)
    return decode_window(text, active_factor(env)) if text else None


def request_restart(window: str | None = None) -> None:
    """Ask for the application to be started again once it has quit."""
    global _restart_requested, _restart_window
    _restart_requested = True
    _restart_window = window


def restart_requested() -> bool:
    return _restart_requested


def relaunch_command(arguments: Sequence[str], *, executable: str, frozen: bool) -> list[str]:
    """The command that starts the application again.

    A packaged application is its own executable; from source it is the
    interpreter running the package. ``--scale`` is left out: it stood
    in for the stored size at this start, and the new size is the stored
    one.
    """
    kept: list[str] = []
    skip = False
    for argument in arguments:
        if skip:
            skip = False
        elif argument == "--scale":
            skip = True
        elif not argument.startswith("--scale="):
            kept.append(argument)
    return [executable, *kept] if frozen else [executable, "-m", "pytodo_qt", *kept]


def relaunch_environment(
    environ: Mapping[str, str] | None = None, window: str | None = None
) -> dict[str, str]:
    """The environment for the process that is started again.

    A factor this run put into its environment is taken out: left in,
    it would count as one the application was started with, and decide
    in place of the new size.
    """
    env = dict(os.environ if environ is None else environ)
    if _source == FROM_SETTING:
        env.pop(_FACTOR_VARIABLE, None)
        if _rounding_is_ours:
            env.pop(_ROUNDING_VARIABLE, None)
    env.pop(_WINDOW_VARIABLE, None)
    if window:
        env[_WINDOW_VARIABLE] = window
    return env


def relaunch(arguments: Sequence[str] | None = None) -> bool:
    """Start the application again, if that was asked for.

    To be called when the event loop has ended and the instance lock is
    free. The new process does not belong to this one's session, so it
    outlives it.
    """
    if not _restart_requested:
        return False
    command = relaunch_command(
        sys.argv[1:] if arguments is None else arguments,
        executable=sys.executable,
        frozen=bool(getattr(sys, "frozen", False)),
    )
    try:
        subprocess.Popen(
            command,
            env=relaunch_environment(window=_restart_window),
            stdin=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    except OSError:
        logger.log.exception("Could not start the application again")
        return False
    logger.log.info("Started again for the new interface size")
    return True
