"""
Password hashing & JWT issuance/verification.

- Passwords: bcrypt via passlib's `CryptContext` (automatic salt generation,
  configurable work factor, safe verification with timing-attack resistance).
- Tokens: short-lived JWT access tokens + longer-lived JWT refresh tokens,
  both signed with HS256 using `settings.SECRET_KEY`. Token `type` is
  embedded in the payload so an access token can never be replayed as a
  refresh token or vice versa.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def _create_token(subject: str, expires_delta: timedelta, token_type: Literal["access", "refresh"]) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),  # unique token id, useful for future revocation lists
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(user_id: str) -> str:
    return _create_token(
        user_id, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), "access"
    )


def create_refresh_token(user_id: str) -> str:
    return _create_token(
        user_id, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), "refresh"
    )


class InvalidTokenError(Exception):
    """Raised for any structurally invalid, expired, or wrong-type token."""


def decode_token(token: str, expected_type: Literal["access", "refresh"]) -> str:
    """Decode & validate a JWT, returning the subject (user id).

    Raises `InvalidTokenError` on any failure — expired, malformed,
    bad signature, or wrong token type — so callers have one exception to
    handle instead of juggling `jose`'s exception hierarchy.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise InvalidTokenError("Token is invalid or has expired.") from exc

    if payload.get("type") != expected_type:
        raise InvalidTokenError(f"Expected a '{expected_type}' token.")

    subject = payload.get("sub")
    if not subject:
        raise InvalidTokenError("Token is missing a subject.")

    return subject
