"""sound_player.py

Sound notification player for focus timer transitions.
Uses QSoundEffect from PyQt6-Multimedia when available;
silently disables if the package is not installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QUrl

if TYPE_CHECKING:
    from ...core.config import PomodoroConfig

_SOUNDS_DIR = Path(__file__).parent.parent / "sounds"

try:
    from PyQt6.QtMultimedia import QSoundEffect  # noqa: F401

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


class SoundPlayer(QObject):
    """Plays notification sounds on focus timer state transitions."""

    def __init__(self, config: PomodoroConfig, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._enabled = config.sound_enabled
        self._volume = config.sound_volume / 100.0  # QSoundEffect uses 0.0-1.0
        self._effects: dict[str, object] = {}

        if _AVAILABLE:
            from PyQt6.QtMultimedia import QSoundEffect

            for name in ("work-complete", "break-complete"):
                path = _SOUNDS_DIR / f"{name}.wav"
                if path.exists():
                    effect = QSoundEffect(self)
                    effect.setSource(QUrl.fromLocalFile(str(path)))
                    effect.setVolume(self._volume)
                    self._effects[name] = effect

    def play(self, sound_name: str) -> None:
        """Play a named sound if enabled and available."""
        if not self._enabled or not _AVAILABLE:
            return
        effect = self._effects.get(sound_name)
        if effect is not None:
            from PyQt6.QtMultimedia import QSoundEffect

            assert isinstance(effect, QSoundEffect)
            effect.setVolume(self._volume)
            effect.play()

    def update_config(self, config: PomodoroConfig) -> None:
        """Update enabled/volume from new config."""
        self._enabled = config.sound_enabled
        self._volume = config.sound_volume / 100.0
