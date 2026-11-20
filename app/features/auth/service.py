"""Single-owner passkey auth: setup, login, recovery, passkey management, sessions."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppError, ConflictError, ForbiddenError, UnauthenticatedError
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.core.security import (
    create_token,
    decode_token,
    generate_recovery_code,
    hash_secret,
    normalize_recovery_code,
    subject_uuid,
    verify_secret,
)
from app.features.auth import webauthn
from app.features.auth.models import PasskeyCredential, RecoveryCode, User
from app.features.auth.schemas import AuthStatus

log = get_logger(__name__)

RECOVERY_CODE_COUNT = 8
DEFAULT_OWNER_NAME = "Mathan"
DEFAULT_OWNER_EMAIL = "demo@mandy.dev"


@dataclass(frozen=True)
class FlowResult:
    flow_id: str
    options: dict[str, Any]


# ---- helpers ---------------------------------------------------------------------------


async def get_owner(db: AsyncSession) -> User | None:
    """The single owner is the oldest user."""
    return await db.scalar(select(User).order_by(User.created_at, User.id).limit(1))


async def passkey_exists(db: AsyncSession) -> bool:
    return bool(await db.scalar(select(func.count()).select_from(PasskeyCredential)))


async def _stored_credentials(
    db: AsyncSession, user_id: uuid.UUID | None = None
) -> list[webauthn.StoredCredential]:
    stmt = select(PasskeyCredential)
    if user_id is not None:
        stmt = stmt.where(PasskeyCredential.user_id == user_id)
    rows = await db.scalars(stmt)
    return [webauthn.StoredCredential(r.credential_id, list(r.transports or [])) for r in rows]


def _verify_registration(
    credential: dict[str, Any], challenge: bytes
) -> webauthn.RegisteredCredential:
    try:
        return webauthn.verify_registration(credential, challenge)
    except (webauthn.WebAuthnException, ValueError, KeyError, TypeError) as exc:
        log.info("passkey_registration_failed", reason=str(exc))
        raise UnauthenticatedError("Passkey could not be verified", code="PASSKEY_INVALID") from exc


async def _save_credential(
    db: AsyncSession,
    user_id: uuid.UUID,
    reg: webauthn.RegisteredCredential,
    device_name: str | None,
) -> PasskeyCredential:
    exists = await db.scalar(
        select(PasskeyCredential.id).where(PasskeyCredential.credential_id == reg.credential_id)
    )
    if exists:
        raise ConflictError("This passkey is already registered", code="PASSKEY_EXISTS")
    cred = PasskeyCredential(
        user_id=user_id,
        credential_id=reg.credential_id,
        public_key=reg.public_key,
        sign_count=reg.sign_count,
        transports=reg.transports,
        device_name=(device_name or "").strip() or "Passkey",
    )
    db.add(cred)
    return cred


async def _replace_recovery_codes(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user_id))
    codes = [generate_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    db.add_all(RecoveryCode(user_id=user_id, code_hash=hash_secret(c)) for c in codes)
    return codes


# ---- status / setup --------------------------------------------------------------------


async def auth_status(db: AsyncSession) -> AuthStatus:
    owner = await get_owner(db)
    return AuthStatus(
        setup_complete=await passkey_exists(db),
        owner_name=owner.display_name if owner else None,
        webauthn_rp_id=get_settings().rp_id,
    )


async def setup_options(db: AsyncSession, display_name: str, email: str) -> FlowResult:
    if await passkey_exists(db):
        raise ForbiddenError("Setup is already complete", code="SETUP_ALREADY_COMPLETE")
    owner = await get_owner(db)
    user_id = owner.id if owner else uuid.uuid4()
    options, challenge = webauthn.registration_options(
        user_id=user_id, email=email, display_name=display_name, exclude=[]
    )
    flow_id = await webauthn.save_flow(
        "setup", challenge, user_id=str(user_id), display_name=display_name, email=email
    )
    return FlowResult(flow_id, options)


async def setup_verify(
    db: AsyncSession, flow_id: str, credential: dict[str, Any], device_name: str | None
) -> tuple[User, list[str]]:
    challenge, data = await webauthn.pop_flow(flow_id, "setup")
    if await passkey_exists(db):
        raise ForbiddenError("Setup is already complete", code="SETUP_ALREADY_COMPLETE")
    reg = _verify_registration(credential, challenge)

    owner = await get_owner(db)
    if owner is None:
        owner = User(id=uuid.UUID(data["user_id"]), email=data["email"], display_name="")
        db.add(owner)
    owner.display_name = data["display_name"]
    owner.email = data["email"]
    await db.flush()
    await _save_credential(db, owner.id, reg, device_name)
    codes = await _replace_recovery_codes(db, owner.id)
    await db.commit()
    log.info("owner_setup_complete", user_id=str(owner.id))
    return owner, codes


# ---- login -----------------------------------------------------------------------------


async def login_options(db: AsyncSession) -> FlowResult:
    options, challenge = webauthn.authentication_options(await _stored_credentials(db))
    return FlowResult(await webauthn.save_flow("login", challenge), options)


async def _authenticate(
    db: AsyncSession, credential: dict[str, Any], challenge: bytes, user_id: uuid.UUID | None = None
) -> User:
    cred_id = webauthn.credential_id_from(credential)
    stmt = select(PasskeyCredential).where(PasskeyCredential.credential_id == cred_id)
    if user_id is not None:
        stmt = stmt.where(PasskeyCredential.user_id == user_id)
    stored = await db.scalar(stmt)
    if stored is None:
        raise UnauthenticatedError("Unknown passkey", code="PASSKEY_INVALID")
    try:
        new_count = webauthn.verify_authentication(
            credential, challenge, stored.public_key, stored.sign_count
        )
    except (webauthn.WebAuthnException, ValueError, KeyError, TypeError) as exc:
        if "sign count" in str(exc).lower():
            raise UnauthenticatedError("Passkey replay detected", code="PASSKEY_REPLAY") from exc
        log.info("passkey_authentication_failed", reason=str(exc))
        raise UnauthenticatedError("Passkey could not be verified", code="PASSKEY_INVALID") from exc
    # Authenticators that don't count always report 0; any counter must strictly increase.
    if (new_count or stored.sign_count) and new_count <= stored.sign_count:
        raise UnauthenticatedError("Passkey replay detected", code="PASSKEY_REPLAY")
    stored.sign_count = new_count
    stored.last_used_at = datetime.now(UTC)
    user = await db.get(User, stored.user_id)
    assert user is not None
    await db.commit()
    return user


async def login_verify(db: AsyncSession, flow_id: str, credential: dict[str, Any]) -> User:
    challenge, _ = await webauthn.pop_flow(flow_id, "login")
    return await _authenticate(db, credential, challenge)


# ---- recovery --------------------------------------------------------------------------


async def recover(db: AsyncSession, code: str) -> str:
    owner = await get_owner(db)
    normalized = normalize_recovery_code(code)
    if owner is not None:
        rows = await db.scalars(
            select(RecoveryCode).where(
                RecoveryCode.user_id == owner.id, RecoveryCode.used_at.is_(None)
            )
        )
        for row in rows:
            if verify_secret(normalized, row.code_hash):
                row.used_at = datetime.now(UTC)
                await db.commit()
                ttl = timedelta(minutes=get_settings().recovery_token_minutes)
                return create_token(owner.id, "recovery", ttl).token
    raise UnauthenticatedError("Invalid recovery code", code="RECOVERY_CODE_INVALID")


def _recovery_payload(token: str) -> tuple[uuid.UUID, str]:
    payload = decode_token(token, "recovery", code="RECOVERY_TOKEN_INVALID")
    return subject_uuid(payload, code="RECOVERY_TOKEN_INVALID"), str(payload["jti"])


async def _recovery_user(db: AsyncSession, token: str) -> tuple[User, str]:
    user_id, jti = _recovery_payload(token)
    if await get_redis().exists(f"used:recovery:{jti}"):
        raise UnauthenticatedError("Recovery token already used", code="RECOVERY_TOKEN_INVALID")
    user = await db.get(User, user_id)
    if user is None:
        raise UnauthenticatedError("Invalid recovery token", code="RECOVERY_TOKEN_INVALID")
    return user, jti


async def recover_options(db: AsyncSession, token: str) -> FlowResult:
    user, jti = await _recovery_user(db, token)
    options, challenge = webauthn.registration_options(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        exclude=await _stored_credentials(db, user.id),
    )
    return FlowResult(await webauthn.save_flow("recover", challenge, jti=jti), options)


async def recover_verify(
    db: AsyncSession,
    token: str,
    flow_id: str,
    credential: dict[str, Any],
    device_name: str | None,
) -> User:
    user, jti = await _recovery_user(db, token)
    challenge, data = await webauthn.pop_flow(flow_id, "recover")
    if data.get("jti") != jti:
        raise UnauthenticatedError("Challenge does not match token", code="CHALLENGE_EXPIRED")
    reg = _verify_registration(credential, challenge)
    ttl = get_settings().recovery_token_minutes * 60
    if not await get_redis().set(f"used:recovery:{jti}", "1", nx=True, ex=ttl):
        raise UnauthenticatedError("Recovery token already used", code="RECOVERY_TOKEN_INVALID")
    await _save_credential(db, user.id, reg, device_name)
    await db.commit()
    log.info("passkey_recovered", user_id=str(user.id))
    return user


# ---- passkey management ----------------------------------------------------------------


async def passkey_options(db: AsyncSession, user: User) -> FlowResult:
    options, challenge = webauthn.registration_options(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        exclude=await _stored_credentials(db, user.id),
    )
    flow_id = await webauthn.save_flow("add_passkey", challenge, user_id=str(user.id))
    return FlowResult(flow_id, options)


async def passkey_verify(
    db: AsyncSession, user: User, flow_id: str, credential: dict[str, Any], device_name: str | None
) -> PasskeyCredential:
    challenge, data = await webauthn.pop_flow(flow_id, "add_passkey")
    if data.get("user_id") != str(user.id):
        raise UnauthenticatedError("Challenge does not match user", code="CHALLENGE_EXPIRED")
    reg = _verify_registration(credential, challenge)
    cred = await _save_credential(db, user.id, reg, device_name)
    await db.commit()
    return cred


async def list_passkeys(db: AsyncSession, user: User) -> list[PasskeyCredential]:
    rows = await db.scalars(
        select(PasskeyCredential)
        .where(PasskeyCredential.user_id == user.id)
        .order_by(PasskeyCredential.created_at)
    )
    return list(rows)


async def delete_passkey(db: AsyncSession, user: User, passkey_id: uuid.UUID) -> None:
    passkeys = await list_passkeys(db, user)
    target = next((p for p in passkeys if p.id == passkey_id), None)
    if target is None:
        raise AppError("Passkey not found", code="PASSKEY_NOT_FOUND", status_code=404)
    if len(passkeys) <= 1:
        raise ConflictError("You can't delete your last passkey", code="LAST_PASSKEY")
    await db.delete(target)
    await db.commit()


async def regenerate_recovery_codes(db: AsyncSession, user: User) -> list[str]:
    codes = await _replace_recovery_codes(db, user.id)
    await db.commit()
    return codes


# ---- sessions --------------------------------------------------------------------------


async def user_from_refresh_token(db: AsyncSession, token: str | None) -> User:
    """Validate a refresh token, revoke it (rotation) and return its user."""
    if not token:
        raise UnauthenticatedError("No refresh token")
    payload = decode_token(token, "refresh")
    jti = str(payload["jti"])
    ttl = max(int(payload["exp"] - datetime.now(UTC).timestamp()), 1)
    if not await get_redis().set(f"revoked:refresh:{jti}", "1", nx=True, ex=ttl):
        raise UnauthenticatedError("Refresh token was already used")
    user = await db.get(User, subject_uuid(payload))
    if user is None:
        raise UnauthenticatedError("User no longer exists")
    return user


async def revoke_refresh_token(token: str | None) -> None:
    if not token:
        return
    try:
        payload = decode_token(token, "refresh")
    except UnauthenticatedError:
        return
    ttl = max(int(payload["exp"] - datetime.now(UTC).timestamp()), 1)
    await get_redis().set(f"revoked:refresh:{payload['jti']}", "1", ex=ttl)


async def dev_login_user(db: AsyncSession) -> User:
    owner = await get_owner(db)
    if owner is None:
        owner = User(email=DEFAULT_OWNER_EMAIL, display_name=DEFAULT_OWNER_NAME)
        db.add(owner)
        await db.commit()
    return owner
