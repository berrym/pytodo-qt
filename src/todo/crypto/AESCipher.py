"""AESCipher.py

AES Cipher class for encrypting and decrypting string data.
"""

import base64
import hashlib

from Cryptodome.Cipher import AES
from Cryptodome.Random import get_random_bytes
from Cryptodome.Util.Padding import pad, unpad

from todo.core.Logger import Logger


logger = Logger(__name__)


def catch_value_error_exception(func):
    """Catch ValueError exceptions."""

    def wrapper(*args, **kwargs):
        """Wrap around func and catch ValueError exceptions."""
        try:
            result = func(*args, **kwargs)
            return result
        except ValueError as e:
            logger.log.exception(f"AESCipher error: {e}")
            return None

    return wrapper


class AESCipher:
    """Implement AES Cipher Block Chaining encryption and decryption."""

    def __init__(self, key: str) -> None:
        """Make a fixed sha256 bit length key."""
        self.key = hashlib.sha256(key.encode("utf-8")).digest()

    @catch_value_error_exception
    def encrypt(self, raw_data: str) -> bytes:
        """Encrypt raw data."""
        logger.log.info("AESCipher: Encrypting data")
        encoded_data = pad(raw_data.encode("utf-8"), AES.block_size)
        iv = get_random_bytes(AES.block_size)
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        return base64.b64encode(iv + cipher.encrypt(encoded_data))

    @catch_value_error_exception
    def decrypt(self, encrypted_data: bytes) -> bytes:
        """Decrypt encoded data."""
        logger.log.info("AESCipher: decrypting data")
        decoded_data = base64.b64decode(encrypted_data)
        iv = decoded_data[: AES.block_size]
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        return unpad(cipher.decrypt(decoded_data[AES.block_size :]), AES.block_size)
