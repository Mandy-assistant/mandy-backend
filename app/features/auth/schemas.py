import uuid
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.shared.schemas import ORMModel, UTCDateTime


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    display_name: str
    created_at: UTCDateTime


class UserEnvelope(BaseModel):
    user: UserOut


class AuthStatus(BaseModel):
    setup_complete: bool
    owner_name: str | None
    webauthn_rp_id: str


class SetupOptionsIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=100, examples=["Mathan"])
    email: EmailStr = Field(examples=["demo@mandy.dev"])


class FlowOptions(BaseModel):
    flow_id: str
    options: dict[str, Any] = Field(
        description="py_webauthn options JSON, pass as `optionsJSON` to @simplewebauthn/browser"
    )


class CredentialIn(BaseModel):
    flow_id: str
    credential: dict[str, Any] = Field(
        description="Object returned by startRegistration/startAuthentication"
    )


class RegisterCredentialIn(CredentialIn):
    device_name: str | None = Field(default=None, max_length=100)


class SetupVerifyOut(BaseModel):
    user: UserOut
    recovery_codes: list[str]


class RecoverIn(BaseModel):
    code: str = Field(min_length=4, max_length=20, examples=["ABCD-EF12"])


class RecoveryTokenOut(BaseModel):
    recovery_token: str


class RecoveryTokenIn(BaseModel):
    recovery_token: str


class RecoverVerifyIn(RegisterCredentialIn):
    recovery_token: str


class PasskeyOut(ORMModel):
    id: uuid.UUID
    device_name: str
    transports: list[str]
    created_at: UTCDateTime
    last_used_at: UTCDateTime | None


class RecoveryCodesOut(BaseModel):
    recovery_codes: list[str]
