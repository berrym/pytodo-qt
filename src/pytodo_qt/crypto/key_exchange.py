"""key_exchange.py

Ed25519 identity keys and X25519 ephemeral key exchange.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)

from ..core.logger import Logger
from .kdf import derive_session_key

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


class KeyExchangeError(Exception):
    """Error during key exchange."""

    pass


class SignatureVerificationError(KeyExchangeError):
    """Signature verification failed."""

    pass


@dataclass
class IdentityKeyPair:
    """Ed25519 identity keypair for signing and verification."""

    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey

    @classmethod
    def generate(cls) -> IdentityKeyPair:
        """Generate a new Ed25519 identity keypair."""
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        logger.log.info("Generated new Ed25519 identity keypair")
        return cls(private_key=private_key, public_key=public_key)

    @classmethod
    def from_private_bytes(cls, data: bytes) -> IdentityKeyPair:
        """Reconstruct keypair from private key bytes."""
        private_key = Ed25519PrivateKey.from_private_bytes(data)
        public_key = private_key.public_key()
        return cls(private_key=private_key, public_key=public_key)

    def private_bytes(self) -> bytes:
        """Get raw private key bytes (32 bytes)."""
        return self.private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def public_bytes(self) -> bytes:
        """Get raw public key bytes (32 bytes)."""
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def fingerprint(self) -> str:
        """Get a human-readable fingerprint of the public key."""
        import hashlib

        digest = hashlib.sha256(self.public_bytes()).hexdigest()
        # Format as groups of 4 characters
        return ":".join(digest[i : i + 4] for i in range(0, 32, 4))

    def sign(self, message: bytes) -> bytes:
        """Sign a message with the identity key."""
        return self.private_key.sign(message)

    def verify(self, signature: bytes, message: bytes) -> bool:
        """Verify a signature with the public key."""
        try:
            self.public_key.verify(signature, message)
            return True
        except InvalidSignature:
            return False


@dataclass
class EphemeralKeyPair:
    """X25519 ephemeral keypair for key exchange."""

    private_key: X25519PrivateKey
    public_key: X25519PublicKey

    @classmethod
    def generate(cls) -> EphemeralKeyPair:
        """Generate a new X25519 ephemeral keypair."""
        private_key = X25519PrivateKey.generate()
        public_key = private_key.public_key()
        logger.log.info("Generated X25519 ephemeral keypair")
        return cls(private_key=private_key, public_key=public_key)

    def public_bytes(self) -> bytes:
        """Get raw public key bytes (32 bytes)."""
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def exchange(self, peer_public_key: X25519PublicKey) -> bytes:
        """Perform X25519 key exchange.

        Args:
            peer_public_key: The peer's X25519 public key

        Returns:
            32-byte shared secret
        """
        return self.private_key.exchange(peer_public_key)


@dataclass
class SignedKeyBundle:
    """X25519 public key signed with Ed25519 identity key."""

    ephemeral_public: bytes  # X25519 public key bytes
    identity_public: bytes  # Ed25519 public key bytes
    signature: bytes  # Ed25519 signature of ephemeral key

    def to_bytes(self) -> bytes:
        """Serialize to bytes."""
        return self.ephemeral_public + self.identity_public + self.signature

    @classmethod
    def from_bytes(cls, data: bytes) -> SignedKeyBundle:
        """Deserialize from bytes."""
        if len(data) != 32 + 32 + 64:
            raise KeyExchangeError(f"Invalid key bundle size: {len(data)}")
        return cls(
            ephemeral_public=data[:32],
            identity_public=data[32:64],
            signature=data[64:],
        )

    def verify(self) -> bool:
        """Verify the signature on the ephemeral key.

        Returns:
            True if signature is valid
        """
        try:
            identity_key = Ed25519PublicKey.from_public_bytes(self.identity_public)
            identity_key.verify(self.signature, self.ephemeral_public)
            return True
        except InvalidSignature:
            return False
        except Exception as e:
            logger.log.exception("Key bundle verification error: %s", e)
            return False


def create_signed_key_bundle(
    identity: IdentityKeyPair, ephemeral: EphemeralKeyPair
) -> SignedKeyBundle:
    """Create a signed key bundle for key exchange.

    The ephemeral X25519 public key is signed with the Ed25519 identity key,
    preventing MITM attacks by binding the ephemeral key to the identity.

    Args:
        identity: Long-term Ed25519 identity keypair
        ephemeral: Session X25519 ephemeral keypair

    Returns:
        SignedKeyBundle ready to send to peer
    """
    ephemeral_bytes = ephemeral.public_bytes()
    signature = identity.sign(ephemeral_bytes)

    return SignedKeyBundle(
        ephemeral_public=ephemeral_bytes,
        identity_public=identity.public_bytes(),
        signature=signature,
    )


@dataclass
class SessionKeys:
    """Symmetric keys derived from key exchange."""

    encrypt_key: bytes  # For encrypting messages to peer
    decrypt_key: bytes  # For decrypting messages from peer
    session_id: bytes  # Unique session identifier


def derive_session_keys(
    shared_secret: bytes, our_public: bytes, their_public: bytes, is_initiator: bool
) -> SessionKeys:
    """Derive session keys from X25519 shared secret.

    Uses HKDF with role-specific info to derive separate encryption
    and decryption keys. The initiator and responder roles ensure
    that both parties derive matching key pairs.

    Args:
        shared_secret: Raw X25519 shared secret
        our_public: Our X25519 public key bytes
        their_public: Peer's X25519 public key bytes
        is_initiator: True if we initiated the connection

    Returns:
        SessionKeys with derived encryption/decryption keys
    """
    # Create session ID from both public keys (sorted for determinism)
    keys_combined = b"".join(sorted([our_public, their_public]))
    session_id = derive_session_key(keys_combined, b"pytodo-session-id", 16)

    # Derive directional keys
    # Initiator encrypts with key_a, decrypts with key_b
    # Responder encrypts with key_b, decrypts with key_a
    key_a = derive_session_key(shared_secret, b"pytodo-key-initiator-" + session_id, 32)
    key_b = derive_session_key(shared_secret, b"pytodo-key-responder-" + session_id, 32)

    if is_initiator:
        return SessionKeys(
            encrypt_key=key_a,
            decrypt_key=key_b,
            session_id=session_id,
        )
    else:
        return SessionKeys(
            encrypt_key=key_b,
            decrypt_key=key_a,
            session_id=session_id,
        )


def perform_key_exchange(
    our_identity: IdentityKeyPair, peer_bundle: SignedKeyBundle, is_initiator: bool
) -> tuple[SessionKeys, EphemeralKeyPair]:
    """Perform authenticated key exchange.

    Verifies the peer's signed key bundle and performs X25519 exchange.

    Args:
        our_identity: Our Ed25519 identity keypair
        peer_bundle: Peer's signed key bundle
        is_initiator: True if we initiated the connection

    Returns:
        Tuple of (session_keys, our_ephemeral_keypair)

    Raises:
        SignatureVerificationError: If peer's signature is invalid
    """
    # Verify peer's signature
    if not peer_bundle.verify():
        raise SignatureVerificationError("Peer's key bundle signature is invalid")

    # Generate our ephemeral key
    our_ephemeral = EphemeralKeyPair.generate()

    # Load peer's ephemeral public key
    peer_ephemeral_public = X25519PublicKey.from_public_bytes(peer_bundle.ephemeral_public)

    # Perform X25519 exchange
    shared_secret = our_ephemeral.exchange(peer_ephemeral_public)

    # Derive session keys
    session_keys = derive_session_keys(
        shared_secret,
        our_ephemeral.public_bytes(),
        peer_bundle.ephemeral_public,
        is_initiator,
    )

    logger.log.info("Key exchange completed successfully")
    return session_keys, our_ephemeral
