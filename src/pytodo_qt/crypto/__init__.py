"""Cryptography module for pytodo-qt.

Provides:
- AES-256-GCM authenticated encryption
- Ed25519/X25519 key exchange
- Argon2id key derivation
- Secure keyring storage
- Legacy AES-CBC support for migration
"""

from .aes_gcm import (
    AESGCMCipher,
    CryptoError,
    DecryptionError,
    EncryptedMessage,
    EncryptionError,
    decrypt,
    encrypt,
    generate_key,
)
from .kdf import (
    DerivedKey,
    derive_key_argon2,
    derive_key_pair_from_session,
    derive_session_key,
)
from .key_exchange import (
    EphemeralKeyPair,
    IdentityKeyPair,
    KeyExchangeError,
    SessionKeys,
    SignatureVerificationError,
    SignedKeyBundle,
    create_signed_key_bundle,
    derive_session_keys,
    perform_key_exchange,
)
from .keyring_storage import (
    KeyringError,
    KeyringUnavailableError,
    StoredIdentity,
    delete_identity,
    get_or_create_identity,
    get_or_create_local_key,
    load_identity,
    load_local_encryption_key,
    store_identity,
    store_local_encryption_key,
)
from .legacy import LegacyAESCipher, decrypt_legacy_data

__all__ = [
    # AES-GCM
    "AESGCMCipher",
    "CryptoError",
    "DecryptionError",
    "EncryptedMessage",
    "EncryptionError",
    "decrypt",
    "encrypt",
    "generate_key",
    # Key exchange
    "EphemeralKeyPair",
    "IdentityKeyPair",
    "KeyExchangeError",
    "SessionKeys",
    "SignatureVerificationError",
    "SignedKeyBundle",
    "create_signed_key_bundle",
    "derive_session_keys",
    "perform_key_exchange",
    # Keyring storage
    "KeyringError",
    "KeyringUnavailableError",
    "StoredIdentity",
    "delete_identity",
    "get_or_create_identity",
    "get_or_create_local_key",
    "load_identity",
    "load_local_encryption_key",
    "store_identity",
    "store_local_encryption_key",
    # KDF
    "DerivedKey",
    "derive_key_argon2",
    "derive_key_pair_from_session",
    "derive_session_key",
    # Legacy
    "LegacyAESCipher",
    "decrypt_legacy_data",
]
