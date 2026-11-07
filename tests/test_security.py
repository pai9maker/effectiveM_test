"""JWT, password hashing and CSRF primitives."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.core.security import (
    TokenError,
    create_token,
    csrf_tokens_match,
    decode_token,
    hash_password,
    needs_rehash,
    new_csrf_token,
    verify_password,
)


def test_password_hash_roundtrip():
    password_hash = hash_password("correct horse battery staple")
    assert password_hash != "correct horse battery staple"
    assert password_hash.startswith("$argon2id$")
    assert verify_password("correct horse battery staple", password_hash)
    assert not verify_password("wrong password", password_hash)


def test_argon2_hash_needs_rehash_only_when_parameters_change():
    password_hash = hash_password("another-secret-value")
    assert not needs_rehash(password_hash)
    assert needs_rehash("not-a-hash")


def test_tokens_are_typed_and_decodable():
    subject = str(uuid.uuid4())
    access, jti, expires = create_token(
        subject=subject, role="user", token_type="access", ttl=timedelta(minutes=5)
    )
    payload = decode_token(access, "access")
    assert payload["sub"] == subject
    assert payload["role"] == "user"
    assert payload["jti"] == jti
    assert expires.timestamp() == pytest.approx(payload["exp"], abs=1)

    with pytest.raises(TokenError):
        decode_token(access, "refresh")


def test_tampered_token_is_rejected():
    token, _, _ = create_token(
        subject=str(uuid.uuid4()), role="user", token_type="access", ttl=timedelta(minutes=5)
    )
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}.{signature[:-2]}AA"
    with pytest.raises(TokenError):
        decode_token(tampered, "access")


def test_expired_token_is_rejected():
    token, _, _ = create_token(
        subject=str(uuid.uuid4()), role="user", token_type="access", ttl=timedelta(seconds=-10)
    )
    with pytest.raises(TokenError):
        decode_token(token, "access")


def test_csrf_double_submit_comparison():
    token = new_csrf_token()
    assert csrf_tokens_match(token, token)
    assert not csrf_tokens_match(token, new_csrf_token())
    assert not csrf_tokens_match(None, token)
    assert not csrf_tokens_match(token, None)
    assert not csrf_tokens_match("", token)
