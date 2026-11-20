"""`get_current_user`: access token from the httpOnly cookie or `Authorization: Bearer`."""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import UnauthenticatedError
from app.core.security import decode_token, subject_uuid
from app.db.session import DbSession
from app.features.auth.cookies import ACCESS_COOKIE
from app.features.auth.models import User

bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Access token (the same JWT that is sent as the `access_token` cookie)",
)


async def get_current_user(
    request: Request,
    db: DbSession,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    token = bearer.credentials if bearer else request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise UnauthenticatedError()
    payload = decode_token(token, "access")
    user = await db.get(User, subject_uuid(payload))
    if user is None:
        raise UnauthenticatedError()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
