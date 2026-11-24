"""JWTs and hashing."""

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import get_settings
from app.core.exceptions import UnauthenticatedError

TokenType = Literal["access", "refresh", "recovery"]

# OWASP-recommended Argon2id minimum (19 MiB, t=2): recovery codes are checked one by one.
_hasher = PasswordHash((Argon2Hasher(time_cost=2, memory_cost=19456, parallelism=1),))


@dataclass(frozen=True)
class IssuedToken:
    token: str
    jti: str
    expires_at: datetime
    max_age: int


def create_token(subject: uuid.UUID, token_type: TokenType, ttl: timedelta) -> IssuedToken:
    settings = get_settings()
    now = datetime.now(UTC)
    jti = uuid.uuid4().hex
    exp = now + ttl
    payload = {"sub": str(subject), "type": token_type, "iat": now, "exp": exp, "jti": jti}
    token = jwt.encode(
        payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm
    )
    return IssuedToken(token=token, jti=jti, expires_at=exp, max_age=int(ttl.total_seconds()))


def decode_token(
    token: str, expected_type: TokenType, *, code: str = "UNAUTHENTICATED"
) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "type", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise UnauthenticatedError("Invalid or expired token", code=code) from exc
    if payload.get("type") != expected_type:
        raise UnauthenticatedError("Invalid token type", code=code)
    return payload


def subject_uuid(payload: dict[str, Any], *, code: str = "UNAUTHENTICATED") -> uuid.UUID:
    try:
        return uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise UnauthenticatedError("Invalid token subject", code=code) from exc


def hash_secret(value: str) -> str:
    return _hasher.hash(value)


def verify_secret(value: str, hashed: str) -> bool:
    try:
        return _hasher.verify(value, hashed)
    except Exception:
        return False


def generate_recovery_code() -> str:
    raw = secrets.token_hex(4).upper()
    return f"{raw[:4]}-{raw[4:]}"


def normalize_recovery_code(code: str) -> str:
    cleaned = "".join(ch for ch in code.upper() if ch.isalnum())
    return f"{cleaned[:4]}-{cleaned[4:]}" if len(cleaned) == 8 else cleaned
