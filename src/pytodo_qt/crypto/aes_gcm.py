"""aes_gcm.py

AES-256-GCM authenticated encryption implementation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..core.logger import Logger

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


# Constants
NONCE_SIZE = 12  # 96-bit nonce (recommended for GCM)
KEY_SIZE = 32  # 256-bit key
TAG_SIZE = 16  # 128-bit authentication tag (appended to ciphertext)


class CryptoError(Exception):
    """Base exception for cryptographic errors."""

    pass


class EncryptionError(CryptoError):
    """Raised when encryption fails."""

    pass


class DecryptionError(CryptoError):
    """Raised when decryption fails (including authentication failure)."""

    pass


@dataclass
class EncryptedMessage:
    """Container for an encrypted message with nonce."""

    nonce: bytes
    ciphertext: bytes  # Includes authentication tag

    def to_bytes(self) -> bytes:
        """Serialize to bytes format: nonce || ciphertext."""
        return self.nonce + self.ciphertext

    @classmethod
    def from_bytes(cls, data: bytes) -> EncryptedMessage:
        """Deserialize from bytes format."""
        if len(data) < NONCE_SIZE + TAG_SIZE:
            raise DecryptionError("Message too short")
        return cls(
            nonce=data[:NONCE_SIZE],
            ciphertext=data[NONCE_SIZE:],
        )


class AESGCMCipher:
    """AES-256-GCM authenticated encryption.

    Provides confidentiality and integrity protection using
    the Galois/Counter Mode (GCM) of AES-256.

    Key features:
    - Random 96-bit nonce per encryption
    - 128-bit authentication tag
    - Associated data (AAD) support for protocol integrity
    """

    def __init__(self, key: bytes) -> None:
        """Initialize cipher with a 256-bit key.

        Args:
            key: 32-byte (256-bit) encryption key

        Raises:
            ValueError: If key is not 32 bytes
        """
        if len(key) != KEY_SIZE:
            raise ValueError(f"Key must be {KEY_SIZE} bytes, got {len(key)}")
        self._aesgcm = AESGCM(key)
        logger.log.info("Initialized AES-256-GCM cipher")

    def encrypt(self, plaintext: bytes, associated_data: bytes | None = None) -> EncryptedMessage:
        """Encrypt data with authentication.

        Args:
            plaintext: Data to encrypt
            associated_data: Optional authenticated but unencrypted data

        Returns:
            EncryptedMessage containing nonce and ciphertext

        Raises:
            EncryptionError: If encryption fails
        """
        try:
            nonce = os.urandom(NONCE_SIZE)
            ciphertext = self._aesgcm.encrypt(nonce, plaintext, associated_data)
            logger.log.info("Encrypted %d bytes", len(plaintext))
            return EncryptedMessage(nonce=nonce, ciphertext=ciphertext)
        except Exception as e:
            logger.log.exception("Encryption error: %s", e)
            raise EncryptionError(f"Encryption failed: {e}") from e

    def decrypt(self, message: EncryptedMessage, associated_data: bytes | None = None) -> bytes:
        """Decrypt and verify data.

        Args:
            message: Encrypted message with nonce
            associated_data: Optional authenticated data (must match encryption)

        Returns:
            Decrypted plaintext

        Raises:
            DecryptionError: If decryption or authentication fails
        """
        try:
            plaintext = self._aesgcm.decrypt(message.nonce, message.ciphertext, associated_data)
            logger.log.info("Decrypted %d bytes", len(plaintext))
            return plaintext
        except Exception as e:
            logger.log.exception("Decryption error: %s", e)
            raise DecryptionError(f"Decryption failed: {e}") from e

    def encrypt_bytes(self, plaintext: bytes, associated_data: bytes | None = None) -> bytes:
        """Encrypt and return serialized bytes.

        Convenience method that returns nonce || ciphertext.

        Args:
            plaintext: Data to encrypt
            associated_data: Optional authenticated data

        Returns:
            Serialized encrypted bytes
        """
        msg = self.encrypt(plaintext, associated_data)
        return msg.to_bytes()

    def decrypt_bytes(self, data: bytes, associated_data: bytes | None = None) -> bytes:
        """Decrypt from serialized bytes.

        Convenience method that accepts nonce || ciphertext.

        Args:
            data: Serialized encrypted bytes
            associated_data: Optional authenticated data

        Returns:
            Decrypted plaintext
        """
        msg = EncryptedMessage.from_bytes(data)
        return self.decrypt(msg, associated_data)


def encrypt(key: bytes, plaintext: bytes, aad: bytes | None = None) -> bytes:
    """Encrypt data with AES-256-GCM.

    Args:
        key: 32-byte encryption key
        plaintext: Data to encrypt
        aad: Optional associated data

    Returns:
        Serialized encrypted bytes (nonce || ciphertext || tag)
    """
    cipher = AESGCMCipher(key)
    return cipher.encrypt_bytes(plaintext, aad)


def decrypt(key: bytes, ciphertext: bytes, aad: bytes | None = None) -> bytes:
    """Decrypt AES-256-GCM encrypted data.

    Args:
        key: 32-byte encryption key
        ciphertext: Serialized encrypted bytes
        aad: Optional associated data

    Returns:
        Decrypted plaintext
    """
    cipher = AESGCMCipher(key)
    return cipher.decrypt_bytes(ciphertext, aad)


def generate_key() -> bytes:
    """Generate a random 256-bit key.

    Returns:
        32 bytes of cryptographically secure random data
    """
    return os.urandom(KEY_SIZE)
