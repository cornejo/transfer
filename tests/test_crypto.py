from __future__ import annotations

import pytest

from transfer.crypto import decrypt, encode_key, decode_key, encrypt, generate_keypair


class TestKeypair:
    def test_generate_returns_32_byte_keys(self) -> None:
        private, public = generate_keypair()
        assert len(private) == 32
        assert len(public) == 32

    def test_generate_produces_distinct_pairs(self) -> None:
        pair_a = generate_keypair()
        pair_b = generate_keypair()
        assert pair_a[0] != pair_b[0]
        assert pair_a[1] != pair_b[1]


class TestEncodeDecodeKey:
    def test_roundtrip(self) -> None:
        _, public = generate_keypair()
        encoded = encode_key(public)
        assert isinstance(encoded, str)
        assert decode_key(encoded) == public

    def test_encode_is_url_safe_base64(self) -> None:
        key = b"\xff" * 32
        encoded = encode_key(key)
        assert "+" not in encoded
        assert "/" not in encoded


class TestEncryptDecrypt:
    def test_roundtrip(self) -> None:
        private, public = generate_keypair()
        plaintext = b"hello world"
        ciphertext = encrypt(plaintext, public)
        assert decrypt(ciphertext, private) == plaintext

    def test_ciphertext_is_larger_than_plaintext(self) -> None:
        _, public = generate_keypair()
        plaintext = b"test"
        ciphertext = encrypt(plaintext, public)
        assert len(ciphertext) > len(plaintext)

    def test_different_ciphertext_each_time(self) -> None:
        _, public = generate_keypair()
        plaintext = b"same input"
        c1 = encrypt(plaintext, public)
        c2 = encrypt(plaintext, public)
        assert c1 != c2

    def test_wrong_key_fails(self) -> None:
        _, public = generate_keypair()
        other_private, _ = generate_keypair()
        ciphertext = encrypt(b"secret", public)
        with pytest.raises(Exception):
            decrypt(ciphertext, other_private)

    def test_truncated_data_raises(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            decrypt(b"short", generate_keypair()[0])

    def test_empty_plaintext(self) -> None:
        private, public = generate_keypair()
        ciphertext = encrypt(b"", public)
        assert decrypt(ciphertext, private) == b""

    def test_large_payload(self) -> None:
        private, public = generate_keypair()
        plaintext = b"x" * 1_000_000
        ciphertext = encrypt(plaintext, public)
        assert decrypt(ciphertext, private) == plaintext

    def test_tampered_ciphertext_fails(self) -> None:
        private, public = generate_keypair()
        ciphertext = bytearray(encrypt(b"data", public))
        ciphertext[-1] ^= 0xFF
        with pytest.raises(Exception):
            decrypt(bytes(ciphertext), private)
