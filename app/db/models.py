"""Import every model so `Base.metadata` is complete (used by Alembic and tests)."""

from app.db.base import Base
from app.features.auth.models import PasskeyCredential, RecoveryCode, User

__all__ = ["Base", "PasskeyCredential", "RecoveryCode", "User"]
