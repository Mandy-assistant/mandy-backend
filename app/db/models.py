"""Import every model so `Base.metadata` is complete (used by Alembic and tests)."""

from app.db.base import Base

__all__ = ["Base"]
