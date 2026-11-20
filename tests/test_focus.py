from datetime import UTC, datetime, timedelta

import httpx


async def test_focus_sessions(auth_client: httpx.AsyncClient) -> None:
    task = (await auth_client.post("/tasks", json={"title": "Read"})).json()
    end = datetime.now(UTC).replace(microsecond=0)
    start = end - timedelta(minutes=25)
    r = await auth_client.post(
        "/focus/sessions",
        json={
            "task_id": task["id"],
            "duration_minutes": 25,
            "started_at": start.isoformat(),
            "ended_at": end.isoformat(),
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["started_at"] == start.isoformat().replace("+00:00", "Z")
    r = await auth_client.get("/focus/sessions", params={"date": start.date().isoformat()})
    assert len(r.json()) == 1
    r = await auth_client.get("/focus/sessions", params={"date": "2001-01-01"})
    assert r.json() == []
    # same instant seen from a far-east timezone may be another local day; default=today works
    r = await auth_client.get("/focus/sessions")
    assert r.status_code == 200


async def test_focus_validation_and_ownership(
    auth_client: httpx.AsyncClient, other_user_client: httpx.AsyncClient
) -> None:
    now = datetime.now(UTC)
    r = await auth_client.post(
        "/focus/sessions",
        json={
            "duration_minutes": 25,
            "started_at": now.isoformat(),
            "ended_at": (now - timedelta(minutes=5)).isoformat(),
        },
    )
    assert r.status_code == 422
    r = await auth_client.post(
        "/focus/sessions",
        json={"duration_minutes": 0, "started_at": now.isoformat(), "ended_at": now.isoformat()},
    )
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "duration_minutes"
    task = (await auth_client.post("/tasks", json={"title": "Mine"})).json()
    r = await other_user_client.post(
        "/focus/sessions",
        json={
            "task_id": task["id"],
            "duration_minutes": 5,
            "started_at": now.isoformat(),
            "ended_at": now.isoformat(),
        },
    )
    assert r.status_code == 404 and r.json()["error"]["code"] == "TASK_NOT_FOUND"
