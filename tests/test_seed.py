from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.auth.models import User
from app.features.focus.models import FocusSession
from app.features.jobs.models import Job
from app.features.news.models import NewsItem
from app.features.tasks.models import Task
from app.scripts.seed import seed
from tests.conftest import ClientFactory


async def _count(db: AsyncSession, model: type) -> int:
    return int(await db.scalar(select(func.count()).select_from(model)) or 0)


async def test_seed_idempotent_and_dashboard(db: AsyncSession, make_client: ClientFactory) -> None:
    first = await seed(db, reset=True)
    assert first["created"] is True
    counts = [await _count(db, m) for m in (User, Job, Task, NewsItem)]
    assert counts == [1, 15, 21, 40]
    focus = await _count(db, FocusSession)

    again = await seed(db)
    assert again["created"] is False
    await seed(db, reset=True)
    assert [await _count(db, m) for m in (User, Job, Task, NewsItem)] == counts
    assert abs(await _count(db, FocusSession) - focus) <= 1

    owner = await db.scalar(select(User))
    assert owner is not None and owner.display_name == "Mathan"
    client = await make_client(owner)
    body = (await client.get("/dashboard/summary", params={"tz": "Asia/Kolkata"})).json()
    assert body["owner_name"] == "Mathan"
    assert body["pipeline"] == {"saved": 3, "applied": 5, "interview": 3, "offer": 1, "rejected": 3}
    assert body["overdue_count"] == 2 and body["tasks_due_today_count"] == 3
    assert body["current_roadmap"]["title"] == "ML Engineer"
    assert body["current_roadmap"]["progress"] == 50
    assert body["current_roadmap"]["milestone_index"] == 3
    assert body["streak"]["current_days"] >= 11 and body["streak"]["best_days"] >= 21
    assert body["next_interview"]["company"] in {"Vercel", "Flipkart"}
    assert len(body["latest_news"]) == 3
    assert (await client.get("/auth/status")).json()["setup_complete"] is False
    resumes = (await client.get("/resumes")).json()
    assert len(resumes) == 2
