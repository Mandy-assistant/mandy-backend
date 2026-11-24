import uuid

import httpx

ROADMAP = {
    "title": "ML Engineer",
    "goal": "Ship ML models",
    "target_date": "2027-03-01",
    "milestones": [
        {
            "title": "Python & math",
            "status": "done",
            "resources": [{"title": "Book", "url": "https://x.dev"}],
        },
        {"title": "Classical ML", "status": "done"},
        {"title": "Deep learning", "status": "in_progress"},
        {"title": "MLOps"},
    ],
}


async def _roadmap(client: httpx.AsyncClient, body: dict | None = None) -> dict:
    r = await client.post("/roadmaps", json=body or ROADMAP)
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_detail_progress(auth_client: httpx.AsyncClient) -> None:
    rm = await _roadmap(auth_client)
    assert rm["progress"] == 50 and rm["milestone_count"] == 4 and rm["done_count"] == 2
    assert [m["position"] for m in rm["milestones"]] == [0, 1, 2, 3]
    assert rm["milestones"][0]["resources"] == [{"title": "Book", "url": "https://x.dev"}]
    listing = (await auth_client.get("/roadmaps")).json()
    assert listing[0]["progress"] == 50 and "milestones" not in listing[0]
    detail = (await auth_client.get(f"/roadmaps/{rm['id']}")).json()
    assert detail["milestones"][2]["status"] == "in_progress"

    r = await auth_client.patch(f"/roadmaps/{rm['id']}", json={"status": "paused", "title": None})
    assert r.json()["status"] == "paused" and r.json()["title"] == "ML Engineer"


async def test_milestone_crud(auth_client: httpx.AsyncClient) -> None:
    rm = await _roadmap(auth_client)
    r = await auth_client.post(
        f"/roadmaps/{rm['id']}/milestones", json={"title": "Capstone", "target_date": "2027-02-01"}
    )
    assert r.status_code == 201 and r.json()["position"] == 4
    assert r.json()["target_date"] == "2027-02-01" and r.json()["task_count"] == 0
    r = await auth_client.post(
        f"/roadmaps/{rm['id']}/milestones", json={"title": "Intro", "position": 0}
    )
    first = r.json()
    assert first["position"] == 0
    detail = (await auth_client.get(f"/roadmaps/{rm['id']}")).json()
    assert [m["title"] for m in detail["milestones"]][:2] == ["Intro", "Python & math"]

    r = await auth_client.patch(
        f"/milestones/{first['id']}", json={"status": "done", "target_date": "2027-01-01"}
    )
    assert r.json()["status"] == "done" and r.json()["target_date"] == "2027-01-01"
    assert (await auth_client.get(f"/roadmaps/{rm['id']}")).json()["done_count"] == 3

    assert (await auth_client.delete(f"/milestones/{first['id']}")).status_code == 204
    detail = (await auth_client.get(f"/roadmaps/{rm['id']}")).json()
    assert [m["position"] for m in detail["milestones"]] == [0, 1, 2, 3, 4]
    r = await auth_client.patch(f"/milestones/{first['id']}", json={"title": "x"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "MILESTONE_NOT_FOUND"


async def test_reorder(auth_client: httpx.AsyncClient) -> None:
    rm = await _roadmap(auth_client)
    other = await _roadmap(auth_client, {"title": "DSA", "milestones": [{"title": "Arrays"}]})
    ids = [m["id"] for m in rm["milestones"]]
    r = await auth_client.put(f"/roadmaps/{rm['id']}/milestones/order", json={"ids": ids[::-1]})
    assert r.status_code == 200
    assert [m["id"] for m in r.json()["milestones"]] == ids[::-1]

    bad = [ids[0], ids[1], ids[2], other["milestones"][0]["id"]]
    r = await auth_client.put(f"/roadmaps/{rm['id']}/milestones/order", json={"ids": bad})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_ORDER"
    r = await auth_client.put(f"/roadmaps/{rm['id']}/milestones/order", json={"ids": ids[:3]})
    assert r.status_code == 422
    r = await auth_client.put(
        f"/roadmaps/{rm['id']}/milestones/order", json={"ids": [ids[0], *ids[:3]]}
    )
    assert r.status_code == 422
    # unchanged after rejected reorders
    detail = (await auth_client.get(f"/roadmaps/{rm['id']}")).json()
    assert [m["id"] for m in detail["milestones"]] == ids[::-1]


async def test_delete_cascades_and_keeps_tasks(auth_client: httpx.AsyncClient) -> None:
    rm = await _roadmap(auth_client)
    ms = rm["milestones"][2]
    r = await auth_client.post("/tasks", json={"title": "CNNs", "milestone_id": ms["id"]})
    task = r.json()
    assert task["roadmap_id"] == rm["id"] and task["milestone_title"] == "Deep learning"
    detail = (await auth_client.get(f"/roadmaps/{rm['id']}")).json()
    assert detail["milestones"][2]["task_count"] == 1
    assert (await auth_client.delete(f"/roadmaps/{rm['id']}")).status_code == 204
    assert (await auth_client.get(f"/roadmaps/{rm['id']}")).status_code == 404
    assert (await auth_client.patch(f"/milestones/{ms['id']}", json={})).status_code == 404
    tasks = (await auth_client.get("/tasks")).json()
    assert len(tasks) == 1
    assert tasks[0]["roadmap_id"] is None and tasks[0]["milestone_id"] is None
    assert tasks[0]["roadmap_title"] is None


async def test_roadmap_validation(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post("/roadmaps", json={"title": "x", "status": "someday"})
    assert r.status_code == 422
    r = await auth_client.get(f"/roadmaps/{uuid.uuid4()}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "ROADMAP_NOT_FOUND"


async def test_roadmap_ownership(
    auth_client: httpx.AsyncClient, other_user_client: httpx.AsyncClient
) -> None:
    rm = await _roadmap(auth_client)
    rid, mid = rm["id"], rm["milestones"][0]["id"]
    c = other_user_client
    assert (await c.get(f"/roadmaps/{rid}")).status_code == 404
    assert (await c.patch(f"/roadmaps/{rid}", json={"title": "x"})).status_code == 404
    assert (await c.post(f"/roadmaps/{rid}/milestones", json={"title": "x"})).status_code == 404
    r = await c.put(f"/roadmaps/{rid}/milestones/order", json={"ids": [mid]})
    assert r.status_code == 404
    assert (await c.patch(f"/milestones/{mid}", json={"title": "x"})).status_code == 404
    assert (await c.delete(f"/milestones/{mid}")).status_code == 404
    assert (await c.delete(f"/roadmaps/{rid}")).status_code == 404
    assert (await c.get("/roadmaps")).json() == []
