"""Job discovery: board adapters, ranking, regions, hide/track and the AI fit check."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ai as ai_module
from app.features.auth.models import User
from app.features.discover import service
from app.features.discover.models import JobPosting
from app.features.discover.providers import (
    AllJobBoardsProvider,
    FetchedPosting,
    hn_who_is_hiring,
    jobicy,
    parse_hn_comment,
    regions_for,
    remoteok,
    remotive,
)
from app.features.discover.router import get_jobs_provider
from app.features.profile.models import Profile, Skill, SkillLevel


class FakeAI:
    model = "fake"

    def __init__(self, result: Any = None) -> None:
        self.result = result
        self.prompts: list[str] = []

    async def generate_structured(self, *, system: str, prompt: str, schema: type) -> Any:
        self.prompts.append(prompt)
        return self.result


async def _postings(db: AsyncSession) -> dict[str, JobPosting]:
    now = datetime.now(UTC)
    specs = [
        ("py", "Senior Python Engineer", "Acme", "Bengaluru, India", False, ["india"], ["python"]),
        ("ml", "ML Engineer (LLMs)", "Brainy", "Worldwide", True, ["remote"], ["python", "ml"]),
        ("us", "Python Developer", "Yankee", "US Only", True, [], ["python"]),
        ("js", "Frontend Engineer", "Webby", "Worldwide", True, ["remote"], ["react"]),
        ("de", "Entwickler (m/w/d) Python", "Gmbh", "Berlin", False, [], ["python"]),
    ]
    out = {}
    for key, role, company, location, remote, regions, tags in specs:
        p = JobPosting(
            source="Test",
            url=f"https://jobs.test/{key}",
            company=company,
            role=role,
            location=location,
            remote=remote,
            regions=regions,
            tags=tags,
            summary=f"{role} at {company}",
            posted_at=now - timedelta(days=1),
        )
        db.add(p)
        out[key] = p
    await db.commit()
    return out


async def _profile(db: AsyncSession, user: User) -> None:
    db.add(Profile(user_id=user.id, target_roles=["Python Engineer"], headline="Backend dev"))
    db.add(Skill(user_id=user.id, name="Python", level=SkillLevel.ADVANCED))
    await db.commit()


def _roles(body: dict[str, Any]) -> list[str]:
    return [i["role"] for i in body["items"]]


async def test_discover_ranks_filters_hides_and_tracks(
    auth_client: httpx.AsyncClient, db: AsyncSession, user: User
) -> None:
    posts = await _postings(db)
    await _profile(db, user)

    body = (await auth_client.get("/jobs/discover")).json()
    assert body["total"] == 5 and body["personalizing"] is False
    roles = _roles(body)
    assert roles[0] in {"Senior Python Engineer", "Python Developer"}
    assert roles[-1] == "Entwickler (m/w/d) Python"  # non-English listings sink
    assert body["items"][0]["match_score"] > 0

    india = (await auth_client.get("/jobs/discover", params={"region": "india"})).json()
    assert _roles(india) == ["Senior Python Engineer"]
    await auth_client.put("/interests", json={"job_regions": ["remote", "india"]})
    mine = _roles((await auth_client.get("/jobs/discover")).json())
    assert set(mine) == {"Senior Python Engineer", "ML Engineer (LLMs)", "Frontend Engineer"}
    everything = (await auth_client.get("/jobs/discover", params={"region": "anywhere"})).json()
    assert everything["total"] == 5

    r = await auth_client.get("/jobs/discover", params={"q": "frontend", "region": "anywhere"})
    assert _roles(r.json()) == ["Frontend Engineer"]
    assert "frontend" in (await auth_client.get("/interests")).json()["context"]

    js = str(posts["js"].id)
    assert (await auth_client.put(f"/jobs/discover/{js}/hide")).status_code == 204
    assert "Frontend Engineer" not in _roles((await auth_client.get("/jobs/discover")).json())
    assert (await auth_client.delete(f"/jobs/discover/{js}/hide")).status_code == 204

    py = str(posts["py"].id)
    r = await auth_client.post(f"/jobs/discover/{py}/track")
    assert r.status_code == 201
    job = r.json()
    assert job["company"] == "Acme" and job["status"] == "saved"
    assert job["url"] == "https://jobs.test/py" and "Found on Test." in job["notes"]
    again = await auth_client.post(f"/jobs/discover/{py}/track")
    assert again.json()["id"] == job["id"]  # idempotent
    tracked = next(
        i for i in (await auth_client.get("/jobs/discover")).json()["items"] if i["id"] == py
    )
    assert tracked["status"] == "tracked" and tracked["job_id"] == job["id"]
    assert (await auth_client.get("/jobs")).json()["total"] == 1

    missing = "00000000-0000-0000-0000-000000000000"
    assert (await auth_client.post(f"/jobs/discover/{missing}/track")).status_code == 404


async def test_ai_fit(auth_client: httpx.AsyncClient, db: AsyncSession, user: User) -> None:
    posts = await _postings(db)
    await _profile(db, user)
    ids = await service.needs_fit(db, user.id, "anywhere")
    assert len(ids) == 5
    ml_n = ids.index(posts["ml"].id) + 1
    fake = FakeAI(
        service.RatedJobs(
            items=[
                service.RatedJob(
                    n=n,
                    fit=95 if n == ml_n else 20,
                    reason="Your Python fits." if n == ml_n else "Weak match.",
                    gaps="No LLM work yet." if n == ml_n else "",
                )
                for n in range(1, 6)
            ]
        )
    )
    assert await service.write_fits(db, user, fake, ids) == 5
    assert "Python (advanced)" in fake.prompts[0]
    assert await service.needs_fit(db, user.id, "anywhere") == []

    body = (await auth_client.get("/jobs/discover", params={"region": "anywhere"})).json()
    top = body["items"][0]
    assert top["role"] == "ML Engineer (LLMs)"
    assert top["fit"] == {"fit": 95, "reason": "Your Python fits.", "gaps": "No LLM work yet."}
    job = (await auth_client.post(f"/jobs/discover/{top['id']}/track")).json()
    assert "AI fit 95/100" in job["notes"] and "Gaps: No LLM work yet." in job["notes"]


async def test_discover_schedules_fit_when_ai_available(
    app, auth_client: httpx.AsyncClient, db: AsyncSession, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    await _postings(db)
    calls: list[Any] = []

    async def fake_run(user_id: Any, ai: Any, region: Any) -> None:
        calls.append(region)

    monkeypatch.setattr(service, "run_fits", fake_run)
    app.dependency_overrides[ai_module.get_optional_ai_client] = lambda: FakeAI()
    assert (await auth_client.get("/jobs/discover")).json()["personalizing"] is True
    assert (await auth_client.get("/jobs/discover")).json()["personalizing"] is False  # cooldown
    assert calls == [None]


async def test_refresh(app, auth_client: httpx.AsyncClient) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)

    class Provider:
        async def fetch(self) -> list[FetchedPosting]:
            return [
                FetchedPosting(
                    "Board",
                    "https://jobs.test/new",
                    "Co",
                    "Dev",
                    "India",
                    True,
                    "",
                    now,
                    regions=("india", "remote"),
                ),
                FetchedPosting(
                    "Board",
                    "https://jobs.test/old",
                    "Co",
                    "Old",
                    "",
                    True,
                    "",
                    now - timedelta(days=90),
                ),
            ]

    app.dependency_overrides[get_jobs_provider] = lambda: Provider()
    assert (await auth_client.post("/jobs/discover/refresh")).json() == {"added": 2}
    body = (await auth_client.get("/jobs/discover", params={"region": "anywhere"})).json()
    assert _roles(body) == ["Dev"]  # the 90-day-old one was pruned


# ---- adapters ----------------------------------------------------------------------------


def test_regions_for() -> None:
    assert regions_for("Bengaluru, India", False) == ("india",)
    assert regions_for("Worldwide", True) == ("remote",)
    assert regions_for("", True) == ("remote",)
    assert regions_for("APAC", True) == ("remote",)
    assert regions_for("India (Remote)", True) == ("india", "remote")
    assert regions_for("US Only", True) == ()
    assert regions_for("Berlin", False) == ()


def test_parse_hn_comment() -> None:
    assert parse_hn_comment(
        "Acme Corp | Senior Backend Engineer | Remote (Worldwide) | $150k<p>We build..."
    ) == ("Acme Corp", "Senior Backend Engineer", "Remote (Worldwide)", True)
    assert parse_hn_comment("Beta | London, UK | ONSITE | ML Engineer") == (
        "Beta",
        "ML Engineer",
        "London, UK, ONSITE",
        False,
    )
    assert parse_hn_comment("Just some reply without pipes") is None


def _boards(request: httpx.Request) -> httpx.Response:
    host = request.url.host
    if host == "remotive.com":
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "url": "https://remotive.com/j/1",
                        "title": "Python Dev",
                        "company_name": "R",
                        "candidate_required_location": "Worldwide",
                        "description": "<p>Hi</p>",
                        "publication_date": "2026-11-20T10:00:00",
                        "tags": ["python"],
                        "job_type": "full_time",
                        "salary": "$100k",
                    }
                ]
            },
        )
    if host == "remoteok.com":
        return httpx.Response(
            200,
            json=[
                {"legal": "notice"},
                {
                    "url": "https://remoteok.com/j/2",
                    "position": "Go Dev",
                    "company": "O",
                    "location": "",
                    "epoch": 1795400000,
                    "salary_min": 90000,
                    "salary_max": 120000,
                    "tags": ["go"],
                },
            ],
        )
    if host == "jobicy.com":
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "url": "https://jobicy.com/j/3",
                        "jobTitle": "AI Engineer",
                        "companyName": "J",
                        "jobGeo": "APAC",
                        "jobExcerpt": "LLMs",
                        "pubDate": "2026-11-21T10:00:00+00:00",
                        "jobIndustry": ["Engineering"],
                        "jobType": ["Full-Time"],
                        "salaryMin": 50000,
                        "salaryMax": 70000,
                        "salaryCurrency": "USD",
                    }
                ]
            },
        )
    if host == "hn.algolia.com" and "author_whoishiring" in str(request.url):
        return httpx.Response(
            200, json={"hits": [{"objectID": "77", "title": "Ask HN: Who is hiring? (Nov)"}]}
        )
    if host == "hn.algolia.com":
        return httpx.Response(
            200,
            json={
                "hits": [
                    {
                        "objectID": "78",
                        "parent_id": 77,
                        "comment_text": "Zed | Rust Engineer | Remote | Full-time<p>Join us",
                        "created_at_i": 1795400000,
                    },
                    {"objectID": "79", "parent_id": 78, "comment_text": "a | reply | here"},
                ]
            },
        )
    return httpx.Response(503)


async def test_board_adapters() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(_boards)) as client:
        r = (await remotive(client))[0]
        assert (r.role, r.regions, r.salary, r.employment_type) == (
            "Python Dev",
            ("remote",),
            "$100k",
            "full time",
        )
        o = (await remoteok(client))[0]
        assert o.salary == "$90,000-$120,000" and o.regions == ("remote",)
        j = (await jobicy(client))[0]
        assert j.salary == "USD 50,000-70,000" and j.regions == ("remote",)
        hn = await hn_who_is_hiring(client)
        assert [(p.company, p.role, p.remote) for p in hn] == [("Zed", "Rust Engineer", True)]

    async def down(client: httpx.AsyncClient) -> list[FetchedPosting]:
        raise httpx.ConnectError("down")

    provider = AllJobBoardsProvider(
        {"remotive": remotive, "down": down}, transport=httpx.MockTransport(_boards)
    )
    assert len(await provider.fetch()) == 1
