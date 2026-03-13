"""Tests for legacy AES-CBC decryption (v0.2.x migration support)."""

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from pytodo_qt.crypto.legacy import LegacyAESCipher, decrypt_legacy_data


def _encrypt_legacy(plaintext: bytes, passphrase: str) -> bytes:
    """Helper to create legacy-format encrypted data for testing.

    This mimics the original pycryptodomex AESCipher.encrypt() behavior.
    """
    key = hashlib.sha256(passphrase.encode("utf-8")).digest()
    iv = os.urandom(16)

    # Pad plaintext with PKCS7
    padder = PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()

    # Encrypt with AES-CBC
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()

    # Return base64-encoded IV + ciphertext
    return base64.b64encode(iv + ciphertext)


class TestLegacyAESCipher:
    """Tests for LegacyAESCipher class."""

    def test_initialization(self):
        """Test cipher initialization with passphrase."""
        cipher = LegacyAESCipher("test_password")
        expected_key = hashlib.sha256(b"test_password").digest()
        assert cipher.key == expected_key

    def test_block_size(self):
        """Test block size constant."""
        assert LegacyAESCipher.BLOCK_SIZE == 16

    def test_decrypt_valid_data(self):
        """Test decryption of valid legacy-encrypted data."""
        passphrase = "my_secret_key"
        plaintext = b"Hello, World! This is a test message."

        encrypted = _encrypt_legacy(plaintext, passphrase)
        cipher = LegacyAESCipher(passphrase)
        decrypted = cipher.decrypt(encrypted)

        assert decrypted == plaintext

    def test_decrypt_unicode_passphrase(self):
        """Test decryption with Unicode passphrase."""
        passphrase = "пароль_日本語_🔐"
        plaintext = b"Secret data"

        encrypted = _encrypt_legacy(plaintext, passphrase)
        cipher = LegacyAESCipher(passphrase)
        decrypted = cipher.decrypt(encrypted)

        assert decrypted == plaintext

    def test_decrypt_empty_message(self):
        """Test decryption of empty message."""
        passphrase = "test_key"
        plaintext = b""

        encrypted = _encrypt_legacy(plaintext, passphrase)
        cipher = LegacyAESCipher(passphrase)
        decrypted = cipher.decrypt(encrypted)

        assert decrypted == plaintext

    def test_decrypt_long_message(self):
        """Test decryption of long message (multiple blocks)."""
        passphrase = "test_key"
        # Create a message that spans multiple AES blocks
        plaintext = b"A" * 1000

        encrypted = _encrypt_legacy(plaintext, passphrase)
        cipher = LegacyAESCipher(passphrase)
        decrypted = cipher.decrypt(encrypted)

        assert decrypted == plaintext

    def test_decrypt_wrong_passphrase(self):
        """Test decryption with wrong passphrase does not recover plaintext.

        AES-CBC lacks authentication, so wrong-key decryption produces
        garbage.  Usually PKCS7 unpadding rejects it (None), but
        occasionally garbage has valid padding and returns bytes != plaintext.
        """
        correct_passphrase = "correct_password"
        wrong_passphrase = "wrong_password"
        plaintext = b"Secret message"

        encrypted = _encrypt_legacy(plaintext, correct_passphrase)
        cipher = LegacyAESCipher(wrong_passphrase)
        result = cipher.decrypt(encrypted)

        assert result is None or result != plaintext

    def test_decrypt_invalid_base64(self):
        """Test decryption of invalid base64 data returns None."""
        cipher = LegacyAESCipher("password")
        result = cipher.decrypt(b"not-valid-base64!!!")

        assert result is None

    def test_decrypt_truncated_data(self):
        """Test decryption of truncated data returns None."""
        passphrase = "test_key"
        plaintext = b"Secret message"

        encrypted = _encrypt_legacy(plaintext, passphrase)
        # Truncate the encrypted data
        truncated = encrypted[: len(encrypted) // 2]

        cipher = LegacyAESCipher(passphrase)
        result = cipher.decrypt(truncated)

        # Should return None due to padding error
        assert result is None

    def test_decrypt_corrupted_ciphertext(self):
        """Test decryption of corrupted ciphertext returns None."""
        passphrase = "test_key"
        plaintext = b"Secret message"

        encrypted = _encrypt_legacy(plaintext, passphrase)
        # Corrupt the encrypted data
        decoded = base64.b64decode(encrypted)
        corrupted = bytearray(decoded)
        # Flip bits in the ciphertext portion (after IV)
        if len(corrupted) > 20:
            corrupted[20] ^= 0xFF
        corrupted = base64.b64encode(bytes(corrupted))

        cipher = LegacyAESCipher(passphrase)
        result = cipher.decrypt(corrupted)

        # Should return None due to padding error
        assert result is None

    def test_decrypt_too_short_data(self):
        """Test decryption of data shorter than IV returns None."""
        cipher = LegacyAESCipher("password")
        # Less than 16 bytes (IV size)
        short_data = base64.b64encode(b"short")

        result = cipher.decrypt(short_data)

        assert result is None

    def test_decrypt_json_data(self):
        """Test decryption of JSON data (common use case for database)."""
        passphrase = "database_key"
        plaintext = b'{"lists": {"Shopping": [{"reminder": "Buy milk"}]}}'

        encrypted = _encrypt_legacy(plaintext, passphrase)
        cipher = LegacyAESCipher(passphrase)
        decrypted = cipher.decrypt(encrypted)

        assert decrypted == plaintext


class TestDecryptLegacyDataFunction:
    """Tests for decrypt_legacy_data convenience function."""

    def test_decrypt_legacy_data_success(self):
        """Test successful decryption via convenience function."""
        passphrase = "my_key"
        plaintext = b"Test message"

        encrypted = _encrypt_legacy(plaintext, passphrase)
        decrypted = decrypt_legacy_data(encrypted, passphrase)

        assert decrypted == plaintext

    def test_decrypt_legacy_data_wrong_key(self):
        """Test decryption failure with wrong key.

        AES-CBC has no authentication tag, so decrypting with the wrong
        key produces garbage.  PKCS7 unpadding *usually* rejects the
        garbage (returning None), but ~6% of the time the last byte is
        accidentally valid padding and we get garbage bytes back.  Either
        outcome means the original plaintext is not recovered.
        """
        plaintext = b"Test message"

        encrypted = _encrypt_legacy(plaintext, "correct_key")
        decrypted = decrypt_legacy_data(encrypted, "wrong_key")

        assert decrypted is None or decrypted != plaintext

    def test_decrypt_legacy_data_invalid_input(self):
        """Test decryption with invalid input."""
        result = decrypt_legacy_data(b"invalid", "key")

        assert result is None


class TestLegacyMigrationScenarios:
    """Tests for realistic migration scenarios."""

    def test_migrate_simple_todo_list(self):
        """Test migrating a simple todo list JSON."""
        passphrase = "user_password"
        legacy_data = b"""{
            "Shopping": [
                {"reminder": "Buy milk", "priority": 2, "complete": false},
                {"reminder": "Buy bread", "priority": 3, "complete": true}
            ]
        }"""

        encrypted = _encrypt_legacy(legacy_data, passphrase)
        decrypted = decrypt_legacy_data(encrypted, passphrase)

        assert decrypted == legacy_data

    def test_migrate_empty_database(self):
        """Test migrating an empty database."""
        passphrase = "password"
        legacy_data = b"{}"

        encrypted = _encrypt_legacy(legacy_data, passphrase)
        decrypted = decrypt_legacy_data(encrypted, passphrase)

        assert decrypted == legacy_data

    def test_migrate_special_characters(self):
        """Test migrating data with special characters."""
        passphrase = "password"
        legacy_data = "Café résumé naïve 日本語 🎉".encode()

        encrypted = _encrypt_legacy(legacy_data, passphrase)
        decrypted = decrypt_legacy_data(encrypted, passphrase)

        assert decrypted == legacy_data
