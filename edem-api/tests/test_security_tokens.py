import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedException
from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
)

USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_SECRET = "another-secret-that-is-also-long-enough-for-hs256"


def make_raw_token(*, remove=(), secret=None, **overrides) -> str:
    """Build a token by hand, so tests can create broken ones."""
    settings = get_settings()
    now = datetime.now(UTC)
    claims = {
        "sub": str(USER_ID),
        "type": "access",
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    for name in remove:
        claims.pop(name, None)
    return jwt.encode(
        claims,
        secret or settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def test_access_token_round_trip():
    payload = decode_token(create_access_token(USER_ID), TokenType.ACCESS)
    assert payload.user_id == USER_ID
    assert payload.token_type == TokenType.ACCESS


def test_refresh_token_round_trip():
    payload = decode_token(create_refresh_token(USER_ID), TokenType.REFRESH)
    assert payload.user_id == USER_ID
    assert payload.token_type == TokenType.REFRESH


def test_every_token_has_its_own_id():
    first = decode_token(create_access_token(USER_ID), TokenType.ACCESS)
    second = decode_token(create_access_token(USER_ID), TokenType.ACCESS)
    assert first.jti != second.jti


def test_access_token_lifetime_matches_settings():
    minutes = get_settings().ACCESS_TOKEN_EXPIRE_MINUTES
    now = datetime.now(UTC)
    payload = decode_token(create_access_token(USER_ID), TokenType.ACCESS)
    remaining = (payload.expires_at - now).total_seconds()
    assert minutes * 60 - 5 <= remaining <= minutes * 60 + 5


def test_refresh_token_lasts_longer_than_access_token():
    access = decode_token(create_access_token(USER_ID), TokenType.ACCESS)
    refresh = decode_token(create_refresh_token(USER_ID), TokenType.REFRESH)
    assert refresh.expires_at > access.expires_at


def test_access_token_is_rejected_where_refresh_is_expected():
    with pytest.raises(UnauthorizedException, match="Wrong token type"):
        decode_token(create_access_token(USER_ID), TokenType.REFRESH)


def test_refresh_token_is_rejected_where_access_is_expected():
    with pytest.raises(UnauthorizedException, match="Wrong token type"):
        decode_token(create_refresh_token(USER_ID), TokenType.ACCESS)


def test_expired_token_is_rejected():
    expired = create_access_token(USER_ID, expires_delta=timedelta(seconds=-5))
    with pytest.raises(UnauthorizedException, match="expired"):
        decode_token(expired, TokenType.ACCESS)


def test_token_signed_with_another_secret_is_rejected():
    forged = make_raw_token(secret=OTHER_SECRET)
    with pytest.raises(UnauthorizedException, match="Invalid token"):
        decode_token(forged, TokenType.ACCESS)


def test_tampered_token_is_rejected():
    header, payload, signature = create_access_token(USER_ID).split(".")
    changed_first_char = "A" if signature[0] != "A" else "B"
    tampered = ".".join([header, payload, changed_first_char + signature[1:]])
    with pytest.raises(UnauthorizedException, match="Invalid token"):
        decode_token(tampered, TokenType.ACCESS)


def test_unsigned_token_with_alg_none_is_rejected():
    now = datetime.now(UTC)
    unsigned = jwt.encode(
        {
            "sub": str(USER_ID),
            "type": "access",
            "jti": "x",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        key="",  # PyJWT requires a key arg; algorithm=none still invalid for us
        algorithm="none",
    )
    with pytest.raises(UnauthorizedException):
        decode_token(unsigned, TokenType.ACCESS)


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c"])
def test_garbage_is_rejected(garbage):
    with pytest.raises(UnauthorizedException, match="Invalid token"):
        decode_token(garbage, TokenType.ACCESS)


@pytest.mark.parametrize("missing", ["exp", "iat", "sub", "type", "jti"])
def test_token_missing_a_required_claim_is_rejected(missing):
    with pytest.raises(UnauthorizedException):
        decode_token(make_raw_token(remove=[missing]), TokenType.ACCESS)


def test_subject_that_is_not_a_uuid_is_rejected():
    with pytest.raises(UnauthorizedException, match="Invalid token"):
        decode_token(make_raw_token(sub="not-a-uuid"), TokenType.ACCESS)


def test_failures_use_the_unauthorized_status_and_code():
    with pytest.raises(UnauthorizedException) as error:
        decode_token("abc", TokenType.ACCESS)
    assert error.value.status_code == 401
    assert error.value.code == "UNAUTHORIZED"