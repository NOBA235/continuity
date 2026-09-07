import time
from uuid import uuid4

import pytest

from app.auth.security import (
    TokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.config import get_settings
from app.models.schemas import UserRole


def test_hash_password_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_hash_password_produces_different_hashes_for_same_input():
    # bcrypt salts randomly -- two hashes of the same password must differ.
    assert hash_password("same-password") != hash_password("same-password")


def test_verify_password_rejects_malformed_stored_hash_instead_of_raising():
    assert verify_password("anything", "not-a-real-bcrypt-hash") is False


def test_access_token_roundtrip():
    settings = get_settings()
    user_id = uuid4()
    token = create_access_token(settings, user_id, "supervisor@studio.test", UserRole.supervisor)
    payload = decode_token(settings, token, expected_type=TokenType.access)
    assert payload["sub"] == str(user_id)
    assert payload["email"] == "supervisor@studio.test"
    assert payload["role"] == "supervisor"
    assert payload["type"] == "access"


def test_refresh_token_cannot_be_used_as_access_token():
    settings = get_settings()
    user_id = uuid4()
    refresh = create_refresh_token(settings, user_id, "e@x.test", UserRole.viewer)
    with pytest.raises(TokenError):
        decode_token(settings, refresh, expected_type=TokenType.access)


def test_access_token_cannot_be_used_as_refresh_token():
    settings = get_settings()
    user_id = uuid4()
    access = create_access_token(settings, user_id, "e@x.test", UserRole.viewer)
    with pytest.raises(TokenError):
        decode_token(settings, access, expected_type=TokenType.refresh)


def test_expired_access_token_is_rejected(mocker):
    settings = get_settings()
    # Force a token that expired 1 minute ago by overriding the expiry window.
    mocker.patch.object(settings, "jwt_access_token_expire_minutes", -1)
    token = create_access_token(settings, uuid4(), "e@x.test", UserRole.viewer)
    time.sleep(0.01)
    with pytest.raises(TokenError, match="expired"):
        decode_token(settings, token, expected_type=TokenType.access)


def test_tampered_token_signature_is_rejected():
    settings = get_settings()
    token = create_access_token(settings, uuid4(), "e@x.test", UserRole.viewer)
    tampered = token[:-4] + ("A" * 4 if not token.endswith("AAAA") else "BBBB")
    with pytest.raises(TokenError):
        decode_token(settings, tampered, expected_type=TokenType.access)


def test_token_signed_with_different_secret_is_rejected(mocker):
    settings = get_settings()
    token = create_access_token(settings, uuid4(), "e@x.test", UserRole.viewer)

    other_settings = get_settings().model_copy(update={"jwt_secret_key": "a" * 32})
    with pytest.raises(TokenError):
        decode_token(other_settings, token, expected_type=TokenType.access)
