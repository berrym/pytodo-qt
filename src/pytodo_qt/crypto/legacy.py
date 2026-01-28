"""legacy.py

Read-only AES-CBC decryption for migrating v0.2.x encrypted data.
This module is intentionally read-only to support migration.
"""

from __future__ import annotations

import base64
import hashlib
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from ..core.logger import Logger

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


class LegacyAESCipher:
    """Read-only AES-256-CBC decryption for v0.2.x data migration.

    This maintains compatibility with the old pycryptodomex-based
    AESCipher class for decrypting existing encrypted data.
    """

    BLOCK_SIZE = 16  # AES block size in bytes

    def __init__(self, key: str) -> None:
        """Initialize with a passphrase.

        The passphrase is hashed with SHA-256 to create a 256-bit key,
        matching the original implementation.

        Args:
            key: Passphrase string
        """
        self.key = hashlib.sha256(key.encode("utf-8")).digest()

    def decrypt(self, encrypted_data: bytes) -> bytes | None:
        """Decrypt AES-256-CBC encrypted data.

        Args:
            encrypted_data: Base64-encoded encrypted data with IV prefix

        Returns:
            Decrypted bytes, or None on error
        """
        try:
            logger.log.info("LegacyAESCipher: decrypting data")
            decoded_data = base64.b64decode(encrypted_data)
            iv = decoded_data[: self.BLOCK_SIZE]
            ciphertext = decoded_data[self.BLOCK_SIZE :]

            cipher = Cipher(algorithms.AES(self.key), modes.CBC(iv))
            decryptor = cipher.decryptor()
            padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()

            # Remove PKCS7 padding
            unpadder = PKCS7(128).unpadder()
            plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()

            return plaintext
        except Exception as e:
            logger.log.exception("LegacyAESCipher decryption error: %s", e)
            return None


def decrypt_legacy_data(encrypted_data: bytes, key: str) -> bytes | None:
    """Convenience function to decrypt legacy AES-CBC data.

    Args:
        encrypted_data: Base64-encoded encrypted data
        key: Passphrase used for encryption

    Returns:
        Decrypted bytes, or None on error
    """
    cipher = LegacyAESCipher(key)
    return cipher.decrypt(encrypted_data)
