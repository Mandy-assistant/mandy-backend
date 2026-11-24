"""Session cookies: access/refresh tokens (httpOnly) + the `mandy_session` hint cookie.

`refresh_token` is scoped to `/api/<API_VERSION>/auth`, so the frontend's Next.js proxy can't
see it on page requests. `mandy_session=1` (not httpOnly, no secret in it) tells the proxy
that a session probably exists, for an optimistic signed-in redirect.
"""

import uuid
from datetime import timedelta

from fastapi import Response

from app.core.config import get_settings
from app.core.security import IssuedToken, create_token

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
SESSION_HINT_COOKIE = "mandy_session"


def refresh_path() -> str:
    """The refresh cookie is only sent to the auth routes of the API version being served."""
    return f"{get_settings().api_prefix}/auth"


def set_auth_cookies(response: Response, user_id: uuid.UUID) -> IssuedToken:
    """Issue a new token pair as cookies. Returns the access token (handy for tests)."""
    settings = get_settings()
    secure = settings.cookie_secure
    access = create_token(user_id, "access", timedelta(minutes=settings.access_token_minutes))
    refresh = create_token(user_id, "refresh", timedelta(days=settings.refresh_token_days))
    response.set_cookie(
        ACCESS_COOKIE,
        access.token,
        max_age=access.max_age,
        path="/",
        httponly=True,
        secure=secure,
        samesite="lax",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh.token,
        max_age=refresh.max_age,
        path=refresh_path(),
        httponly=True,
        secure=secure,
        samesite="lax",
    )
    response.set_cookie(
        SESSION_HINT_COOKIE,
        "1",
        max_age=refresh.max_age,
        path="/",
        httponly=False,
        secure=secure,
        samesite="lax",
    )
    return access


def clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    secure = settings.cookie_secure
    response.delete_cookie(ACCESS_COOKIE, path="/", httponly=True, secure=secure, samesite="lax")
    response.delete_cookie(
        REFRESH_COOKIE, path=refresh_path(), httponly=True, secure=secure, samesite="lax"
    )
    response.delete_cookie(SESSION_HINT_COOKIE, path="/", secure=secure, samesite="lax")
