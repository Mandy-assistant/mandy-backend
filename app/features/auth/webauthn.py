"""Thin wrapper over py_webauthn plus the Redis challenge store.

Tests monkeypatch `verify_registration_response` / `verify_authentication_response` here.
"""

import json
import secrets
import uuid
from dataclasses import dataclass
from typing import Any

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.core.config import get_settings
from app.core.exceptions import UnauthenticatedError
from app.core.redis import get_redis

FLOW_TTL_SECONDS = 300

__all__ = [
    "RegisteredCredential",
    "WebAuthnException",
    "authentication_options",
    "credential_id_from",
    "pop_flow",
    "registration_options",
    "save_flow",
    "verify_authentication",
    "verify_registration",
]


@dataclass(frozen=True)
class RegisteredCredential:
    credential_id: bytes
    public_key: bytes
    sign_count: int
    transports: list[str]


@dataclass(frozen=True)
class StoredCredential:
    credential_id: bytes
    transports: list[str]


def _descriptors(creds: list[StoredCredential]) -> list[PublicKeyCredentialDescriptor]:
    out = []
    for c in creds:
        transports = []
        for t in c.transports:
            try:
                transports.append(AuthenticatorTransport(t))
            except ValueError:
                continue
        out.append(PublicKeyCredentialDescriptor(id=c.credential_id, transports=transports))
    return out


def registration_options(
    *,
    user_id: uuid.UUID,
    email: str,
    display_name: str,
    exclude: list[StoredCredential],
) -> tuple[dict[str, Any], bytes]:
    settings = get_settings()
    options = generate_registration_options(
        rp_id=settings.rp_id,
        rp_name=settings.rp_name,
        user_id=user_id.bytes,
        user_name=email,
        user_display_name=display_name,
        exclude_credentials=_descriptors(exclude),
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    return json.loads(options_to_json(options)), options.challenge


def authentication_options(allow: list[StoredCredential]) -> tuple[dict[str, Any], bytes]:
    settings = get_settings()
    options = generate_authentication_options(
        rp_id=settings.rp_id,
        allow_credentials=_descriptors(allow),
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    return json.loads(options_to_json(options)), options.challenge


def verify_registration(credential: dict[str, Any], challenge: bytes) -> RegisteredCredential:
    settings = get_settings()
    verified = verify_registration_response(
        credential=credential,
        expected_challenge=challenge,
        expected_rp_id=settings.rp_id,
        expected_origin=settings.origin,
    )
    response = credential.get("response") or {}
    transports = [str(t) for t in response.get("transports", []) if isinstance(t, str)]
    return RegisteredCredential(
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        transports=transports,
    )


def verify_authentication(
    credential: dict[str, Any], challenge: bytes, public_key: bytes, sign_count: int
) -> int:
    """Verify an assertion and return the authenticator's new sign count."""
    settings = get_settings()
    verified = verify_authentication_response(
        credential=credential,
        expected_challenge=challenge,
        expected_rp_id=settings.rp_id,
        expected_origin=settings.origin,
        credential_public_key=public_key,
        credential_current_sign_count=sign_count,
    )
    return int(verified.new_sign_count)


def credential_id_from(credential: dict[str, Any]) -> bytes:
    raw = credential.get("rawId") or credential.get("id")
    if not isinstance(raw, str) or not raw:
        raise UnauthenticatedError("Malformed credential", code="PASSKEY_INVALID")
    try:
        return base64url_to_bytes(raw)
    except Exception as exc:
        raise UnauthenticatedError("Malformed credential", code="PASSKEY_INVALID") from exc


# ---- challenge store ------------------------------------------------------------------


async def save_flow(purpose: str, challenge: bytes, **data: Any) -> str:
    flow_id = secrets.token_urlsafe(24)
    payload = {"purpose": purpose, "challenge": bytes_to_base64url(challenge), **data}
    await get_redis().set(f"webauthn:flow:{flow_id}", json.dumps(payload), ex=FLOW_TTL_SECONDS)
    return flow_id


async def pop_flow(flow_id: str, purpose: str) -> tuple[bytes, dict[str, Any]]:
    """Return (challenge, data) and delete the flow: every challenge is single use."""
    raw = await get_redis().getdel(f"webauthn:flow:{flow_id}")
    if not raw:
        raise UnauthenticatedError("Challenge expired or already used", code="CHALLENGE_EXPIRED")
    payload: dict[str, Any] = json.loads(raw)
    if payload.get("purpose") != purpose:
        raise UnauthenticatedError("Challenge expired or already used", code="CHALLENGE_EXPIRED")
    return base64url_to_bytes(payload.pop("challenge")), payload
