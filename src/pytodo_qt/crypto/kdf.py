"""kdf.py

Key derivation functions using Argon2id.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..core.logger import Logger

logger = Logger(__name__)


# Argon2id parameters - these provide strong security for password-based keys
ARGON2_TIME_COST = 3  # Number of iterations
ARGON2_MEMORY_COST = 65536  # 64 MB memory
ARGON2_PARALLELISM = 4  # Number of parallel threads
ARGON2_HASH_LEN = 32  # Output key length (256 bits)
ARGON2_SALT_LEN = 16  # Salt length


@dataclass
class DerivedKey:
    """Container for a derived key and its salt."""

    key: bytes
    salt: bytes


def derive_key_argon2(password: str, salt: bytes | None = None) -> DerivedKey:
    """Derive a 256-bit key from a password using Argon2id.

    Argon2id is the recommended algorithm for password hashing,
    providing resistance to both GPU and side-channel attacks.

    Args:
        password: User password
        salt: Optional salt (random bytes generated if not provided)

    Returns:
        DerivedKey containing the derived key and salt
    """
    # Import argon2-cffi for Argon2id
    try:
        from argon2.low_level import Type, hash_secret_raw
    except ImportError:
        # Fallback to PBKDF2 if argon2-cffi not available
        logger.log.warning("argon2-cffi not available, falling back to PBKDF2")
        return _derive_key_pbkdf2_fallback(password, salt)

    if salt is None:
        salt = os.urandom(ARGON2_SALT_LEN)

    key = hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        parallelism=ARGON2_PARALLELISM,
        hash_len=ARGON2_HASH_LEN,
        type=Type.ID,  # Argon2id
    )

    logger.log.info("Derived key using Argon2id")
    return DerivedKey(key=key, salt=salt)


def _derive_key_pbkdf2_fallback(password: str, salt: bytes | None = None) -> DerivedKey:
    """Fallback key derivation using PBKDF2 if Argon2 is unavailable."""
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    if salt is None:
        salt = os.urandom(ARGON2_SALT_LEN)

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=ARGON2_HASH_LEN,
        salt=salt,
        iterations=600000,  # OWASP recommendation for PBKDF2-SHA256
    )
    key = kdf.derive(password.encode("utf-8"))

    logger.log.warning("Derived key using PBKDF2 fallback (Argon2 preferred)")
    return DerivedKey(key=key, salt=salt)


def derive_session_key(shared_secret: bytes, info: bytes, length: int = 32) -> bytes:
    """Derive a session key from a shared secret using HKDF.

    This is used to derive encryption keys from X25519 key exchange results.

    Args:
        shared_secret: Raw shared secret from key exchange
        info: Context info to bind the key to a specific purpose
        length: Desired key length in bytes (default 32 for AES-256)

    Returns:
        Derived key bytes
    """
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=None,  # Using info for domain separation instead
        info=info,
    )
    key = hkdf.derive(shared_secret)
    logger.log.info("Derived session key using HKDF")
    return key


def derive_key_pair_from_session(shared_secret: bytes, session_id: bytes) -> tuple[bytes, bytes]:
    """Derive separate encryption and authentication keys from a session.

    Uses HKDF with different info strings to derive independent keys.

    Args:
        shared_secret: Raw shared secret from key exchange
        session_id: Unique session identifier

    Returns:
        Tuple of (encryption_key, auth_key), each 32 bytes
    """
    enc_key = derive_session_key(shared_secret, b"pytodo-encrypt-" + session_id, 32)
    auth_key = derive_session_key(shared_secret, b"pytodo-auth-" + session_id, 32)
    return enc_key, auth_key
