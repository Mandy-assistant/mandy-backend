"""Sources, the personal feed, likes/hides, interests and AI insights."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ai as ai_module
from app.features.auth.models import User
from app.features.news import service
from app.features.news.models import NewsCategory, NewsInsight, NewsItem, NewsKind
from app.features.news.provider import FetchedNews, RSSProvider
from app.features.news.router import get_news_provider
from app.features.news.sources import (
    AllSourcesProvider,
    classify,
    dev_to,
    github_trending,
    hacker_news,
    lobsters,
    og_image,
    reddit,
)
from app.features.profile.models import Skill, SkillLevel


class FakeAI:
    model = "fake"

    def __init__(self, result: Any = None) -> None:
        self.result = result
        self.prompts: list[str] = []

    async def generate_structured(self, *, system: str, prompt: str, schema: type) -> Any:
        self.prompts.append(prompt)
        return self.result


async def _items(db: AsyncSession) -> dict[str, NewsItem]:
    now = datetime.now(UTC)
    specs = [
        ("rust", "Rust 2.0 borrow checker rewrite", "Lobsters", ["rust"], 2, 50),
        ("react", "React compiler ships in Next.js", "DEV", ["react", "nextjs"], 3, 40),
        ("k8s", "Kubernetes 1.40 drops dockershim again", "Hacker News", ["kubernetes"], 1, 900),
        ("crypto", "Crypto exchange hacked overnight", "Hacker News", [], 1, 1200),
        ("python", "Python 3.15 makes the GIL optional by default", "DEV", ["python"], 5, 30),
    ]
    out = {}
    for key, title, source, tags, hours, score in specs:
        item = NewsItem(
            title=title,
            source=source,
            url=f"https://feed.test/{key}",
            summary=f"About {key}",
            category=NewsCategory.DEV,
            published_at=now - timedelta(hours=hours),
            score=score,
            comments=score // 10,
            tags=tags,
        )
        db.add(item)
        out[key] = item
    # pad the pool so the feed doesn't fall back to "newest overall"
    for i in range(30):
        db.add(
            NewsItem(
                title=f"Filler story {i}",
                source=f"Blog {i % 4}",
                url=f"https://feed.test/filler/{i}",
                summary="",
                category=NewsCategory.WEB,
                published_at=now - timedelta(hours=40 + i),
            )
        )
    await db.commit()
    return out


def _titles(body: dict[str, Any]) -> list[str]:
    return [i["title"] for i in body["items"]]


async def test_feed_follows_mutes_hides_and_likes(
    auth_client: httpx.AsyncClient, db: AsyncSession, user: User
) -> None:
    items = await _items(db)
    r = await auth_client.put(
        "/interests", json={"followed": ["Python", " python ", "react"], "muted": ["crypto"]}
    )
    assert r.status_code == 200
    assert r.json()["followed"] == ["python", "react"] and r.json()["muted"] == ["crypto"]

    body = (await auth_client.get("/news/feed", params={"size": 5})).json()
    top = _titles(body)[:2]
    assert set(top) == {items["python"].title, items["react"].title}
    assert items["crypto"].title not in _titles(
        (await auth_client.get("/news/feed", params={"size": 50})).json()
    )
    assert body["personalizing"] is False  # no AI configured in tests

    target = str(items["k8s"].id)
    assert (await auth_client.put(f"/news/{target}/like")).json() == {"is_liked": True}
    feed = (await auth_client.get("/news/feed", params={"size": 50})).json()
    liked = next(i for i in feed["items"] if i["id"] == target)
    assert liked["is_liked"] is True and liked["score"] == 900 and liked["tags"] == ["kubernetes"]
    assert (await auth_client.delete(f"/news/{target}/like")).json() == {"is_liked": False}

    assert (await auth_client.put(f"/news/{target}/hide")).status_code == 204
    feed = (await auth_client.get("/news/feed", params={"size": 50})).json()
    assert target not in {i["id"] for i in feed["items"]}
    assert (await auth_client.delete(f"/news/{target}/hide")).status_code == 204
    assert (await auth_client.post(f"/news/{target}/open")).status_code == 204

    r = await auth_client.put("/news/00000000-0000-0000-0000-000000000000/like")
    assert r.status_code == 404


async def test_activity_teaches_interests(
    auth_client: httpx.AsyncClient, db: AsyncSession, user: User
) -> None:
    items = await _items(db)
    db.add(Skill(user_id=user.id, name="FastAPI", level=SkillLevel.ADVANCED))
    await db.commit()
    await auth_client.put(f"/news/{items['rust'].id}/like")
    await auth_client.put(f"/news/{items['rust'].id}/save")
    await auth_client.get("/news", params={"q": "borrow checker"})
    await auth_client.get("/news", params={"q": "x"})  # too short to learn from

    body = (await auth_client.get("/interests")).json()
    learned = [t["term"] for t in body["learned"]]
    assert "rust" in learned[:3] and "fastapi" in learned and "borrow" in learned
    assert "Recent searches: borrow checker" in body["context"]
    assert "FastAPI (advanced)" in body["context"]
    assert "Rust 2.0" in body["context"]  # recently liked

    feed = (await auth_client.get("/news/feed", params={"size": 3})).json()
    assert _titles(feed)[0] == items["rust"].title


async def test_job_regions_validation(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.put("/interests", json={"job_regions": ["india", "remote", "india"]})
    assert r.json()["job_regions"] == ["india", "remote"]
    r = await auth_client.put("/interests", json={"job_regions": ["mars"]})
    assert r.status_code == 422


async def test_sources_and_filter(auth_client: httpx.AsyncClient, db: AsyncSession) -> None:
    await _items(db)
    sources = (await auth_client.get("/news/sources")).json()
    assert sources[0]["source"] in {"Hacker News", "DEV"} and sources[0]["count"] == 2
    r = await auth_client.get("/news", params={"source": "Lobsters"})
    assert _titles(r.json()) == ["Rust 2.0 borrow checker rewrite"]


async def test_ai_insights_boost_and_show(
    db: AsyncSession, user: User, auth_client: httpx.AsyncClient
) -> None:
    items = await _items(db)
    ids = await service.needs_insights(db, user.id)
    assert len(ids) == service.INSIGHT_BATCH
    crypto_n = ids.index(items["crypto"].id) + 1
    fake = FakeAI(
        service.RatedStories(
            items=[
                service.RatedStory(n=n, relevance=5, reason="Not your area.")
                for n in range(1, len(ids) + 1)
                if n != crypto_n
            ]
            + [service.RatedStory(n=crypto_n, relevance=100, reason="You asked for this.")]
        )
    )
    assert await service.write_insights(db, user, fake, ids) == len(ids)
    assert "Reader context" in fake.prompts[0]
    assert not set(await service.needs_insights(db, user.id)) & set(ids)  # never re-rated
    rows = (await db.scalars(select(NewsInsight).where(NewsInsight.user_id == user.id))).all()
    assert len(rows) == len(ids)

    feed = (await auth_client.get("/news/feed", params={"size": 1})).json()
    assert feed["items"][0]["title"] == items["crypto"].title
    assert feed["items"][0]["insight"] == {"relevance": 100, "reason": "You asked for this."}


async def test_feed_schedules_ai_when_available(
    app, auth_client: httpx.AsyncClient, db: AsyncSession, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    await _items(db)
    calls: list[Any] = []

    async def fake_run(user_id: Any, ai: Any) -> None:
        calls.append(user_id)

    monkeypatch.setattr(service, "run_insights", fake_run)
    app.dependency_overrides[ai_module.get_optional_ai_client] = lambda: FakeAI()
    first = (await auth_client.get("/news/feed")).json()
    second = (await auth_client.get("/news/feed")).json()
    assert first["personalizing"] is True and second["personalizing"] is False  # cooldown
    assert len(calls) == 1


async def test_refresh_updates_votes_and_fills_images(
    app, auth_client: httpx.AsyncClient, db: AsyncSession
) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)

    class Provider:
        def __init__(self, score: int) -> None:
            self.score = score

        async def fetch(self) -> list[FetchedNews]:
            return [
                FetchedNews(
                    "Show HN",
                    "Hacker News",
                    "https://feed.test/show",
                    "",
                    None,
                    NewsCategory.DEV,
                    now,
                    kind=NewsKind.DISCUSSION,
                    score=self.score,
                    comments=3,
                    tags=("python",),
                )
            ]

        async def preview_images(self, urls: list[str]) -> dict[str, str]:
            return dict.fromkeys(urls, "https://img.test/og.png")

    app.dependency_overrides[get_news_provider] = lambda: Provider(10)
    assert (await auth_client.post("/news/refresh")).json() == {"added": 1}
    app.dependency_overrides[get_news_provider] = lambda: Provider(250)
    assert (await auth_client.post("/news/refresh")).json() == {"added": 0}
    item = (await auth_client.get("/news")).json()["items"][0]
    assert item["score"] == 250 and item["image_url"] == "https://img.test/og.png"
    assert item["kind"] == "discussion" and item["tags"] == ["python"]


# ---- source adapters ---------------------------------------------------------------------

HN = {
    "hits": [
        {
            "objectID": "1",
            "title": "Postgres 19 released",
            "url": "https://pg.test/19",
            "points": 512,
            "num_comments": 88,
            "author": "pg",
            "created_at_i": 1795400000,
        },
        {"objectID": "2", "title": "Ask HN: what are you reading?", "url": None, "points": 5},
        {"objectID": "3", "title": None},
    ]
}
DEV = [
    {
        "title": "Building agents with Claude",
        "url": "https://dev.test/a",
        "description": "Agents 101",
        "cover_image": "https://img.test/a.png",
        "published_at": "2026-11-20T10:00:00Z",
        "public_reactions_count": 77,
        "comments_count": 4,
        "tag_list": ["ai", "python"],
        "user": {"name": "Ana"},
    }
]
LOBSTERS = [
    {
        "title": "A tiny Lisp in Rust",
        "url": "",
        "comments_url": "https://lobste.rs/s/x",
        "score": 40,
        "comment_count": 9,
        "tags": ["rust", "plt"],
        "created_at": "2026-11-21T08:00:00.000-06:00",
        "submitter_user": "bob",
    }
]
GITHUB = {
    "items": [
        {
            "full_name": "acme/fastthing",
            "html_url": "https://github.com/acme/fastthing",
            "description": "Blazing fast thing",
            "stargazers_count": 4200,
            "language": "Go",
            "topics": ["cli"],
            "created_at": "2026-11-19T00:00:00Z",
            "owner": {"login": "acme"},
        }
    ]
}


def _api(request: httpx.Request) -> httpx.Response:
    host, path = request.url.host, request.url.path
    if host == "hn.algolia.com":
        return httpx.Response(200, json=HN)
    if host == "dev.to":
        return httpx.Response(200, json=DEV)
    if host == "lobste.rs":
        return httpx.Response(200, json=LOBSTERS)
    if host == "api.github.com":
        return httpx.Response(200, json=GITHUB)
    if path == "/page":
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text='<html><head><meta property="og:image" content="//cdn.test/i.png?a=1&amp;b=2">'
            "</head><body>x</body></html>",
        )
    return httpx.Response(500)


async def test_source_adapters_normalise() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(_api)) as client:
        hn = await hacker_news(client)
        assert [i.title for i in hn] == ["Postgres 19 released", "Ask HN: what are you reading?"]
        assert hn[0].score == 512 and hn[0].category == NewsCategory.DATA
        assert hn[1].kind == NewsKind.DISCUSSION and hn[1].url.endswith("id=2")
        dev = (await dev_to(client))[0]
        assert dev.category == NewsCategory.AI and dev.image_url == "https://img.test/a.png"
        assert dev.tags == ("ai", "python") and dev.author == "Ana"
        lob = (await lobsters(client))[0]
        assert lob.url == "https://lobste.rs/s/x" and lob.kind == NewsKind.DISCUSSION
        repo = (await github_trending(client))[0]
        assert repo.kind == NewsKind.REPO and repo.score == 4200 and repo.tags == ("go", "cli")
        assert await reddit(client) == []  # not configured
        assert await og_image(client, "https://site.test/page") == "https://cdn.test/i.png?a=1&b=2"
        assert await og_image(client, "https://site.test/missing") is None


async def test_all_sources_survive_a_failing_one() -> None:
    async def broken(client: httpx.AsyncClient) -> list[FetchedNews]:
        raise RuntimeError("down")

    provider = AllSourcesProvider(
        sources={"hn": hacker_news, "broken": broken},
        rss=RSSProvider([]),
        transport=httpx.MockTransport(_api),
    )
    items = await provider.fetch()
    assert len(items) == 2
    images = await provider.preview_images(["https://site.test/page", "https://site.test/nope"])
    assert images == {"https://site.test/page": "https://cdn.test/i.png?a=1&b=2"}


def test_classify() -> None:
    assert classify("New CVE in OpenSSL") == NewsCategory.SECURITY
    assert classify("Fine-tuning Llama on a laptop") == NewsCategory.AI
    assert classify("SwiftUI tips") == NewsCategory.MOBILE
    assert classify("Hiring freeze and layoffs at BigCo") == NewsCategory.CAREER
    assert classify("Something else entirely") == NewsCategory.DEV
    assert classify("Plain title", tags=("kubernetes",)) == NewsCategory.CLOUD
