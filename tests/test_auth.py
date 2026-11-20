from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.features.auth import webauthn
from app.features.auth.models import PasskeyCredential, RecoveryCode, User
from app.main import create_app
from tests.conftest import ClientFactory

CRED = {
    "id": "Y3JlZDE",
    "rawId": "Y3JlZDE",
    "type": "public-key",
    "response": {"transports": ["internal", "hybrid"]},
}


@pytest.fixture
def fake_webauthn(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"sign_count": 1, "reg_id": b"cred1", "fail_auth": None}

    def fake_reg(**kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            credential_id=state["reg_id"], credential_public_key=b"public-key", sign_count=0
        )

    def fake_auth(**kwargs: Any) -> SimpleNamespace:
        if state["fail_auth"]:
            raise webauthn.WebAuthnException(state["fail_auth"])
        return SimpleNamespace(new_sign_count=state["sign_count"])

    monkeypatch.setattr(webauthn, "verify_registration_response", fake_reg)
    monkeypatch.setattr(webauthn, "verify_authentication_response", fake_auth)
    return state


async def _setup(client: httpx.AsyncClient) -> dict[str, Any]:
    r = await client.post(
        "/auth/setup/options", json={"display_name": "Mathan", "email": "m@x.dev"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["options"]["rp"]["id"] == "localhost"
    assert body["options"]["challenge"]
    r = await client.post(
        "/auth/setup/verify",
        json={"flow_id": body["flow_id"], "credential": CRED, "device_name": "MacBook"},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _login(client: httpx.AsyncClient) -> httpx.Response:
    r = await client.post("/auth/login/options")
    assert r.status_code == 200, r.text
    return await client.post(
        "/auth/login/verify", json={"flow_id": r.json()["flow_id"], "credential": CRED}
    )


async def test_status_before_setup(client: httpx.AsyncClient) -> None:
    r = await client.get("/auth/status")
    assert r.json() == {"setup_complete": False, "owner_name": None, "webauthn_rp_id": "localhost"}


async def test_setup_creates_owner_codes_and_cookies(
    client: httpx.AsyncClient, db: AsyncSession, fake_webauthn: dict[str, Any]
) -> None:
    data = await _setup(client)
    assert data["user"]["display_name"] == "Mathan"
    codes = data["recovery_codes"]
    assert len(codes) == 8 and all(len(c) == 9 and c[4] == "-" for c in codes)
    assert {"access_token", "refresh_token", "mandy_session"} <= set(client.cookies.keys())
    # stored hashed only
    hashes = (await db.scalars(select(RecoveryCode.code_hash))).all()
    assert len(hashes) == 8 and not set(codes) & set(hashes)
    cred = await db.scalar(select(PasskeyCredential))
    assert cred is not None and cred.transports == ["internal", "hybrid"]
    assert cred.device_name == "MacBook"

    r = await client.get("/auth/status")
    assert r.json()["setup_complete"] is True and r.json()["owner_name"] == "Mathan"
    me = await client.get("/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "m@x.dev"

    r = await client.post("/auth/setup/options", json={"display_name": "X", "email": "x@x.dev"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "SETUP_ALREADY_COMPLETE"


async def test_setup_attaches_to_seeded_owner(
    client: httpx.AsyncClient, db: AsyncSession, user: User, fake_webauthn: dict[str, Any]
) -> None:
    data = await _setup(client)
    assert data["user"]["id"] == str(user.id)
    assert await db.scalar(select(func.count()).select_from(User)) == 1
    await db.refresh(user)
    assert user.display_name == "Mathan" and user.email == "m@x.dev"


async def test_challenge_single_use(
    client: httpx.AsyncClient, fake_webauthn: dict[str, Any]
) -> None:
    r = await client.post("/auth/setup/options", json={"display_name": "M", "email": "m@x.dev"})
    flow = r.json()["flow_id"]
    payload = {"flow_id": flow, "credential": CRED}
    assert (await client.post("/auth/setup/verify", json=payload)).status_code == 200
    r = await client.post("/auth/setup/verify", json=payload)
    assert r.status_code == 401 and r.json()["error"]["code"] == "CHALLENGE_EXPIRED"


async def test_challenge_expires(client: httpx.AsyncClient) -> None:
    from app.core.redis import get_redis

    r = await client.post("/auth/setup/options", json={"display_name": "M", "email": "m@x.dev"})
    flow = r.json()["flow_id"]
    assert await get_redis().ttl(f"webauthn:flow:{flow}") <= 300
    await get_redis().delete(f"webauthn:flow:{flow}")  # what expiry does
    r = await client.post("/auth/setup/verify", json={"flow_id": flow, "credential": CRED})
    assert r.json()["error"]["code"] == "CHALLENGE_EXPIRED"


async def test_login_and_replay(client: httpx.AsyncClient, fake_webauthn: dict[str, Any]) -> None:
    await _setup(client)
    client.cookies.clear()
    r = await _login(client)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["display_name"] == "Mathan"
    assert "access_token" in client.cookies
    # same sign count again -> replay
    r = await _login(client)
    assert r.status_code == 401 and r.json()["error"]["code"] == "PASSKEY_REPLAY"
    fake_webauthn["sign_count"] = 5
    assert (await _login(client)).status_code == 200
    fake_webauthn["fail_auth"] = "Response sign count of 5 was not greater than current count"
    r = await _login(client)
    assert r.json()["error"]["code"] == "PASSKEY_REPLAY"
    fake_webauthn["fail_auth"] = "bad signature"
    r = await _login(client)
    assert r.json()["error"]["code"] == "PASSKEY_INVALID"


async def test_login_unknown_credential(
    client: httpx.AsyncClient, fake_webauthn: dict[str, Any]
) -> None:
    r = await client.post("/auth/login/options")
    r = await client.post(
        "/auth/login/verify",
        json={"flow_id": r.json()["flow_id"], "credential": {"id": "bm9wZQ", "rawId": "bm9wZQ"}},
    )
    assert r.status_code == 401 and r.json()["error"]["code"] == "PASSKEY_INVALID"


async def test_registration_failure(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(**_: Any) -> None:
        raise webauthn.WebAuthnException("bad attestation")

    monkeypatch.setattr(webauthn, "verify_registration_response", boom)
    r = await client.post("/auth/setup/options", json={"display_name": "M", "email": "m@x.dev"})
    r = await client.post(
        "/auth/setup/verify", json={"flow_id": r.json()["flow_id"], "credential": CRED}
    )
    assert r.status_code == 401 and r.json()["error"]["code"] == "PASSKEY_INVALID"


async def test_rate_limit_login(client: httpx.AsyncClient) -> None:
    codes = [(await client.post("/auth/login/options")).status_code for _ in range(6)]
    assert codes[:5] == [200] * 5 and codes[5] == 429
    r = await client.post("/auth/login/options")
    assert r.json()["error"]["code"] == "RATE_LIMITED" and "retry-after" in r.headers


async def test_recovery_flow(client: httpx.AsyncClient, fake_webauthn: dict[str, Any]) -> None:
    codes = (await _setup(client))["recovery_codes"]
    client.cookies.clear()
    r = await client.post("/auth/recover", json={"code": "0000-0000"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "RECOVERY_CODE_INVALID"
    r = await client.post("/auth/recover", json={"code": codes[0].lower()})
    assert r.status_code == 200, r.text
    token = r.json()["recovery_token"]
    # code works once
    r = await client.post("/auth/recover", json={"code": codes[0]})
    assert r.status_code == 401

    r = await client.post("/auth/recover/options", json={"recovery_token": token})
    assert r.status_code == 200
    flow = r.json()["flow_id"]
    fake_webauthn["reg_id"] = b"cred2"
    r = await client.post(
        "/auth/recover/verify",
        json={"recovery_token": token, "flow_id": flow, "credential": CRED, "device_name": "Phone"},
    )
    assert r.status_code == 200, r.text
    assert "access_token" in client.cookies
    # token is single use
    r = await client.post("/auth/recover/options", json={"recovery_token": token})
    assert r.status_code == 401 and r.json()["error"]["code"] == "RECOVERY_TOKEN_INVALID"
    r = await client.post("/auth/recover/options", json={"recovery_token": "garbage"})
    assert r.status_code == 401


async def test_passkey_management(client: httpx.AsyncClient, fake_webauthn: dict[str, Any]) -> None:
    await _setup(client)
    keys = (await client.get("/auth/passkeys")).json()
    assert len(keys) == 1 and keys[0]["device_name"] == "MacBook"
    r = await client.delete(f"/auth/passkeys/{keys[0]['id']}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "LAST_PASSKEY"

    r = await client.post("/auth/passkeys/options")
    flow = r.json()["flow_id"]
    assert r.json()["options"]["excludeCredentials"]
    r = await client.post(
        "/auth/passkeys/verify", json={"flow_id": flow, "credential": CRED, "device_name": "Key"}
    )
    assert r.status_code == 409  # same credential id already registered
    fake_webauthn["reg_id"] = b"cred2"
    r = await client.post("/auth/passkeys/options")
    r = await client.post(
        "/auth/passkeys/verify",
        json={"flow_id": r.json()["flow_id"], "credential": CRED, "device_name": "YubiKey"},
    )
    assert r.status_code == 201 and r.json()["device_name"] == "YubiKey"
    assert len((await client.get("/auth/passkeys")).json()) == 2
    assert (await client.delete(f"/auth/passkeys/{keys[0]['id']}")).status_code == 204
    r = await client.delete(f"/auth/passkeys/{keys[0]['id']}")
    assert r.status_code == 404

    r = await client.post("/auth/recovery-codes")
    assert len(r.json()["recovery_codes"]) == 8


async def test_refresh_rotation_and_logout(
    client: httpx.AsyncClient, fake_webauthn: dict[str, Any]
) -> None:
    await _setup(client)
    old_refresh = client.cookies.get("refresh_token")
    r = await client.post("/auth/refresh")
    assert r.status_code == 200 and r.json()["user"]["display_name"] == "Mathan"
    assert client.cookies.get("refresh_token") != old_refresh
    # the rotated token can't be reused; failure clears cookies incl. the hint cookie
    client.cookies.clear()
    client.cookies.set("refresh_token", old_refresh or "")
    r = await client.post("/auth/refresh")
    assert r.status_code == 401
    cleared = [c for c in r.headers.get_list("set-cookie") if "Max-Age=0" in c]
    assert {c.split("=", 1)[0] for c in cleared} == {
        "access_token",
        "refresh_token",
        "mandy_session",
    }

    await _login(client)
    r = await client.post("/auth/logout")
    assert r.status_code == 204
    assert "access_token" not in client.cookies
    r = await client.get("/auth/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_refresh_without_cookie(client: httpx.AsyncClient) -> None:
    r = await client.post("/auth/refresh")
    assert r.status_code == 401


async def test_protected_requires_auth(client: httpx.AsyncClient) -> None:
    for path in ("/auth/me", "/auth/passkeys"):
        r = await client.get(path)
        assert r.status_code == 401
    r = await client.get("/auth/me", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


async def test_dev_login_only_when_enabled(
    client: httpx.AsyncClient, make_client: ClientFactory, user: User
) -> None:
    r = await client.post("/auth/dev-login")
    assert r.status_code == 404
    dev_settings = get_settings().model_copy(update={"env": "dev", "dev_login_enabled": True})
    dev_app = create_app(dev_settings)
    dev = await make_client(None, dev_app)  # type: ignore[call-arg]
    r = await dev.post("/auth/dev-login")
    assert r.status_code == 200 and r.json()["user"]["id"] == str(user.id)
    assert (await dev.get("/auth/me")).status_code == 200
    prod_like = create_app(
        get_settings().model_copy(update={"env": "test", "dev_login_enabled": True})
    )
    other = await make_client(None, prod_like)  # type: ignore[call-arg]
    assert (await other.post("/auth/dev-login")).status_code == 404


async def test_dev_login_creates_owner_when_empty(make_client: ClientFactory) -> None:
    dev_app = create_app(
        get_settings().model_copy(update={"env": "dev", "dev_login_enabled": True})
    )
    dev = await make_client(None, dev_app)  # type: ignore[call-arg]
    r = await dev.post("/auth/dev-login")
    assert r.status_code == 200 and r.json()["user"]["email"] == "demo@mandy.dev"
