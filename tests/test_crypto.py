"""Tests for cryptography modules."""

import pytest

from pytodo_qt.crypto import (
    AESGCMCipher,
    DecryptionError,
    decrypt,
    encrypt,
    generate_key,
)
from pytodo_qt.crypto.kdf import derive_session_key
from pytodo_qt.crypto.key_exchange import (
    EphemeralKeyPair,
    IdentityKeyPair,
    create_signed_key_bundle,
    derive_session_keys,
)


class TestAESGCM:
    """Tests for AES-256-GCM encryption."""

    def test_encrypt_decrypt(self):
        """Test basic encryption and decryption."""
        key = generate_key()
        cipher = AESGCMCipher(key)

        plaintext = b"Hello, World!"
        encrypted = cipher.encrypt(plaintext)
        decrypted = cipher.decrypt(encrypted)

        assert decrypted == plaintext

    def test_encrypt_decrypt_bytes(self):
        """Test convenience byte methods."""
        key = generate_key()

        plaintext = b"Test message"
        ciphertext = encrypt(key, plaintext)
        decrypted = decrypt(key, ciphertext)

        assert decrypted == plaintext

    def test_associated_data(self):
        """Test encryption with associated data."""
        key = generate_key()
        cipher = AESGCMCipher(key)

        plaintext = b"Secret data"
        aad = b"header information"

        encrypted = cipher.encrypt(plaintext, aad)
        decrypted = cipher.decrypt(encrypted, aad)

        assert decrypted == plaintext

    def test_wrong_key_fails(self):
        """Test that wrong key fails decryption."""
        key1 = generate_key()
        key2 = generate_key()

        plaintext = b"Secret"
        ciphertext = encrypt(key1, plaintext)

        with pytest.raises(DecryptionError):
            decrypt(key2, ciphertext)

    def test_wrong_aad_fails(self):
        """Test that wrong AAD fails decryption."""
        key = generate_key()
        cipher = AESGCMCipher(key)

        plaintext = b"Secret"
        aad1 = b"correct"
        aad2 = b"wrong"

        encrypted = cipher.encrypt(plaintext, aad1)

        with pytest.raises(DecryptionError):
            cipher.decrypt(encrypted, aad2)

    def test_tampered_ciphertext_fails(self):
        """Test that tampered ciphertext fails decryption."""
        key = generate_key()

        plaintext = b"Secret data"
        ciphertext = encrypt(key, plaintext)

        # Tamper with ciphertext
        tampered = bytearray(ciphertext)
        tampered[20] ^= 0xFF  # Flip bits
        tampered = bytes(tampered)

        with pytest.raises(DecryptionError):
            decrypt(key, tampered)

    def test_invalid_key_size(self):
        """Test that invalid key size raises error."""
        with pytest.raises(ValueError):
            AESGCMCipher(b"too short")

    def test_generate_key_length(self):
        """Test that generated keys are correct length."""
        key = generate_key()
        assert len(key) == 32


class TestKeyExchange:
    """Tests for Ed25519/X25519 key exchange."""

    def test_identity_keypair_generation(self):
        """Test identity keypair generation."""
        keypair = IdentityKeyPair.generate()

        assert len(keypair.public_bytes()) == 32
        assert len(keypair.private_bytes()) == 32

    def test_identity_keypair_serialization(self):
        """Test identity keypair serialization."""
        keypair = IdentityKeyPair.generate()
        private_bytes = keypair.private_bytes()

        # Reconstruct from bytes
        keypair2 = IdentityKeyPair.from_private_bytes(private_bytes)

        assert keypair.public_bytes() == keypair2.public_bytes()

    def test_identity_sign_verify(self):
        """Test signing and verification."""
        keypair = IdentityKeyPair.generate()
        message = b"Test message"

        signature = keypair.sign(message)
        assert keypair.verify(signature, message) is True

        # Wrong message should fail
        assert keypair.verify(signature, b"Wrong message") is False

    def test_identity_fingerprint(self):
        """Test fingerprint generation."""
        keypair = IdentityKeyPair.generate()
        fingerprint = keypair.fingerprint()

        # Fingerprint should be formatted as hex groups
        assert ":" in fingerprint
        parts = fingerprint.split(":")
        assert len(parts) == 8  # 32 chars / 4 = 8 groups

    def test_ephemeral_keypair(self):
        """Test ephemeral keypair generation."""
        keypair = EphemeralKeyPair.generate()
        assert len(keypair.public_bytes()) == 32

    def test_signed_key_bundle(self):
        """Test creating and verifying signed key bundle."""
        identity = IdentityKeyPair.generate()
        ephemeral = EphemeralKeyPair.generate()

        bundle = create_signed_key_bundle(identity, ephemeral)

        assert bundle.verify() is True
        assert len(bundle.to_bytes()) == 32 + 32 + 64  # ephemeral + identity + signature

    def test_key_exchange_session_keys(self):
        """Test that key exchange produces matching session keys."""
        # Simulate client and server
        _client_identity = IdentityKeyPair.generate()  # noqa: F841
        _server_identity = IdentityKeyPair.generate()  # noqa: F841

        client_ephemeral = EphemeralKeyPair.generate()
        server_ephemeral = EphemeralKeyPair.generate()

        # Perform exchange
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey

        server_pub = X25519PublicKey.from_public_bytes(server_ephemeral.public_bytes())
        client_pub = X25519PublicKey.from_public_bytes(client_ephemeral.public_bytes())

        client_shared = client_ephemeral.exchange(server_pub)
        server_shared = server_ephemeral.exchange(client_pub)

        # Shared secrets should match
        assert client_shared == server_shared

        # Derive session keys
        client_keys = derive_session_keys(
            client_shared,
            client_ephemeral.public_bytes(),
            server_ephemeral.public_bytes(),
            is_initiator=True,
        )
        server_keys = derive_session_keys(
            server_shared,
            server_ephemeral.public_bytes(),
            client_ephemeral.public_bytes(),
            is_initiator=False,
        )

        # Client encrypt key should match server decrypt key and vice versa
        assert client_keys.encrypt_key == server_keys.decrypt_key
        assert client_keys.decrypt_key == server_keys.encrypt_key
        assert client_keys.session_id == server_keys.session_id


class TestKDF:
    """Tests for key derivation functions."""

    def test_derive_session_key(self):
        """Test session key derivation."""
        shared_secret = b"shared_secret_bytes_here_32bytes"
        info = b"test-info"

        key = derive_session_key(shared_secret, info, 32)

        assert len(key) == 32

    def test_different_info_different_keys(self):
        """Test that different info produces different keys."""
        shared_secret = b"shared_secret_bytes_here_32bytes"

        key1 = derive_session_key(shared_secret, b"info1", 32)
        key2 = derive_session_key(shared_secret, b"info2", 32)

        assert key1 != key2
