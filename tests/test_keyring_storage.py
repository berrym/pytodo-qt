"""Tests for keyring storage module."""

import base64
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pytodo_qt.crypto.key_exchange import IdentityKeyPair
from pytodo_qt.crypto.keyring_storage import (
    KEYRING_ENCRYPTION_KEY,
    KEYRING_IDENTITY_KEY,
    KEYRING_SERVICE,
    KeyringError,
    KeyringUnavailableError,
    StoredIdentity,
    _get_identity_file_path,
    _get_local_key_file_path,
    _get_or_create_identity_file,
    _load_local_key_file,
    _store_identity_file,
    _store_local_key_file,
    delete_identity,
    get_or_create_identity,
    get_or_create_local_key,
    load_identity,
    load_local_encryption_key,
    store_identity,
    store_local_encryption_key,
)
from pytodo_qt.crypto.aes_gcm import generate_key


class TestKeyringConstants:
    """Test keyring constants are properly defined."""

    def test_service_name(self):
        """Test keyring service name."""
        assert KEYRING_SERVICE == "pytodo-qt"

    def test_identity_key_name(self):
        """Test identity key name."""
        assert KEYRING_IDENTITY_KEY == "identity-private-key"

    def test_encryption_key_name(self):
        """Test encryption key name."""
        assert KEYRING_ENCRYPTION_KEY == "local-encryption-key"


class TestStoredIdentity:
    """Test StoredIdentity dataclass."""

    def test_stored_identity_creation(self):
        """Test creating a StoredIdentity."""
        keypair = IdentityKeyPair.generate()
        fingerprint = keypair.fingerprint()
        stored = StoredIdentity(keypair=keypair, fingerprint=fingerprint)

        assert stored.keypair is keypair
        assert stored.fingerprint == fingerprint


class TestStoreIdentity:
    """Tests for store_identity function."""

    def test_store_identity_success(self):
        """Test successful identity storage."""
        mock_keyring = MagicMock()
        keypair = IdentityKeyPair.generate()

        with patch("pytodo_qt.crypto.keyring_storage._get_keyring", return_value=mock_keyring):
            fingerprint = store_identity(keypair)

        assert fingerprint == keypair.fingerprint()
        mock_keyring.set_password.assert_called_once()
        call_args = mock_keyring.set_password.call_args
        assert call_args[0][0] == KEYRING_SERVICE
        assert call_args[0][1] == KEYRING_IDENTITY_KEY
        # Verify the stored value is base64-encoded private key
        stored_value = call_args[0][2]
        decoded = base64.b64decode(stored_value.encode("ascii"))
        assert decoded == keypair.private_bytes()

    def test_store_identity_keyring_unavailable(self):
        """Test storage when keyring is unavailable."""
        keypair = IdentityKeyPair.generate()

        with patch(
            "pytodo_qt.crypto.keyring_storage._get_keyring",
            side_effect=KeyringUnavailableError("Not available"),
        ):
            with pytest.raises(KeyringError):
                store_identity(keypair)

    def test_store_identity_keyring_error(self):
        """Test storage when keyring write fails."""
        mock_keyring = MagicMock()
        mock_keyring.set_password.side_effect = Exception("Write failed")
        keypair = IdentityKeyPair.generate()

        with patch("pytodo_qt.crypto.keyring_storage._get_keyring", return_value=mock_keyring):
            with pytest.raises(KeyringError) as exc_info:
                store_identity(keypair)
            assert "Failed to store identity" in str(exc_info.value)


class TestLoadIdentity:
    """Tests for load_identity function."""

    def test_load_identity_success(self):
        """Test successful identity loading."""
        keypair = IdentityKeyPair.generate()
        encoded = base64.b64encode(keypair.private_bytes()).decode("ascii")

        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = encoded

        with patch("pytodo_qt.crypto.keyring_storage._get_keyring", return_value=mock_keyring):
            result = load_identity()

        assert result is not None
        assert result.keypair.public_bytes() == keypair.public_bytes()
        assert result.fingerprint == keypair.fingerprint()

    def test_load_identity_not_found(self):
        """Test loading when identity doesn't exist."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = None

        with patch("pytodo_qt.crypto.keyring_storage._get_keyring", return_value=mock_keyring):
            result = load_identity()

        assert result is None

    def test_load_identity_keyring_unavailable(self):
        """Test loading when keyring is unavailable."""
        with patch(
            "pytodo_qt.crypto.keyring_storage._get_keyring",
            side_effect=KeyringUnavailableError("Not available"),
        ):
            with pytest.raises(KeyringUnavailableError):
                load_identity()

    def test_load_identity_invalid_data(self):
        """Test loading when keyring contains invalid data."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = "not-valid-base64!!!"

        with patch("pytodo_qt.crypto.keyring_storage._get_keyring", return_value=mock_keyring):
            with pytest.raises(KeyringError):
                load_identity()


class TestDeleteIdentity:
    """Tests for delete_identity function."""

    def test_delete_identity_success(self):
        """Test successful identity deletion."""
        mock_keyring = MagicMock()

        with patch("pytodo_qt.crypto.keyring_storage._get_keyring", return_value=mock_keyring):
            result = delete_identity()

        assert result is True
        mock_keyring.delete_password.assert_called_once_with(
            KEYRING_SERVICE, KEYRING_IDENTITY_KEY
        )

    def test_delete_identity_not_found(self):
        """Test deletion when identity doesn't exist."""
        mock_keyring = MagicMock()
        mock_keyring.delete_password.side_effect = Exception("Not found")

        with patch("pytodo_qt.crypto.keyring_storage._get_keyring", return_value=mock_keyring):
            result = delete_identity()

        assert result is False


class TestGetOrCreateIdentity:
    """Tests for get_or_create_identity function."""

    def test_get_existing_identity(self):
        """Test getting existing identity."""
        keypair = IdentityKeyPair.generate()
        encoded = base64.b64encode(keypair.private_bytes()).decode("ascii")

        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = encoded

        with patch("pytodo_qt.crypto.keyring_storage._get_keyring", return_value=mock_keyring):
            result = get_or_create_identity()

        assert result.keypair.public_bytes() == keypair.public_bytes()

    def test_create_new_identity(self):
        """Test creating new identity when none exists."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = None

        with patch("pytodo_qt.crypto.keyring_storage._get_keyring", return_value=mock_keyring):
            result = get_or_create_identity()

        assert result is not None
        assert result.keypair is not None
        assert result.fingerprint is not None
        # Verify identity was stored
        mock_keyring.set_password.assert_called_once()

    def test_fallback_to_file_on_keyring_unavailable(self):
        """Test fallback to file storage when keyring unavailable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "pytodo_qt.crypto.keyring_storage._get_keyring",
                side_effect=KeyringUnavailableError("Not available"),
            ):
                with patch(
                    "pytodo_qt.crypto.keyring_storage._get_identity_file_path",
                    return_value=Path(tmpdir) / "identity.key",
                ):
                    result = get_or_create_identity()

            assert result is not None
            assert (Path(tmpdir) / "identity.key").exists()


class TestFileBasedStorage:
    """Tests for file-based fallback storage."""

    def test_store_identity_file(self):
        """Test storing identity to file."""
        keypair = IdentityKeyPair.generate()

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "pytodo_qt.crypto.keyring_storage._get_identity_file_path",
                return_value=Path(tmpdir) / "identity.key",
            ):
                result = _store_identity_file(keypair)

            assert result.keypair.public_bytes() == keypair.public_bytes()
            identity_file = Path(tmpdir) / "identity.key"
            assert identity_file.exists()
            # Check permissions (0o600 = owner read/write only)
            mode = identity_file.stat().st_mode & 0o777
            assert mode == 0o600

    def test_get_or_create_identity_file_existing(self):
        """Test loading existing identity from file."""
        keypair = IdentityKeyPair.generate()

        with tempfile.TemporaryDirectory() as tmpdir:
            identity_file = Path(tmpdir) / "identity.key"
            with open(identity_file, "wb") as f:
                f.write(keypair.private_bytes())

            with patch(
                "pytodo_qt.crypto.keyring_storage._get_identity_file_path",
                return_value=identity_file,
            ):
                result = _get_or_create_identity_file()

            assert result.keypair.public_bytes() == keypair.public_bytes()

    def test_get_or_create_identity_file_new(self):
        """Test creating new identity file when none exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            identity_file = Path(tmpdir) / "identity.key"

            with patch(
                "pytodo_qt.crypto.keyring_storage._get_identity_file_path",
                return_value=identity_file,
            ):
                result = _get_or_create_identity_file()

            assert result is not None
            assert identity_file.exists()

    def test_get_or_create_identity_file_corrupted(self):
        """Test handling corrupted identity file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            identity_file = Path(tmpdir) / "identity.key"
            with open(identity_file, "wb") as f:
                f.write(b"corrupted data")

            with patch(
                "pytodo_qt.crypto.keyring_storage._get_identity_file_path",
                return_value=identity_file,
            ):
                # Should generate new identity instead of failing
                result = _get_or_create_identity_file()

            assert result is not None


class TestLocalEncryptionKey:
    """Tests for local encryption key storage."""

    def test_store_local_key_success(self):
        """Test successful local key storage."""
        mock_keyring = MagicMock()
        key = generate_key()

        with patch("pytodo_qt.crypto.keyring_storage._get_keyring", return_value=mock_keyring):
            store_local_encryption_key(key)

        mock_keyring.set_password.assert_called_once()
        call_args = mock_keyring.set_password.call_args
        stored_value = call_args[0][2]
        decoded = base64.b64decode(stored_value.encode("ascii"))
        assert decoded == key

    def test_store_local_key_fallback_to_file(self):
        """Test fallback to file when keyring unavailable."""
        key = generate_key()

        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / "local.key"

            with patch(
                "pytodo_qt.crypto.keyring_storage._get_keyring",
                side_effect=KeyringUnavailableError("Not available"),
            ):
                with patch(
                    "pytodo_qt.crypto.keyring_storage._get_local_key_file_path",
                    return_value=key_file,
                ):
                    store_local_encryption_key(key)

            assert key_file.exists()
            with open(key_file, "rb") as f:
                assert f.read() == key

    def test_load_local_key_success(self):
        """Test successful local key loading."""
        key = generate_key()
        encoded = base64.b64encode(key).decode("ascii")

        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = encoded

        with patch("pytodo_qt.crypto.keyring_storage._get_keyring", return_value=mock_keyring):
            result = load_local_encryption_key()

        assert result == key

    def test_load_local_key_not_found(self):
        """Test loading when key doesn't exist."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = None

        with patch("pytodo_qt.crypto.keyring_storage._get_keyring", return_value=mock_keyring):
            result = load_local_encryption_key()

        assert result is None

    def test_load_local_key_fallback_to_file(self):
        """Test fallback to file when keyring unavailable."""
        key = generate_key()

        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / "local.key"
            with open(key_file, "wb") as f:
                f.write(key)

            with patch(
                "pytodo_qt.crypto.keyring_storage._get_keyring",
                side_effect=KeyringUnavailableError("Not available"),
            ):
                with patch(
                    "pytodo_qt.crypto.keyring_storage._get_local_key_file_path",
                    return_value=key_file,
                ):
                    result = load_local_encryption_key()

            assert result == key

    def test_get_or_create_local_key_existing(self):
        """Test getting existing local key."""
        key = generate_key()
        encoded = base64.b64encode(key).decode("ascii")

        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = encoded

        with patch("pytodo_qt.crypto.keyring_storage._get_keyring", return_value=mock_keyring):
            result = get_or_create_local_key()

        assert result == key

    def test_get_or_create_local_key_new(self):
        """Test creating new local key when none exists."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = None

        with patch("pytodo_qt.crypto.keyring_storage._get_keyring", return_value=mock_keyring):
            result = get_or_create_local_key()

        assert result is not None
        assert len(result) == 32
        mock_keyring.set_password.assert_called_once()


class TestLocalKeyFile:
    """Tests for local key file operations."""

    def test_store_local_key_file(self):
        """Test storing key to file."""
        key = generate_key()

        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / "local.key"

            with patch(
                "pytodo_qt.crypto.keyring_storage._get_local_key_file_path",
                return_value=key_file,
            ):
                _store_local_key_file(key)

            assert key_file.exists()
            mode = key_file.stat().st_mode & 0o777
            assert mode == 0o600
            with open(key_file, "rb") as f:
                assert f.read() == key

    def test_load_local_key_file_existing(self):
        """Test loading key from file."""
        key = generate_key()

        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / "local.key"
            with open(key_file, "wb") as f:
                f.write(key)

            with patch(
                "pytodo_qt.crypto.keyring_storage._get_local_key_file_path",
                return_value=key_file,
            ):
                result = _load_local_key_file()

            assert result == key

    def test_load_local_key_file_not_found(self):
        """Test loading when file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / "nonexistent.key"

            with patch(
                "pytodo_qt.crypto.keyring_storage._get_local_key_file_path",
                return_value=key_file,
            ):
                result = _load_local_key_file()

            assert result is None
