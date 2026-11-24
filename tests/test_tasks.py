from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

EAST = "Pacific/Kiritimati"  # UTC+14
WEST = "Pacific/Pago_Pago"  # UTC-11


def _local_today(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz))


async def _task(client: httpx.AsyncClient, **kw: object) -> dict:
    r = await client.post("/tasks", json={"title": "Study", **kw})
    assert r.status_code == 201, r.text
    return r.json()


async def test_task_crud_and_complete(auth_client: httpx.AsyncClient) -> None:
    t = await _task(auth_client, description="d")
    assert t["priority"] == "medium" and t["status"] == "todo" and t["completed_at"] is None
    r = await auth_client.patch(f"/tasks/{t['id']}", json={"priority": "high", "title": None})
    assert r.json()["priority"] == "high" and r.json()["title"] == "Study"
    r = await auth_client.post(f"/tasks/{t['id']}/complete")
    assert r.json()["status"] == "done" and r.json()["completed_at"].endswith("Z")
    first_completed = r.json()["completed_at"]
    r = await auth_client.post(f"/tasks/{t['id']}/complete")  # idempotent
    assert r.json()["completed_at"] == first_completed
    r = await auth_client.post(f"/tasks/{t['id']}/reopen")
    assert r.json()["status"] == "todo" and r.json()["completed_at"] is None
    assert (await auth_client.delete(f"/tasks/{t['id']}")).status_code == 204
    r = await auth_client.post(f"/tasks/{t['id']}/complete")
    assert r.status_code == 404 and r.json()["error"]["code"] == "TASK_NOT_FOUND"


async def test_task_validation(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post("/tasks", json={"title": "", "priority": "urgent"})
    assert r.status_code == 422
    assert {d["field"] for d in r.json()["error"]["details"]} == {"title", "priority"}
    r = await auth_client.get("/tasks", params={"filter": "someday"})
    assert r.status_code == 422
    r = await auth_client.get("/tasks", params={"tz": "Mars/Base"})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "tz"


async def test_filters_respect_timezone(auth_client: httpx.AsyncClient) -> None:
    east_today = _local_today(EAST).date()
    west_today = _local_today(WEST).date()
    assert east_today > west_today  # 25h apart: always different calendar days
    t = await _task(auth_client, title="East today", due_date=east_today.isoformat())

    async def ids(flt: str, tz: str) -> list[str]:
        r = await auth_client.get("/tasks", params={"filter": flt, "tz": tz})
        assert r.status_code == 200
        return [x["id"] for x in r.json()]

    assert await ids("today", EAST) == [t["id"]]
    assert await ids("upcoming", WEST) == [t["id"]]
    assert await ids("today", WEST) == []
    # due "yesterday" in the east is still today/upcoming in the west
    y = await _task(
        auth_client, title="East yesterday", due_date=(east_today - timedelta(days=1)).isoformat()
    )
    assert y["id"] in await ids("overdue", EAST)
    assert y["id"] not in await ids("overdue", WEST)


async def test_filters_and_ordering(auth_client: httpx.AsyncClient) -> None:
    today = datetime.now(ZoneInfo("UTC")).date()
    low = await _task(auth_client, title="low today", priority="low", due_date=str(today))
    high = await _task(auth_client, title="high today", priority="high", due_date=str(today))
    over = await _task(auth_client, title="overdue", due_date=str(today - timedelta(days=2)))
    up = await _task(auth_client, title="upcoming", due_date=str(today + timedelta(days=3)))
    none = await _task(auth_client, title="no date")
    done = await _task(auth_client, title="done", due_date=str(today))
    await auth_client.post(f"/tasks/{done['id']}/complete")

    async def titles(**params: str) -> list[str]:
        r = await auth_client.get("/tasks", params=params)
        return [x["title"] for x in r.json()]

    assert await titles(filter="today") == ["high today", "low today"]
    assert await titles(filter="overdue") == ["overdue"]
    assert await titles(filter="upcoming") == ["upcoming"]
    assert await titles(filter="completed") == ["done"]
    assert await titles(priority="high") == ["high today"]
    everything = await titles()
    assert everything == ["overdue", "high today", "low today", "upcoming", "no date", "done"]
    assert {low["id"], high["id"], over["id"], up["id"], none["id"]}


async def test_roadmap_links(
    auth_client: httpx.AsyncClient, other_user_client: httpx.AsyncClient
) -> None:
    rm = (
        await auth_client.post(
            "/roadmaps", json={"title": "ML", "milestones": [{"title": "A"}, {"title": "B"}]}
        )
    ).json()
    rm2 = (
        await auth_client.post(
            "/roadmaps", json={"title": "DSA", "milestones": [{"title": "Arrays"}]}
        )
    ).json()
    m_a, m_b = rm["milestones"][0]["id"], rm["milestones"][1]["id"]
    t = await _task(auth_client, roadmap_id=rm["id"], milestone_id=m_a)
    assert t["roadmap_title"] == "ML" and t["milestone_title"] == "A"

    r = await auth_client.get("/tasks", params={"roadmap_id": rm["id"]})
    assert len(r.json()) == 1
    r = await auth_client.get("/tasks", params={"milestone_id": m_b})
    assert r.json() == []

    r = await auth_client.patch(f"/tasks/{t['id']}", json={"milestone_id": m_b})
    assert r.json()["milestone_title"] == "B" and r.json()["roadmap_id"] == rm["id"]
    # moving to another roadmap drops the old milestone
    r = await auth_client.patch(f"/tasks/{t['id']}", json={"roadmap_id": rm2["id"]})
    assert r.json()["roadmap_title"] == "DSA" and r.json()["milestone_id"] is None
    r = await auth_client.patch(
        f"/tasks/{t['id']}", json={"roadmap_id": rm2["id"], "milestone_id": m_a}
    )
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "milestone_id"
    r = await auth_client.patch(f"/tasks/{t['id']}", json={"roadmap_id": None})
    assert r.json()["roadmap_id"] is None

    # cannot link to another user's roadmap / milestone
    r = await other_user_client.post("/tasks", json={"title": "x", "roadmap_id": rm["id"]})
    assert r.status_code == 404 and r.json()["error"]["code"] == "ROADMAP_NOT_FOUND"
    r = await other_user_client.post("/tasks", json={"title": "x", "milestone_id": m_a})
    assert r.status_code == 404 and r.json()["error"]["code"] == "MILESTONE_NOT_FOUND"


async def test_task_ownership(
    auth_client: httpx.AsyncClient, other_user_client: httpx.AsyncClient
) -> None:
    t = await _task(auth_client)
    c = other_user_client
    assert (await c.patch(f"/tasks/{t['id']}", json={"title": "x"})).status_code == 404
    assert (await c.post(f"/tasks/{t['id']}/complete")).status_code == 404
    assert (await c.post(f"/tasks/{t['id']}/reopen")).status_code == 404
    assert (await c.delete(f"/tasks/{t['id']}")).status_code == 404
    assert (await c.get("/tasks")).json() == []
