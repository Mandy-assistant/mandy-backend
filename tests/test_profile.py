import httpx


async def test_profile_get_and_update(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.get("/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["full_name"] == "Owner" and body["experience"] == []
    assert body["links"] == {"github": None, "linkedin": None, "portfolio": None, "website": None}
    start = body["completeness"]

    r = await auth_client.put(
        "/profile",
        json={
            "full_name": "Mathan K",
            "headline": "ML Engineer",
            "summary": "Builds things",
            "links": {"github": "https://github.com/m"},
            "target_roles": ["ML Engineer"],
            "preferences": {"locations": ["Chennai"], "work_modes": ["remote"], "salary_min": 10},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["full_name"] == "Mathan K" and body["headline"] == "ML Engineer"
    assert body["links"]["github"] == "https://github.com/m"
    assert body["preferences"]["work_modes"] == ["remote"]
    assert body["preferences"]["currency"] == "INR"
    assert body["completeness"] > start
    assert (await auth_client.get("/auth/me")).json()["display_name"] == "Mathan K"


async def test_profile_validation(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.put("/profile", json={"preferences": {"work_modes": ["moon"]}})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert err["details"][0]["field"] == "preferences.work_modes.0"
    r = await auth_client.put(
        "/profile", json={"preferences": {"salary_min": 20, "salary_max": 10}}
    )
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["field"] == "preferences.salary_max"


async def test_profile_email_conflict(
    auth_client: httpx.AsyncClient, other_user_client: httpx.AsyncClient
) -> None:
    r = await auth_client.put("/profile", json={"email": "other@example.com"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "EMAIL_TAKEN"


async def test_experience_crud(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/profile/experience",
        json={"company": "Acme", "title": "Dev", "start_date": "2022-01-01", "highlights": ["a"]},
    )
    assert r.status_code == 201, r.text
    exp = r.json()
    assert exp["current"] is False and exp["end_date"] is None
    r = await auth_client.patch(f"/profile/experience/{exp['id']}", json={"end_date": "2021-01-01"})
    assert r.status_code == 422
    assert r.json()["error"]["details"] == [
        {"field": "end_date", "message": "end_date must be on or after start_date"}
    ]
    r = await auth_client.patch(
        f"/profile/experience/{exp['id']}", json={"end_date": "2023-01-01", "company": None}
    )
    assert r.status_code == 200 and r.json()["company"] == "Acme"
    assert len((await auth_client.get("/profile/experience")).json()) == 1
    assert len((await auth_client.get("/profile")).json()["experience"]) == 1
    assert (await auth_client.delete(f"/profile/experience/{exp['id']}")).status_code == 204
    r = await auth_client.delete(f"/profile/experience/{exp['id']}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "EXPERIENCE_NOT_FOUND"


async def test_experience_create_invalid_dates(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/profile/experience",
        json={"company": "A", "title": "B", "start_date": "2022-01-01", "end_date": "2020-01-01"},
    )
    assert r.status_code == 422
    r = await auth_client.post("/profile/experience", json={"company": "A"})
    assert r.status_code == 422
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert fields == {"title", "start_date"}


async def test_education_and_skills(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/profile/education",
        json={
            "school": "Anna University",
            "degree": "B.E.",
            "start_date": "2016-06-01",
            "end_date": "2020-05-01",
            "grade": "8.4",
        },
    )
    assert r.status_code == 201
    edu = r.json()
    r = await auth_client.patch(f"/profile/education/{edu['id']}", json={"grade": "8.6"})
    assert r.json()["grade"] == "8.6"
    assert len((await auth_client.get("/profile/education")).json()) == 1

    r = await auth_client.post(
        "/profile/skills", json={"name": "Python", "level": "advanced", "category": "language"}
    )
    assert r.status_code == 201
    skill = r.json()
    r = await auth_client.post("/profile/skills", json={"name": "X", "level": "guru"})
    assert r.status_code == 422
    r = await auth_client.patch(f"/profile/skills/{skill['id']}", json={"category": "ml"})
    assert r.json()["category"] == "ml"
    assert [s["name"] for s in (await auth_client.get("/profile/skills")).json()] == ["Python"]
    assert (await auth_client.delete(f"/profile/skills/{skill['id']}")).status_code == 204
    assert (await auth_client.delete(f"/profile/education/{edu['id']}")).status_code == 204


async def test_profile_ownership(
    auth_client: httpx.AsyncClient, other_user_client: httpx.AsyncClient
) -> None:
    exp = (
        await auth_client.post(
            "/profile/experience", json={"company": "A", "title": "B", "start_date": "2022-01-01"}
        )
    ).json()
    skill = (await auth_client.post("/profile/skills", json={"name": "Go"})).json()
    edu = (
        await auth_client.post(
            "/profile/education", json={"school": "S", "start_date": "2010-01-01"}
        )
    ).json()
    for path in (
        f"/profile/experience/{exp['id']}",
        f"/profile/skills/{skill['id']}",
        f"/profile/education/{edu['id']}",
    ):
        assert (await other_user_client.patch(path, json={})).status_code == 404
        assert (await other_user_client.delete(path)).status_code == 404
    assert (await other_user_client.get("/profile/experience")).json() == []
    assert (await other_user_client.get("/profile")).json()["skills"] == []


async def test_profile_requires_auth(client: httpx.AsyncClient) -> None:
    r = await client.get("/profile")
    assert r.status_code == 401
