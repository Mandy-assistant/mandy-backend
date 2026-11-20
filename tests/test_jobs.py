import httpx


async def _job(client: httpx.AsyncClient, **kw: object) -> dict:
    payload = {"company": "Acme", "role": "Engineer", **kw}
    r = await client.post("/jobs", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_get_update_delete(auth_client: httpx.AsyncClient) -> None:
    job = await _job(
        auth_client,
        tags=["remote"],
        salary_min=10,
        salary_max=20,
        interview_at="2026-11-27T11:00:00+05:30",
    )
    assert job["status"] == "saved" and job["currency"] == "INR" and job["position"] == 0
    assert job["interview_at"] == "2026-11-27T05:30:00Z"
    assert job["created_at"].endswith("Z")
    r = await auth_client.get(f"/jobs/{job['id']}")
    assert r.status_code == 200
    r = await auth_client.patch(f"/jobs/{job['id']}", json={"notes": "hi", "company": None})
    assert r.json()["notes"] == "hi" and r.json()["company"] == "Acme"
    r = await auth_client.patch(f"/jobs/{job['id']}", json={"salary_max": 5})
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["field"] == "salary_max"
    assert (await auth_client.delete(f"/jobs/{job['id']}")).status_code == 204
    r = await auth_client.get(f"/jobs/{job['id']}")
    assert r.status_code == 404
    assert r.json() == {
        "error": {"code": "JOB_NOT_FOUND", "message": "Job not found", "details": []}
    }


async def test_validation_errors(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post("/jobs", json={"company": "A", "role": "B", "salary_min": -1})
    assert r.status_code == 422
    assert r.json()["error"]["details"] == [
        {"field": "salary_min", "message": "Input should be greater than or equal to 0"}
    ]
    r = await auth_client.post(
        "/jobs", json={"company": "A", "role": "B", "salary_min": 9, "salary_max": 1}
    )
    assert r.status_code == 422
    r = await auth_client.post("/jobs", json={"company": "A", "role": "B", "status": "ghosted"})
    assert r.status_code == 422
    r = await auth_client.get("/jobs?sort=salary")
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "sort"
    r = await auth_client.get("/jobs/not-a-uuid")
    assert r.status_code == 422


async def test_status_change_and_timeline(auth_client: httpx.AsyncClient) -> None:
    job = await _job(auth_client)
    r = await auth_client.patch(f"/jobs/{job['id']}/status", json={"status": "applied"})
    assert r.status_code == 200
    assert r.json()["status"] == "applied" and r.json()["applied_at"] is not None
    r = await auth_client.patch(
        f"/jobs/{job['id']}/status", json={"status": "interview", "position": 3}
    )
    assert r.json()["position"] == 0  # clamped: the column is empty
    # same status, only position
    r = await auth_client.patch(
        f"/jobs/{job['id']}/status", json={"status": "interview", "position": 1}
    )
    assert r.json()["position"] == 0
    # status through generic PATCH also records an event
    r = await auth_client.patch(f"/jobs/{job['id']}", json={"status": "offer"})
    assert r.json()["status"] == "offer"
    events = (await auth_client.get(f"/jobs/{job['id']}/timeline")).json()
    assert [(e["from_status"], e["to_status"]) for e in events] == [
        (None, "saved"),
        ("saved", "applied"),
        ("applied", "interview"),
        ("interview", "offer"),
    ]


async def test_created_as_applied_sets_date(auth_client: httpx.AsyncClient) -> None:
    job = await _job(auth_client, status="applied")
    assert job["applied_at"] is not None
    job2 = await _job(auth_client, status="applied", applied_at="2026-01-02")
    assert job2["applied_at"] == "2026-01-02" and job2["position"] == 0  # new jobs go on top


async def test_filter_search_sort_paginate(auth_client: httpx.AsyncClient) -> None:
    for company, role, status in [
        ("Vercel", "Frontend Engineer", "interview"),
        ("Razorpay", "Frontend Engineer", "offer"),
        ("Amazon", "SDE II", "rejected"),
        ("Zomato", "Backend Engineer", "applied"),
        ("Swiggy", "Frontend Dev", "applied"),
        ("100%_Pure", "ML Engineer", "saved"),
    ]:
        await _job(auth_client, company=company, role=role, status=status)

    r = await auth_client.get("/jobs", params={"q": "frontend", "sort": "company", "size": 2})
    body = r.json()
    assert body["total"] == 3 and body["pages"] == 2 and body["size"] == 2 and body["page"] == 1
    assert [j["company"] for j in body["items"]] == ["Razorpay", "Swiggy"]
    r = await auth_client.get(
        "/jobs", params={"q": "frontend", "sort": "company", "size": 2, "page": 2}
    )
    assert [j["company"] for j in r.json()["items"]] == ["Vercel"]

    r = await auth_client.get("/jobs", params={"status": "applied", "sort": "-company"})
    assert [j["company"] for j in r.json()["items"]] == ["Zomato", "Swiggy"]
    r = await auth_client.get("/jobs", params={"q": "%_"})
    assert [j["company"] for j in r.json()["items"]] == ["100%_Pure"]
    r = await auth_client.get("/jobs")
    assert r.json()["total"] == 6
    r = await auth_client.get("/jobs", params={"size": 201})
    assert r.status_code == 422
    r = await auth_client.get("/jobs", params={"page": 9})
    assert r.json()["items"] == [] and r.json()["total"] == 6


async def test_jobs_ownership(
    auth_client: httpx.AsyncClient, other_user_client: httpx.AsyncClient
) -> None:
    job = await _job(auth_client)
    jid = job["id"]
    assert (await other_user_client.get(f"/jobs/{jid}")).status_code == 404
    assert (await other_user_client.patch(f"/jobs/{jid}", json={"notes": "x"})).status_code == 404
    r = await other_user_client.patch(f"/jobs/{jid}/status", json={"status": "offer"})
    assert r.status_code == 404
    assert (await other_user_client.get(f"/jobs/{jid}/timeline")).status_code == 404
    assert (await other_user_client.delete(f"/jobs/{jid}")).status_code == 404
    assert (await other_user_client.get("/jobs")).json()["total"] == 0
    assert (await auth_client.get(f"/jobs/{jid}")).json()["notes"] is None


async def test_jobs_unauthenticated(client: httpx.AsyncClient) -> None:
    r = await client.get("/jobs")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_board_positions_are_contiguous(auth_client: httpx.AsyncClient) -> None:
    async def column(status: str) -> list[str]:
        r = await auth_client.get("/jobs", params={"status": status, "sort": "position"})
        items = r.json()["items"]
        assert [j["position"] for j in items] == list(range(len(items)))
        return [j["company"] for j in items]

    ids = {}
    for name in ("A", "B", "C"):
        ids[name] = (await _job(auth_client, company=name, status="applied"))["id"]
    assert await column("applied") == ["C", "B", "A"]  # newest on top
    x = await _job(auth_client, company="X", status="interview")
    ids["X"] = x["id"]

    # move B into interview at index 1 -> source column closes the gap
    r = await auth_client.patch(
        f"/jobs/{ids['B']}/status", json={"status": "interview", "position": 1}
    )
    assert r.json()["position"] == 1
    assert await column("interview") == ["X", "B"]
    assert await column("applied") == ["C", "A"]
    # omitted position -> top
    await auth_client.patch(f"/jobs/{ids['A']}/status", json={"status": "interview"})
    assert await column("interview") == ["A", "X", "B"]
    # reorder within a column
    await auth_client.patch(f"/jobs/{ids['A']}/status", json={"status": "interview", "position": 2})
    assert await column("interview") == ["X", "B", "A"]
    await auth_client.patch(f"/jobs/{ids['A']}", json={"position": 0})
    assert await column("interview") == ["A", "X", "B"]
    # delete closes the gap
    await auth_client.delete(f"/jobs/{ids['X']}")
    assert await column("interview") == ["A", "B"]
    await _job(auth_client, company="Y", status="interview", position=1)
    assert await column("interview") == ["A", "Y", "B"]
    r = await auth_client.get("/jobs", params={"sort": "-position"})
    assert r.status_code == 200
