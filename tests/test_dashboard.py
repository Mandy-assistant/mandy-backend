from datetime import UTC, date, datetime, timedelta

import httpx

from app.features.dashboard.service import compute_streak


def test_compute_streak() -> None:
    today = date(2026, 11, 20)
    counts = {today - timedelta(days=i): 1 for i in range(3)}  # today, -1, -2
    counts.update({today - timedelta(days=i): 2 for i in range(10, 16)})  # 6-day run
    assert compute_streak(counts, today) == (3, 6)
    # no activity today yet: streak still counts from yesterday
    del counts[today]
    assert compute_streak(counts, today) == (2, 6)
    assert compute_streak({}, today) == (0, 0)


async def test_summary_empty(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.get("/dashboard/summary")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["owner_name"] == "Owner"
    assert body["active_applications"] == 0 and body["next_interview"] is None
    assert body["pipeline"] == {"saved": 0, "applied": 0, "interview": 0, "offer": 0, "rejected": 0}
    assert body["current_roadmap"] is None and body["focus_task"] is None
    assert len(body["streak"]["heatmap"]) == 105
    assert body["streak"]["current_days"] == 0 and body["timeline"] == []


async def test_summary_with_data_and_invalidation(auth_client: httpx.AsyncClient) -> None:
    c = auth_client
    now = datetime.now(UTC)
    today = now.date()
    for status in ("saved", "applied", "applied", "offer", "rejected"):
        await c.post("/jobs", json={"company": f"C-{status}", "role": "Eng", "status": status})
    interview_at = (now + timedelta(hours=1)).isoformat()
    await c.post(
        "/jobs",
        json={
            "company": "Vercel",
            "role": "FE",
            "status": "interview",
            "interview_at": interview_at,
        },
    )
    rm = (
        await c.post(
            "/roadmaps",
            json={
                "title": "DSA Practice",
                "milestones": [
                    {"title": "Arrays", "status": "done"},
                    {"title": "Trees", "status": "in_progress"},
                    {"title": "DP"},
                ],
            },
        )
    ).json()
    t_high = (
        await c.post(
            "/tasks",
            json={
                "title": "Graphs",
                "priority": "high",
                "due_date": str(today),
                "roadmap_id": rm["id"],
            },
        )
    ).json()
    await c.post("/tasks", json={"title": "Low today", "priority": "low", "due_date": str(today)})
    await c.post("/tasks", json={"title": "Late", "due_date": str(today - timedelta(days=2))})
    await c.post("/tasks", json={"title": "Later", "due_date": str(today + timedelta(days=2))})
    done = (await c.post("/tasks", json={"title": "Done", "due_date": str(today)})).json()
    await c.post(f"/tasks/{done['id']}/complete")
    start = now - timedelta(minutes=30)
    if start.date() == today:
        await c.post(
            "/focus/sessions",
            json={
                "task_id": t_high["id"],
                "duration_minutes": 25,
                "started_at": start.isoformat(),
                "ended_at": now.isoformat(),
            },
        )

    body = (await c.get("/dashboard/summary")).json()
    assert body["pipeline"] == {"saved": 1, "applied": 2, "interview": 1, "offer": 1, "rejected": 1}
    assert body["active_applications"] == 4
    assert body["next_interview"]["company"] == "Vercel"
    assert body["tasks_due_today_count"] == 2
    assert [t["title"] for t in body["tasks_due_today"]] == ["Graphs", "Low today"]
    assert body["overdue_count"] == 1 and body["completed_today"] == 1
    assert body["focus_task"]["title"] == "Graphs" and body["up_next"]["title"] == "Late"
    cr = body["current_roadmap"]
    assert cr["title"] == "DSA Practice" and cr["progress"] == 33
    assert cr["milestone_index"] == 2 and cr["milestone_count"] == 3
    assert cr["next_milestone"]["title"] == "Trees"
    assert body["streak"]["current_days"] >= 1
    assert body["streak"]["heatmap"][-1]["date"] == str(today)
    kinds = {e["title"]: e for e in body["timeline"]}
    assert kinds["Graphs"]["kind"] == "practice" and kinds["Graphs"]["time"] is None
    assert kinds["Done"]["done"] is True
    assert any(e["kind"] == "job" for e in body["timeline"])

    # cached, but invalidated on writes
    await c.post("/jobs", json={"company": "New", "role": "x", "status": "applied"})
    body2 = (await c.get("/dashboard/summary")).json()
    assert body2["active_applications"] == 5
    await c.post(f"/tasks/{t_high['id']}/complete")
    body3 = (await c.get("/dashboard/summary")).json()
    assert body3["completed_today"] == 2 and body3["tasks_due_today_count"] == 1


async def test_summary_isolated_per_user(
    auth_client: httpx.AsyncClient, other_user_client: httpx.AsyncClient
) -> None:
    await auth_client.post("/jobs", json={"company": "A", "role": "B", "status": "applied"})
    other = (await other_user_client.get("/dashboard/summary")).json()
    assert other["active_applications"] == 0 and other["owner_name"] == "Other"


async def test_summary_tz_validation(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.get("/dashboard/summary", params={"tz": "Nowhere/City"})
    assert r.status_code == 422
    r = await auth_client.get("/dashboard/summary", params={"tz": "Asia/Kolkata"})
    assert r.status_code == 200


async def test_summary_accepts_legacy_timezone_alias(auth_client: httpx.AsyncClient) -> None:
    # Chrome reports "Asia/Calcutta"; Postgres rejects it inside timezone().
    await auth_client.post(
        "/focus/sessions",
        json={
            "duration_minutes": 25,
            "started_at": "2026-11-20T04:00:00Z",
            "ended_at": "2026-11-20T04:25:00Z",
        },
    )
    r = await auth_client.get("/dashboard/summary", params={"tz": "Asia/Calcutta"})
    assert r.status_code == 200, r.text


def test_canonical_tz_name() -> None:
    from app.shared.timeutil import canonical_tz_name, parse_tz

    assert canonical_tz_name("Asia/Calcutta") == "Asia/Kolkata"
    assert canonical_tz_name("Europe/Kiev") == "Europe/Kyiv"
    assert canonical_tz_name("Asia/Kolkata") == "Asia/Kolkata"
    assert parse_tz("Asia/Calcutta").key == "Asia/Kolkata"
