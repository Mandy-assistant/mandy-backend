"""Ownership helpers: another user's record is indistinguishable from a missing one (404)."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.exceptions import NotFoundError


async def get_owned_or_404[M](
    db: AsyncSession,
    model: type[M],
    obj_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    code: str = "NOT_FOUND",
    message: str = "Resource not found",
) -> M:
    id_col: InstrumentedAttribute[Any] = model.id  # type: ignore[attr-defined]
    user_col: InstrumentedAttribute[Any] = model.user_id  # type: ignore[attr-defined]
    obj = await db.scalar(
        select(model)
        .where(id_col == obj_id, user_col == user_id)
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise NotFoundError(message, code=code)
    return obj
