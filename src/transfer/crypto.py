from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_HKDF_INFO = b"transfer-file-encryption"
_EPHEMERAL_KEY_LEN = 32
_NONCE_LEN = 12
_HEADER_LEN = _EPHEMERAL_KEY_LEN + _NONCE_LEN


def generate_keypair() -> tuple[bytes, bytes]:
    private_key = X25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private_bytes, public_bytes


def _derive_key(shared_secret: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=_HKDF_INFO,
    ).derive(shared_secret)


def encrypt(plaintext: bytes, recipient_public_key_bytes: bytes) -> bytes:
    recipient_public_key = X25519PublicKey.from_public_bytes(
        recipient_public_key_bytes
    )
    ephemeral_private = X25519PrivateKey.generate()
    ephemeral_public = ephemeral_private.public_key()
    shared_secret = ephemeral_private.exchange(recipient_public_key)
    derived_key = _derive_key(shared_secret)
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = ChaCha20Poly1305(derived_key).encrypt(nonce, plaintext, None)
    ephemeral_public_bytes = ephemeral_public.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return ephemeral_public_bytes + nonce + ciphertext


def decrypt(data: bytes, private_key_bytes: bytes) -> bytes:
    if len(data) < _HEADER_LEN:
        msg = f"encrypted data too short ({len(data)} bytes)"
        raise ValueError(msg)
    ephemeral_public_bytes = data[:_EPHEMERAL_KEY_LEN]
    nonce = data[_EPHEMERAL_KEY_LEN:_HEADER_LEN]
    ciphertext = data[_HEADER_LEN:]
    private_key = X25519PrivateKey.from_private_bytes(private_key_bytes)
    ephemeral_public = X25519PublicKey.from_public_bytes(ephemeral_public_bytes)
    shared_secret = private_key.exchange(ephemeral_public)
    derived_key = _derive_key(shared_secret)
    return ChaCha20Poly1305(derived_key).decrypt(nonce, ciphertext, None)


def encode_key(key_bytes: bytes) -> str:
    return base64.urlsafe_b64encode(key_bytes).decode("ascii")


def decode_key(key_str: str) -> bytes:
    return base64.urlsafe_b64decode(key_str)
