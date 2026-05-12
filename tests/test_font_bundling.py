"""Tests for bundled font loading and configuration."""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QFontDatabase

from pytodo_qt.core.config import AppConfig, AppearanceConfig
from pytodo_qt.gui.styles.themes import (
    _BUNDLED_EMOJI_FONT,
    _BUNDLED_TEXT_FONTS,
    _FONTS_DIR,
    DEFAULT_FONT_SIZE,
    load_bundled_fonts,
    make_font,
)

# ---------------------------------------------------------------------------
# TestBundledFontFiles
# ---------------------------------------------------------------------------


class TestBundledFontFiles:
    """Verify all bundled font files exist on disk."""

    def test_fonts_directory_exists(self) -> None:
        assert _FONTS_DIR.is_dir(), f"Fonts directory not found: {_FONTS_DIR}"

    @pytest.mark.parametrize("filename", list(_BUNDLED_TEXT_FONTS))
    def test_text_font_exists(self, filename: str) -> None:
        path = _FONTS_DIR / filename
        assert path.exists(), f"Bundled text font not found: {path}"
        assert path.stat().st_size > 0

    def test_emoji_font_exists(self) -> None:
        path = _FONTS_DIR / _BUNDLED_EMOJI_FONT
        assert path.exists(), f"Bundled emoji font not found: {path}"
        assert path.stat().st_size > 0

    def test_license_file_exists(self) -> None:
        ofl = _FONTS_DIR / "OFL.txt"
        assert ofl.exists(), "OFL license file missing"


# ---------------------------------------------------------------------------
# TestLoadBundledFonts
# ---------------------------------------------------------------------------


class TestLoadBundledFonts:
    """Test font registration with Qt."""

    def test_load_bundled_fonts_registers_text_fonts(self, qtbot) -> None:
        # Emoji font may fail in offscreen mode (Qt CBDT limitation),
        # so we only verify text fonts register successfully
        load_bundled_fonts()
        families = QFontDatabase.families()
        assert "Noto Sans" in families
        assert "Noto Sans Mono" in families

    def test_noto_sans_registered(self, qtbot) -> None:
        load_bundled_fonts()
        families = QFontDatabase.families()
        assert "Noto Sans" in families

    def test_noto_sans_mono_registered(self, qtbot) -> None:
        load_bundled_fonts()
        families = QFontDatabase.families()
        assert "Noto Sans Mono" in families


# ---------------------------------------------------------------------------
# TestAppearanceConfig
# ---------------------------------------------------------------------------


class TestAppearanceConfigFont:
    """Test font config defaults and serialization."""

    def test_default_is_bundled(self) -> None:
        config = AppearanceConfig()
        assert config.font == "bundled"

    def test_config_font_toml_roundtrip(self) -> None:
        config = AppConfig()
        config.appearance.font = "Custom Family"
        toml_str = config.to_toml()
        assert 'font = "Custom Family"' in toml_str

    def test_config_from_dict_font(self) -> None:
        data = {"appearance": {"font": "monospace"}}
        config = AppConfig.from_dict(data)
        assert config.appearance.font == "monospace"

    def test_config_from_dict_default_font(self) -> None:
        data = {"appearance": {}}
        config = AppConfig.from_dict(data)
        assert config.appearance.font == "bundled"


# ---------------------------------------------------------------------------
# TestMakeFont
# ---------------------------------------------------------------------------


class TestMakeFont:
    """Test make_font() respects config settings."""

    def test_make_font_default_size(self, qtbot) -> None:
        font = make_font()
        assert font.pointSize() == DEFAULT_FONT_SIZE

    def test_make_font_mono(self, qtbot) -> None:
        font = make_font(mono=True)
        # Should have families set (at least system mono stack)
        families = font.families()
        assert len(families) > 0

    def test_make_font_custom_size(self, qtbot) -> None:
        font = make_font(14)
        assert font.pointSize() == 14
