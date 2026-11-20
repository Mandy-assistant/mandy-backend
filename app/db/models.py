"""Import every model so `Base.metadata` is complete (used by Alembic and tests)."""

from app.db.base import Base
from app.features.auth.models import PasskeyCredential, RecoveryCode, User
from app.features.profile.models import Education, Experience, Profile, Skill
from app.features.resumes.models import Resume, ResumeVersion

__all__ = [
    "Base",
    "Education",
    "Experience",
    "PasskeyCredential",
    "Profile",
    "RecoveryCode",
    "Resume",
    "ResumeVersion",
    "Skill",
    "User",
]
