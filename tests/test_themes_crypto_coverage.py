"""Tests for themes and crypto modules to improve coverage."""

import os

import pytest
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QApplication

from pytodo_qt.crypto.aes_gcm import (
    KEY_SIZE,
    NONCE_SIZE,
    TAG_SIZE,
    AESGCMCipher,
    DecryptionError,
    EncryptedMessage,
)


@pytest.fixture(scope="session")
def app():
    """Create QApplication for tests."""
    _app = QApplication.instance()
    if _app is None:
        _app = QApplication([])
    return _app


# ── Themes ──────────────────────────────────────────────────────────────


class TestThemeEnum:
    """Test Theme enum values."""

    def test_theme_values(self):
        from pytodo_qt.gui.styles.themes import Theme

        assert Theme.LIGHT.value == "light"
        assert Theme.DARK.value == "dark"
        assert Theme.SYSTEM.value == "system"


class TestMakeFont:
    """Test make_font function."""

    def test_make_default_font(self, app):
        from pytodo_qt.gui.styles.themes import make_font

        font = make_font()
        assert font.pointSize() == 10

    def test_make_font_custom_size(self, app):
        from pytodo_qt.gui.styles.themes import make_font

        font = make_font(14)
        assert font.pointSize() == 14

    def test_make_mono_font(self, app):
        from pytodo_qt.gui.styles.themes import make_font

        font = make_font(mono=True)
        # Should have families set
        families = font.families()
        assert len(families) > 0


class TestCreatePalette:
    """Test create_palette function."""

    def test_light_palette(self, app):
        from pytodo_qt.gui.styles.themes import Theme, create_palette

        palette = create_palette(Theme.LIGHT)
        assert isinstance(palette, QPalette)
        # Light theme should have bright window color
        window_color = palette.color(QPalette.ColorRole.Window)
        luminance = (
            0.299 * window_color.red() + 0.587 * window_color.green() + 0.114 * window_color.blue()
        )
        assert luminance > 128

    def test_dark_palette(self, app):
        from pytodo_qt.gui.styles.themes import Theme, create_palette

        palette = create_palette(Theme.DARK)
        assert isinstance(palette, QPalette)
        window_color = palette.color(QPalette.ColorRole.Window)
        luminance = (
            0.299 * window_color.red() + 0.587 * window_color.green() + 0.114 * window_color.blue()
        )
        assert luminance < 128


class TestGetStylesheet:
    """Test get_stylesheet function."""

    def test_light_stylesheet(self, app):
        from pytodo_qt.gui.styles.themes import Theme, get_stylesheet

        stylesheet = get_stylesheet(Theme.LIGHT)
        assert "QMainWindow" in stylesheet
        assert "#f5f5f5" in stylesheet  # Light window color

    def test_dark_stylesheet(self, app):
        from pytodo_qt.gui.styles.themes import Theme, get_stylesheet

        stylesheet = get_stylesheet(Theme.DARK)
        assert "QMainWindow" in stylesheet
        assert "#1e1e1e" in stylesheet  # Dark window color

    def test_stylesheet_without_theme_arg(self, app):
        from pytodo_qt.gui.styles.themes import get_stylesheet

        stylesheet = get_stylesheet()
        assert "QMainWindow" in stylesheet


class TestApplyTheme:
    """Test apply_theme function."""

    def test_apply_light_theme(self, app):
        from pytodo_qt.gui.styles.themes import Theme, apply_theme

        apply_theme(app, Theme.LIGHT)
        # After applying, app should have the stylesheet
        assert app.styleSheet() != ""

    def test_apply_dark_theme(self, app):
        from pytodo_qt.gui.styles.themes import Theme, apply_theme

        apply_theme(app, Theme.DARK)
        assert app.styleSheet() != ""

    def test_apply_theme_no_arg(self, app):
        from pytodo_qt.gui.styles.themes import apply_theme

        apply_theme(app)
        assert app.styleSheet() != ""


class TestApplyCurrentTheme:
    """Test apply_current_theme function."""

    def test_apply_current_theme(self, app):
        from pytodo_qt.gui.styles.themes import apply_current_theme

        apply_current_theme()
        assert app.styleSheet() != ""


class TestGetSystemTheme:
    """Test get_system_theme function."""

    def test_returns_theme(self, app):
        from pytodo_qt.gui.styles.themes import Theme, get_system_theme

        result = get_system_theme()
        assert result in (Theme.LIGHT, Theme.DARK)


class TestGetCurrentTheme:
    """Test get_current_theme function."""

    def test_returns_theme(self, app):
        from pytodo_qt.gui.styles.themes import Theme, get_current_theme

        result = get_current_theme()
        assert result in (Theme.LIGHT, Theme.DARK)


class TestGetColors:
    """Test get_colors function."""

    def test_returns_color_dict(self, app):
        from pytodo_qt.gui.styles.themes import get_colors

        colors = get_colors()
        assert "window" in colors
        assert "text" in colors
        assert "highlight" in colors
        assert "priority_high" in colors
        assert "due_overdue" in colors


# ── Crypto: AES-GCM ────────────────────────────────────────────────────


class TestEncryptedMessage:
    """Test EncryptedMessage data class."""

    def test_to_bytes_and_back(self):
        nonce = os.urandom(NONCE_SIZE)
        ciphertext = os.urandom(32 + TAG_SIZE)
        msg = EncryptedMessage(nonce=nonce, ciphertext=ciphertext)

        data = msg.to_bytes()
        restored = EncryptedMessage.from_bytes(data)

        assert restored.nonce == nonce
        assert restored.ciphertext == ciphertext

    def test_from_bytes_too_short(self):
        with pytest.raises(DecryptionError, match="too short"):
            EncryptedMessage.from_bytes(b"short")


class TestAESGCMCipher:
    """Test AES-256-GCM cipher."""

    def test_invalid_key_size(self):
        with pytest.raises(ValueError, match="Key must be"):
            AESGCMCipher(b"short_key")

    def test_encrypt_decrypt_roundtrip(self):
        key = os.urandom(KEY_SIZE)
        cipher = AESGCMCipher(key)

        plaintext = b"Hello, World!"
        encrypted = cipher.encrypt(plaintext)
        decrypted = cipher.decrypt(encrypted)

        assert decrypted == plaintext

    def test_encrypt_decrypt_with_aad(self):
        key = os.urandom(KEY_SIZE)
        cipher = AESGCMCipher(key)

        plaintext = b"Secret data"
        aad = b"authenticated but not encrypted"
        encrypted = cipher.encrypt(plaintext, associated_data=aad)
        decrypted = cipher.decrypt(encrypted, associated_data=aad)

        assert decrypted == plaintext

    def test_decrypt_wrong_key_fails(self):
        key1 = os.urandom(KEY_SIZE)
        key2 = os.urandom(KEY_SIZE)
        cipher1 = AESGCMCipher(key1)
        cipher2 = AESGCMCipher(key2)

        encrypted = cipher1.encrypt(b"test")
        with pytest.raises(DecryptionError):
            cipher2.decrypt(encrypted)

    def test_decrypt_tampered_ciphertext_fails(self):
        key = os.urandom(KEY_SIZE)
        cipher = AESGCMCipher(key)

        encrypted = cipher.encrypt(b"test")
        # Tamper with ciphertext
        tampered = EncryptedMessage(
            nonce=encrypted.nonce,
            ciphertext=encrypted.ciphertext[:-1] + bytes([encrypted.ciphertext[-1] ^ 0xFF]),
        )
        with pytest.raises(DecryptionError):
            cipher.decrypt(tampered)

    def test_decrypt_wrong_aad_fails(self):
        key = os.urandom(KEY_SIZE)
        cipher = AESGCMCipher(key)

        encrypted = cipher.encrypt(b"test", associated_data=b"correct")
        with pytest.raises(DecryptionError):
            cipher.decrypt(encrypted, associated_data=b"wrong")

    def test_encrypt_empty_message(self):
        key = os.urandom(KEY_SIZE)
        cipher = AESGCMCipher(key)

        encrypted = cipher.encrypt(b"")
        decrypted = cipher.decrypt(encrypted)

        assert decrypted == b""


# ── Crypto: KDF ─────────────────────────────────────────────────────────


class TestKeyDerivation:
    """Test key derivation functions."""

    def test_derive_key_argon2(self):
        from pytodo_qt.crypto.kdf import derive_key_argon2

        result = derive_key_argon2("password123")
        assert len(result.key) == 32
        assert len(result.salt) > 0

    def test_derive_key_argon2_with_salt(self):
        from pytodo_qt.crypto.kdf import derive_key_argon2

        result1 = derive_key_argon2("password", salt=b"0" * 16)
        result2 = derive_key_argon2("password", salt=b"0" * 16)
        assert result1.key == result2.key

    def test_derive_key_argon2_different_passwords(self):
        from pytodo_qt.crypto.kdf import derive_key_argon2

        salt = os.urandom(16)
        result1 = derive_key_argon2("password1", salt=salt)
        result2 = derive_key_argon2("password2", salt=salt)
        assert result1.key != result2.key

    def test_pbkdf2_fallback(self):
        from pytodo_qt.crypto.kdf import _derive_key_pbkdf2_fallback

        result = _derive_key_pbkdf2_fallback("password")
        assert len(result.key) == 32
        assert len(result.salt) > 0

    def test_pbkdf2_with_salt(self):
        from pytodo_qt.crypto.kdf import _derive_key_pbkdf2_fallback

        salt = os.urandom(16)
        result1 = _derive_key_pbkdf2_fallback("pass", salt=salt)
        result2 = _derive_key_pbkdf2_fallback("pass", salt=salt)
        assert result1.key == result2.key
