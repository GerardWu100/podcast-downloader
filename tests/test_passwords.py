"""Tests for password hashing and verification helpers."""

from __future__ import annotations

import pytest

from src.passwords import hash_password, is_password_hash, verify_password


def test_hash_password_round_trip() -> None:
    """A hashed password should verify successfully and hide the original text."""
    stored_value = hash_password("podcast-secret", salt=b"0123456789abcdef")

    assert stored_value != "podcast-secret"
    assert is_password_hash(stored_value) is True
    assert verify_password("podcast-secret", stored_value) is True
    assert verify_password("wrong-secret", stored_value) is False


def test_hash_password_rejects_blank_values() -> None:
    """Whitespace-only passwords must not be serialized into hashes."""
    with pytest.raises(ValueError):
        hash_password("   ")
