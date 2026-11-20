"""Import every model so `Base.metadata` is complete (used by Alembic and tests)."""

from app.db.base import Base
from app.features.auth.models import PasskeyCredential, RecoveryCode, User
from app.features.profile.models import Education, Experience, Profile, Skill

__all__ = [
    "Base",
    "Education",
    "Experience",
    "PasskeyCredential",
    "Profile",
    "RecoveryCode",
    "Skill",
    "User",
]
