import httpx
import pytest
from fastapi import APIRouter

from app.core.config import Settings
from app.core.security import create_token, decode_token
from app.main import create_app
from tests.conftest import ClientFactory


async def test_health(client: httpx.AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok", "redis": "ok"}


async def test_request_id_and_security_headers(client: httpx.AsyncClient) -> None:
    r = await client.get("/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["x-request-id"] == "abc123"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    r = await client.get("/health")
    assert len(r.headers["x-request-id"]) == 32


async def test_docs_have_no_strict_csp(app) -> None:  # type: ignore[no-untyped-def]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/docs")
        assert r.status_code == 200 and "content-security-policy" not in r.headers
        spec = (await c.get("/openapi.json")).json()
        assert "/api/v1/dashboard/summary" in spec["paths"]
        assert "ErrorResponse" in spec["components"]["schemas"]
        assert "HTTPBearer" in spec["components"]["securitySchemes"]


async def test_error_formats(client: httpx.AsyncClient) -> None:
    r = await client.get("/does-not-exist")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "NOT_FOUND", "message": "Not Found", "details": []}}
    r = await client.delete("/health")
    assert r.status_code == 405 and r.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


async def test_body_size_limit(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/tasks", content=b"x" * 1_100_000, headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


async def test_cors_preflight(client: httpx.AsyncClient) -> None:
    r = await client.options(
        "/jobs",
        headers={"Origin": "http://localhost:3001", "Access-Control-Request-Method": "POST"},
    )
    assert r.headers["access-control-allow-origin"] == "http://localhost:3001"
    assert r.headers["access-control-allow-credentials"] == "true"
    r = await client.options(
        "/jobs", headers={"Origin": "http://evil.test", "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in r.headers


async def test_unhandled_error_is_wrapped(make_client: ClientFactory) -> None:
    app = create_app()
    boom = APIRouter()

    @boom.get("/api/v1/boom")
    async def _boom() -> None:
        raise RuntimeError("kaboom")

    app.include_router(boom)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/boom")
    assert r.status_code == 500
    assert r.json()["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "Something went wrong",
        "details": [],
    }
    assert "kaboom" not in r.text


async def test_token_type_is_checked(client: httpx.AsyncClient, user) -> None:  # type: ignore[no-untyped-def]
    from datetime import timedelta

    refresh = create_token(user.id, "refresh", timedelta(minutes=5)).token
    r = await client.get("/auth/me", headers={"Authorization": f"Bearer {refresh}"})
    assert r.status_code == 401
    assert decode_token(create_token(user.id, "access", timedelta(minutes=1)).token, "access")


def test_prod_settings_require_strong_secret() -> None:
    with pytest.raises(ValueError):
        Settings(env="prod", jwt_secret="short")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Settings(env="prod", jwt_secret="x" * 40, dev_login_enabled=True)  # type: ignore[arg-type]
    ok = Settings(env="prod", jwt_secret="x" * 40)  # type: ignore[arg-type]
    assert ok.cookie_secure is True and ok.dev_login_active is False


async def test_body_size_limit_streamed(app) -> None:  # type: ignore[no-untyped-def]
    async def chunks():  # type: ignore[no-untyped-def]
        for _ in range(20):
            yield b"x" * 100_000

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post("/api/v1/auth/setup/options", content=chunks())
    assert r.status_code == 413 and r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_api_version_setting() -> None:
    assert Settings(api_version=" /V1 ").api_version == "v1"
    assert Settings(api_version="v1").api_prefix == "/api/v1"
    with pytest.raises(ValueError, match="api_version"):
        Settings(api_version="v9")


def test_only_selected_version_is_mounted(app) -> None:  # type: ignore[no-untyped-def]
    paths = set(app.openapi()["paths"])
    assert "/api/v1/health" in paths
    assert not any(p.startswith("/api/") and not p.startswith("/api/v1/") for p in paths)
