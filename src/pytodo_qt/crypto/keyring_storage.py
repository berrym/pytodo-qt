"""keyring_storage.py

Secure storage of cryptographic keys using system keyring.
Cross-platform support via the keyring library:
- Linux: SecretService API (GNOME Keyring, KDE Wallet, keepassxc)
- macOS: macOS Keychain
- Windows: Windows Credential Locker
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..core.logger import Logger
from .aes_gcm import generate_key
from .key_exchange import IdentityKeyPair

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


# Keyring service and key names
KEYRING_SERVICE = "pytodo-qt"
KEYRING_IDENTITY_KEY = "identity-private-key"
KEYRING_ENCRYPTION_KEY = "local-encryption-key"


class KeyringError(Exception):
    """Error accessing system keyring."""

    pass


class KeyringUnavailableError(KeyringError):
    """System keyring is not available."""

    pass


@dataclass
class StoredIdentity:
    """Container for identity stored in keyring."""

    keypair: IdentityKeyPair
    fingerprint: str


def _get_keyring():
    """Get the keyring module, raising helpful error if unavailable."""
    try:
        import keyring

        # Test if a backend is available
        backend = keyring.get_keyring()
        logger.log.info("Using keyring backend: %s", type(backend).__name__)
        return keyring
    except Exception as e:
        logger.log.warning("Keyring not available: %s", e)
        raise KeyringUnavailableError(
            "System keyring not available. Install a keyring backend or "
            "check your system's secret service."
        ) from e


def store_identity(keypair: IdentityKeyPair) -> str:
    """Store identity keypair in system keyring.

    Args:
        keypair: Ed25519 identity keypair to store

    Returns:
        Fingerprint of the stored identity

    Raises:
        KeyringError: If storage fails
    """
    try:
        keyring = _get_keyring()
        private_bytes = keypair.private_bytes()
        # Base64 encode for keyring storage (some backends don't handle raw bytes)
        encoded = base64.b64encode(private_bytes).decode("ascii")
        keyring.set_password(KEYRING_SERVICE, KEYRING_IDENTITY_KEY, encoded)
        fingerprint = keypair.fingerprint()
        logger.log.info("Stored identity in keyring (fingerprint: %s)", fingerprint)
        return fingerprint
    except Exception as e:
        logger.log.exception("Failed to store identity in keyring: %s", e)
        raise KeyringError(f"Failed to store identity: {e}") from e


def load_identity() -> StoredIdentity | None:
    """Load identity keypair from system keyring.

    Returns:
        StoredIdentity if found, None if not stored

    Raises:
        KeyringError: If keyring access fails
    """
    try:
        keyring = _get_keyring()
        encoded = keyring.get_password(KEYRING_SERVICE, KEYRING_IDENTITY_KEY)

        if encoded is None:
            logger.log.info("No identity found in keyring")
            return None

        private_bytes = base64.b64decode(encoded.encode("ascii"))
        keypair = IdentityKeyPair.from_private_bytes(private_bytes)
        fingerprint = keypair.fingerprint()
        logger.log.info("Loaded identity from keyring (fingerprint: %s)", fingerprint)
        return StoredIdentity(keypair=keypair, fingerprint=fingerprint)
    except KeyringUnavailableError:
        raise
    except Exception as e:
        logger.log.exception("Failed to load identity from keyring: %s", e)
        raise KeyringError(f"Failed to load identity: {e}") from e


def delete_identity() -> bool:
    """Delete identity from system keyring.

    Returns:
        True if deleted, False if not found
    """
    try:
        keyring = _get_keyring()
        keyring.delete_password(KEYRING_SERVICE, KEYRING_IDENTITY_KEY)
        logger.log.info("Deleted identity from keyring")
        return True
    except Exception as e:
        logger.log.warning("Failed to delete identity: %s", e)
        return False


def get_or_create_identity() -> StoredIdentity:
    """Get existing identity or create a new one.

    Returns:
        StoredIdentity (existing or newly created)
    """
    try:
        existing = load_identity()
        if existing is not None:
            return existing
    except KeyringUnavailableError:
        # Fall back to file-based storage
        return _get_or_create_identity_file()
    except KeyringError:
        pass

    # Generate new identity
    keypair = IdentityKeyPair.generate()
    try:
        fingerprint = store_identity(keypair)
        return StoredIdentity(keypair=keypair, fingerprint=fingerprint)
    except KeyringError:
        # Fall back to file-based storage
        return _store_identity_file(keypair)


# File-based fallback storage


def _get_identity_file_path() -> Path:
    """Get path to file-based identity storage."""
    from ..core import paths

    return paths.get_data_dir() / "identity.key"


def _get_or_create_identity_file() -> StoredIdentity:
    """File-based identity storage fallback."""
    identity_file = _get_identity_file_path()

    if identity_file.exists():
        try:
            with open(identity_file, "rb") as f:
                private_bytes = f.read()
            keypair = IdentityKeyPair.from_private_bytes(private_bytes)
            fingerprint = keypair.fingerprint()
            logger.log.info("Loaded identity from file (fingerprint: %s)", fingerprint)
            return StoredIdentity(keypair=keypair, fingerprint=fingerprint)
        except Exception as e:
            logger.log.exception("Failed to load identity file: %s", e)

    # Generate new identity
    keypair = IdentityKeyPair.generate()
    return _store_identity_file(keypair)


def _store_identity_file(keypair: IdentityKeyPair) -> StoredIdentity:
    """Store identity to file (fallback when keyring unavailable)."""
    identity_file = _get_identity_file_path()

    try:
        # Write with restrictive permissions
        private_bytes = keypair.private_bytes()
        identity_file.touch(mode=0o600)
        with open(identity_file, "wb") as f:
            f.write(private_bytes)
        os.chmod(identity_file, 0o600)

        fingerprint = keypair.fingerprint()
        logger.log.warning(
            "Stored identity in file (keyring unavailable). Fingerprint: %s", fingerprint
        )
        return StoredIdentity(keypair=keypair, fingerprint=fingerprint)
    except Exception as e:
        logger.log.exception("Failed to store identity file: %s", e)
        raise KeyringError(f"Failed to store identity: {e}") from e


def store_local_encryption_key(key: bytes) -> None:
    """Store local encryption key for database encryption.

    Args:
        key: 32-byte encryption key
    """
    try:
        keyring = _get_keyring()
        encoded = base64.b64encode(key).decode("ascii")
        keyring.set_password(KEYRING_SERVICE, KEYRING_ENCRYPTION_KEY, encoded)
        logger.log.info("Stored local encryption key in keyring")
    except KeyringUnavailableError:
        _store_local_key_file(key)
    except Exception as e:
        logger.log.exception("Failed to store local key: %s", e)
        raise KeyringError(f"Failed to store local key: {e}") from e


def load_local_encryption_key() -> bytes | None:
    """Load local encryption key from keyring.

    Returns:
        32-byte encryption key, or None if not stored
    """
    try:
        keyring = _get_keyring()
        encoded = keyring.get_password(KEYRING_SERVICE, KEYRING_ENCRYPTION_KEY)

        if encoded is None:
            return None

        return base64.b64decode(encoded.encode("ascii"))
    except KeyringUnavailableError:
        return _load_local_key_file()
    except Exception as e:
        logger.log.exception("Failed to load local key: %s", e)
        return None


def get_or_create_local_key() -> bytes:
    """Get existing local encryption key or create a new one."""
    key = load_local_encryption_key()
    if key is not None:
        return key

    key = generate_key()
    store_local_encryption_key(key)
    return key


def _get_local_key_file_path() -> Path:
    """Get path to file-based local key storage."""
    from ..core import paths

    return paths.get_data_dir() / "local.key"


def _store_local_key_file(key: bytes) -> None:
    """Store local key to file fallback."""
    key_file = _get_local_key_file_path()
    key_file.touch(mode=0o600)
    with open(key_file, "wb") as f:
        f.write(key)
    os.chmod(key_file, 0o600)
    logger.log.warning("Stored local key in file (keyring unavailable)")


def _load_local_key_file() -> bytes | None:
    """Load local key from file fallback."""
    key_file = _get_local_key_file_path()
    if not key_file.exists():
        return None
    try:
        with open(key_file, "rb") as f:
            return f.read()
    except Exception as e:
        logger.log.exception("Failed to load local key file: %s", e)
        return None
