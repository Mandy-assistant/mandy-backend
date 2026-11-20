import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response, status
from fastapi.responses import JSONResponse

from app.core.exceptions import UnauthenticatedError, error_payload, error_responses
from app.core.ratelimit import rate_limit
from app.db.session import DbSession
from app.features.auth import service
from app.features.auth.cookies import REFRESH_COOKIE, clear_auth_cookies, set_auth_cookies
from app.features.auth.deps import CurrentUser
from app.features.auth.schemas import (
    AuthStatus,
    CredentialIn,
    FlowOptions,
    PasskeyOut,
    RecoverIn,
    RecoverVerifyIn,
    RecoveryCodesOut,
    RecoveryTokenIn,
    RecoveryTokenOut,
    RegisterCredentialIn,
    SetupOptionsIn,
    SetupVerifyOut,
    UserEnvelope,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])
dev_router = APIRouter(prefix="/auth", tags=["auth"])

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE, include_in_schema=False)]


def _envelope(user: object) -> UserEnvelope:
    return UserEnvelope(user=UserOut.model_validate(user))


@router.get("/status", response_model=AuthStatus, summary="Setup vs unlock")
async def auth_status(db: DbSession) -> AuthStatus:
    return await service.auth_status(db)


@router.post(
    "/setup/options",
    response_model=FlowOptions,
    summary="Start first-passkey registration",
    responses=error_responses(403),
)
async def setup_options(body: SetupOptionsIn, db: DbSession) -> FlowOptions:
    flow = await service.setup_options(db, body.display_name, str(body.email))
    return FlowOptions(flow_id=flow.flow_id, options=flow.options)


@router.post(
    "/setup/verify",
    response_model=SetupVerifyOut,
    summary="Finish setup: save the passkey, return recovery codes, start a session",
    responses=error_responses(401, 403),
)
async def setup_verify(
    body: RegisterCredentialIn, db: DbSession, response: Response
) -> SetupVerifyOut:
    user, codes = await service.setup_verify(db, body.flow_id, body.credential, body.device_name)
    set_auth_cookies(response, user.id)
    return SetupVerifyOut(user=UserOut.model_validate(user), recovery_codes=codes)


@router.post(
    "/login/options",
    response_model=FlowOptions,
    dependencies=[Depends(rate_limit("login_options"))],
    responses=error_responses(429),
)
async def login_options(db: DbSession) -> FlowOptions:
    flow = await service.login_options(db)
    return FlowOptions(flow_id=flow.flow_id, options=flow.options)


@router.post(
    "/login/verify",
    response_model=UserEnvelope,
    dependencies=[Depends(rate_limit("login_verify"))],
    responses=error_responses(401, 429),
)
async def login_verify(body: CredentialIn, db: DbSession, response: Response) -> UserEnvelope:
    user = await service.login_verify(db, body.flow_id, body.credential)
    set_auth_cookies(response, user.id)
    return _envelope(user)


@router.post(
    "/recover",
    response_model=RecoveryTokenOut,
    summary="Trade a recovery code for a short-lived token that can register a new passkey",
    dependencies=[Depends(rate_limit("recover"))],
    responses=error_responses(401, 429),
)
async def recover(body: RecoverIn, db: DbSession) -> RecoveryTokenOut:
    return RecoveryTokenOut(recovery_token=await service.recover(db, body.code))


@router.post(
    "/recover/options",
    response_model=FlowOptions,
    dependencies=[Depends(rate_limit("recover_options"))],
    responses=error_responses(401, 429),
)
async def recover_options(body: RecoveryTokenIn, db: DbSession) -> FlowOptions:
    flow = await service.recover_options(db, body.recovery_token)
    return FlowOptions(flow_id=flow.flow_id, options=flow.options)


@router.post(
    "/recover/verify",
    response_model=UserEnvelope,
    dependencies=[Depends(rate_limit("recover_verify"))],
    responses=error_responses(401, 429),
)
async def recover_verify(body: RecoverVerifyIn, db: DbSession, response: Response) -> UserEnvelope:
    user = await service.recover_verify(
        db, body.recovery_token, body.flow_id, body.credential, body.device_name
    )
    set_auth_cookies(response, user.id)
    return _envelope(user)


@router.post("/passkeys/options", response_model=FlowOptions, responses=error_responses(401))
async def passkey_options(user: CurrentUser, db: DbSession) -> FlowOptions:
    flow = await service.passkey_options(db, user)
    return FlowOptions(flow_id=flow.flow_id, options=flow.options)


@router.post(
    "/passkeys/verify",
    response_model=PasskeyOut,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 409),
)
async def passkey_verify(
    body: RegisterCredentialIn, user: CurrentUser, db: DbSession
) -> PasskeyOut:
    cred = await service.passkey_verify(db, user, body.flow_id, body.credential, body.device_name)
    return PasskeyOut.model_validate(cred)


@router.get("/passkeys", response_model=list[PasskeyOut], responses=error_responses(401))
async def list_passkeys(user: CurrentUser, db: DbSession) -> list[PasskeyOut]:
    return [PasskeyOut.model_validate(p) for p in await service.list_passkeys(db, user)]


@router.delete(
    "/passkeys/{passkey_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 404, 409),
)
async def delete_passkey(passkey_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    await service.delete_passkey(db, user, passkey_id)


@router.post(
    "/recovery-codes",
    response_model=RecoveryCodesOut,
    summary="Replace all recovery codes",
    responses=error_responses(401),
)
async def regenerate_recovery_codes(user: CurrentUser, db: DbSession) -> RecoveryCodesOut:
    return RecoveryCodesOut(recovery_codes=await service.regenerate_recovery_codes(db, user))


@router.post(
    "/refresh",
    response_model=UserEnvelope,
    summary="Rotate the session using the refresh cookie",
    responses=error_responses(401),
)
async def refresh(db: DbSession, refresh_token: RefreshCookie = None) -> Response:
    try:
        user = await service.user_from_refresh_token(db, refresh_token)
    except UnauthenticatedError as exc:
        failed = JSONResponse(error_payload(exc.code, exc.message), status_code=401)
        clear_auth_cookies(failed)
        return failed
    ok = JSONResponse(_envelope(user).model_dump(mode="json"))
    set_auth_cookies(ok, user.id)
    return ok


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, refresh_token: RefreshCookie = None) -> None:
    await service.revoke_refresh_token(refresh_token)
    clear_auth_cookies(response)


@router.get("/me", response_model=UserOut, responses=error_responses(401))
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@dev_router.post(
    "/dev-login",
    response_model=UserEnvelope,
    summary="DEV ONLY: sign in as the owner without a passkey",
)
async def dev_login(db: DbSession, response: Response) -> UserEnvelope:
    user = await service.dev_login_user(db)
    set_auth_cookies(response, user.id)
    return _envelope(user)
