import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.resumes.models import ResumeVersion

CONTENT = {
    "header": {"full_name": "M", "links": [{"label": "GitHub", "url": "https://github.com/m"}]},
    "sections": [
        {"id": "s1", "type": "summary", "title": "Summary", "text": "Hello"},
        {
            "type": "experience",
            "title": "Experience",
            "items": [{"title": "Dev", "bullets": ["x"]}],
        },
    ],
}


async def test_resume_crud_and_versions(auth_client: httpx.AsyncClient, db: AsyncSession) -> None:
    r = await auth_client.post("/resumes", json={"title": "Main", "content": CONTENT})
    assert r.status_code == 201, r.text
    resume = r.json()
    assert resume["template"] == "modern" and resume["current_version"] == 1
    assert resume["content"]["sections"][1]["items"][0]["id"]  # generated id
    rid = resume["id"]

    r = await auth_client.patch(
        f"/resumes/{rid}",
        json={"template": "classic", "content": {**CONTENT, "sections": CONTENT["sections"][:1]}},
    )
    assert r.status_code == 200 and r.json()["template"] == "classic"
    assert len(r.json()["content"]["sections"]) == 1

    v = await auth_client.post(f"/resumes/{rid}/versions")
    assert v.status_code == 201 and v.json()["version"] == 2
    versions = (await auth_client.get(f"/resumes/{rid}/versions")).json()
    assert [x["version"] for x in versions] == [2, 1]

    r = await auth_client.post(f"/resumes/{rid}/versions/1/restore")
    assert r.status_code == 200
    assert r.json()["current_version"] == 3
    assert len(r.json()["content"]["sections"]) == 2
    assert len((await auth_client.get(f"/resumes/{rid}/versions")).json()) == 3
    r = await auth_client.post(f"/resumes/{rid}/versions/99/restore")
    assert r.status_code == 404 and r.json()["error"]["code"] == "VERSION_NOT_FOUND"

    dup = (await auth_client.post(f"/resumes/{rid}/duplicate")).json()
    assert dup["title"] == "Main (copy)" and dup["current_version"] == 1
    assert len((await auth_client.get("/resumes")).json()) == 2

    assert (await auth_client.delete(f"/resumes/{rid}")).status_code == 204
    count = await db.scalar(
        select(func.count()).select_from(ResumeVersion).where(ResumeVersion.resume_id == rid)
    )
    assert count == 0
    r = await auth_client.get(f"/resumes/{rid}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "RESUME_NOT_FOUND"


async def test_resume_content_validation(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post(
        "/resumes",
        json={"title": "X", "content": {"sections": [{"type": "hobbies", "title": "H"}]}},
    )
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["field"] == "content.sections.0.type"
    r = await auth_client.post("/resumes", json={"title": ""})
    assert r.status_code == 422


async def test_resume_from_profile(auth_client: httpx.AsyncClient) -> None:
    await auth_client.put(
        "/profile",
        json={"headline": "ML Eng", "summary": "Sum", "links": {"github": "https://g.com/m"}},
    )
    await auth_client.post(
        "/profile/experience",
        json={
            "company": "Acme",
            "title": "Dev",
            "start_date": "2022-01-01",
            "current": True,
            "highlights": ["Shipped"],
        },
    )
    await auth_client.post(
        "/profile/education",
        json={
            "school": "AU",
            "degree": "B.E.",
            "field": "CS",
            "start_date": "2016-01-01",
            "end_date": "2020-01-01",
            "grade": "8.1",
        },
    )
    await auth_client.post("/profile/skills", json={"name": "Python", "category": "language"})
    r = await auth_client.post(
        "/resumes/from-profile", json={"title": "Auto", "template": "classic"}
    )
    assert r.status_code == 201, r.text
    content = r.json()["content"]
    assert content["header"]["headline"] == "ML Eng"
    assert content["header"]["links"] == [{"label": "Github", "url": "https://g.com/m"}]
    sections = {s["type"]: s for s in content["sections"]}
    assert sections["summary"]["text"] == "Sum"
    exp = sections["experience"]["items"][0]
    assert (
        exp["subtitle"] == "Acme" and exp["end_date"] == "Present" and exp["bullets"] == ["Shipped"]
    )
    assert sections["education"]["items"][0]["title"] == "B.E. CS"
    assert sections["skills"]["items"][0]["tags"] == ["Python"]
    assert sections["projects"]["visible"] is False


async def test_resume_ownership(
    auth_client: httpx.AsyncClient, other_user_client: httpx.AsyncClient
) -> None:
    rid = (await auth_client.post("/resumes", json={"title": "Mine"})).json()["id"]
    assert (await other_user_client.get(f"/resumes/{rid}")).status_code == 404
    assert (
        await other_user_client.patch(f"/resumes/{rid}", json={"title": "x"})
    ).status_code == 404
    assert (await other_user_client.delete(f"/resumes/{rid}")).status_code == 404
    assert (await other_user_client.post(f"/resumes/{rid}/duplicate")).status_code == 404
    assert (await other_user_client.get(f"/resumes/{rid}/versions")).status_code == 404
    assert (await other_user_client.post(f"/resumes/{rid}/versions")).status_code == 404
    assert (await other_user_client.post(f"/resumes/{rid}/versions/1/restore")).status_code == 404
    assert (await other_user_client.get("/resumes")).json() == []
