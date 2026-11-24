"""API news sources (Hacker News, DEV, Lobsters, GitHub, Reddit) and the combined provider.

Every source is best-effort: one that is down, rate-limited or not configured returns nothing and
the others still come through.
"""

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, TypeGuard

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.features.news.models import NewsCategory, NewsKind
from app.features.news.provider import FetchedNews, RSSProvider, parse_date
from app.shared.text import clean_text, normalise_tag, token_set, words

log = get_logger(__name__)

USER_AGENT = "MandyNewsBot/1.0 (+personal tech news reader)"

# Keyword -> category, checked in order (first hit wins). Tokens come from title, summary, tags.
_CATEGORY_KEYWORDS: list[tuple[NewsCategory, frozenset[str]]] = [
    (
        NewsCategory.SECURITY,
        words(
            "security vulnerability vulnerabilities cve exploit malware ransomware breach "
            "phishing zero-day 0day xss csrf auth oauth encryption cryptography backdoor"
        ),
    ),
    (
        NewsCategory.AI,
        words(
            "ai llm llms gpt gpt-5 openai anthropic claude gemini llama mistral ml "
            "machine-learning deep-learning neural transformer transformers diffusion rag "
            "agent agents agentic embeddings pytorch tensorflow huggingface inference "
            "fine-tuning finetuning prompt chatgpt copilot model models"
        ),
    ),
    (
        NewsCategory.CAREER,
        words(
            "career interview interviews hiring layoffs layoff salary salaries resume "
            "promotion manager engineering-manager burnout job-market"
        ),
    ),
    (
        NewsCategory.MOBILE,
        words("android ios swift swiftui kotlin flutter react-native mobile iphone xcode"),
    ),
    (
        NewsCategory.CLOUD,
        words(
            "aws azure gcp cloud kubernetes k8s docker container containers serverless "
            "terraform devops sre infrastructure cloudflare lambda observability"
        ),
    ),
    (
        NewsCategory.DATA,
        words(
            "database databases postgres postgresql sql sqlite mysql data analytics "
            "warehouse duckdb spark kafka etl pandas clickhouse redis"
        ),
    ),
    (
        NewsCategory.WEB,
        words(
            "javascript typescript react next.js nextjs vue svelte css html web browser "
            "frontend node.js nodejs deno bun webassembly wasm chrome firefox safari"
        ),
    ),
]


def classify(*texts: str | None, tags: tuple[str, ...] = ()) -> NewsCategory:
    found = token_set(*texts) | {normalise_tag(t) for t in tags}
    for category, keywords in _CATEGORY_KEYWORDS:
        if found & keywords:
            return category
    return NewsCategory.DEV


def _ts(value: Any) -> datetime:
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, UTC)
    parsed = parse_date(str(value)) if value else None
    return parsed or datetime.now(UTC)


def _item(
    *,
    title: str,
    url: str,
    source: str,
    summary: str = "",
    image_url: str | None = None,
    published_at: datetime | None = None,
    kind: NewsKind = NewsKind.ARTICLE,
    score: int = 0,
    comments: int = 0,
    discussion_url: str | None = None,
    author: str | None = None,
    tags: tuple[str, ...] = (),
    category: NewsCategory | None = None,
) -> FetchedNews:
    clean_tags = tuple(dict.fromkeys(normalise_tag(t) for t in tags if t))[:10]
    summary = clean_text(summary)
    return FetchedNews(
        title=clean_text(title, 500),
        source=source,
        url=url[:1000],
        summary=summary,
        image_url=image_url[:1000] if image_url else None,
        category=category or classify(title, summary, tags=clean_tags),
        published_at=published_at or datetime.now(UTC),
        kind=kind,
        score=max(0, int(score or 0)),
        comments=max(0, int(comments or 0)),
        discussion_url=discussion_url[:1000] if discussion_url else None,
        author=author[:200] if author else None,
        tags=clean_tags,
    )


def _valid_url(url: Any) -> TypeGuard[str]:
    return isinstance(url, str) and url.startswith(("http://", "https://"))


_OG_IMAGE_RE = re.compile(
    r"<meta[^>]+(?:property|name)=[\"'](?:og:image|twitter:image)(?::src)?[\"'][^>]*>", re.I
)
_CONTENT_RE = re.compile(r"content=[\"']([^\"']+)[\"']", re.I)
MAX_HEAD_BYTES = 150_000


async def og_image(client: httpx.AsyncClient, url: str) -> str | None:
    """The page's og:image, reading only the start of the HTML."""
    async with client.stream("GET", url) as r:
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return None
        head = b""
        async for chunk in r.aiter_bytes():
            head += chunk
            if len(head) >= MAX_HEAD_BYTES or b"</head>" in head.lower():
                break
    text = head.decode("utf-8", errors="ignore")
    for tag in _OG_IMAGE_RE.findall(text):
        found = _CONTENT_RE.search(tag)
        if found:
            image = found.group(1).replace("&amp;", "&")
            if image.startswith("//"):
                image = "https:" + image
            if _valid_url(image):
                return image[:1000]
    return None


# ---- sources -------------------------------------------------------------------------------

Fetcher = Callable[[httpx.AsyncClient], Awaitable[list[FetchedNews]]]


async def hacker_news(client: httpx.AsyncClient) -> list[FetchedNews]:
    r = await client.get(
        "https://hn.algolia.com/api/v1/search", params={"tags": "front_page", "hitsPerPage": 40}
    )
    r.raise_for_status()
    out = []
    for hit in r.json().get("hits", []):
        discussion = f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        url = hit.get("url") if _valid_url(hit.get("url")) else discussion
        if not hit.get("title"):
            continue
        out.append(
            _item(
                title=hit["title"],
                url=url,
                source="Hacker News",
                summary=hit.get("story_text") or "",
                published_at=_ts(hit.get("created_at_i")),
                kind=NewsKind.DISCUSSION if url == discussion else NewsKind.ARTICLE,
                score=hit.get("points") or 0,
                comments=hit.get("num_comments") or 0,
                discussion_url=discussion,
                author=hit.get("author"),
            )
        )
    return out


async def dev_to(client: httpx.AsyncClient) -> list[FetchedNews]:
    r = await client.get("https://dev.to/api/articles", params={"top": 2, "per_page": 30})
    r.raise_for_status()
    out = []
    for a in r.json():
        if not a.get("title") or not _valid_url(a.get("url")):
            continue
        out.append(
            _item(
                title=a["title"],
                url=a["url"],
                source="DEV",
                summary=a.get("description") or "",
                image_url=a.get("cover_image") or a.get("social_image"),
                published_at=_ts(a.get("published_at")),
                score=a.get("public_reactions_count") or a.get("positive_reactions_count") or 0,
                comments=a.get("comments_count") or 0,
                discussion_url=a["url"] + "#comments",
                author=(a.get("user") or {}).get("name"),
                tags=tuple(a.get("tag_list") or ()),
            )
        )
    return out


async def lobsters(client: httpx.AsyncClient) -> list[FetchedNews]:
    r = await client.get("https://lobste.rs/hottest.json")
    r.raise_for_status()
    out = []
    for s in r.json()[:30]:
        url = s.get("url") if _valid_url(s.get("url")) else s.get("comments_url")
        if not s.get("title") or not _valid_url(url):
            continue
        out.append(
            _item(
                title=s["title"],
                url=url,
                source="Lobsters",
                summary=s.get("description_plain") or s.get("description") or "",
                published_at=_ts(s.get("created_at")),
                kind=NewsKind.DISCUSSION if url == s.get("comments_url") else NewsKind.ARTICLE,
                score=s.get("score") or 0,
                comments=s.get("comment_count") or 0,
                discussion_url=s.get("comments_url"),
                author=s.get("submitter_user"),
                tags=tuple(s.get("tags") or ()),
            )
        )
    return out


async def github_trending(client: httpx.AsyncClient) -> list[FetchedNews]:
    """Repositories created in the last week with the most stars (GitHub has no trending API)."""
    since = (datetime.now(UTC) - timedelta(days=7)).date().isoformat()
    r = await client.get(
        "https://api.github.com/search/repositories",
        params={
            "q": f"created:>{since} stars:>50",
            "sort": "stars",
            "order": "desc",
            "per_page": 25,
        },
        headers={"Accept": "application/vnd.github+json"},
    )
    r.raise_for_status()
    out = []
    for repo in r.json().get("items", []):
        if not _valid_url(repo.get("html_url")):
            continue
        topics = tuple(repo.get("topics") or ())
        language = repo.get("language")
        out.append(
            _item(
                title=f"{repo['full_name']}: {repo.get('description') or 'new repository'}",
                url=repo["html_url"],
                source="GitHub Trending",
                summary=repo.get("description") or "",
                image_url=f"https://opengraph.githubassets.com/1/{repo['full_name']}",
                published_at=_ts(repo.get("created_at")),
                kind=NewsKind.REPO,
                score=repo.get("stargazers_count") or 0,
                comments=0,
                author=(repo.get("owner") or {}).get("login"),
                tags=((language,) if language else ()) + topics,
            )
        )
    return out


DEFAULT_SUBREDDITS = (
    "programming",
    "MachineLearning",
    "LocalLLaMA",
    "webdev",
    "ExperiencedDevs",
    "cscareerquestions",
    "devops",
    "Python",
    "reactjs",
)

_reddit_token: tuple[str, float] | None = None


async def _reddit_access_token(client: httpx.AsyncClient) -> str | None:
    """App-only OAuth (free 'script' app). Reddit blocks anonymous API calls from servers."""
    global _reddit_token
    settings = get_settings()
    secret = settings.reddit_client_secret.get_secret_value()
    if not settings.reddit_client_id or not secret:
        return None
    if _reddit_token and _reddit_token[1] > time.time() + 60:
        return _reddit_token[0]
    r = await client.post(
        "https://www.reddit.com/api/v1/access_token",
        data={"grant_type": "client_credentials"},
        auth=(settings.reddit_client_id, secret),
    )
    r.raise_for_status()
    body = r.json()
    _reddit_token = (body["access_token"], time.time() + float(body.get("expires_in", 3600)))
    return _reddit_token[0]


async def reddit(client: httpx.AsyncClient) -> list[FetchedNews]:
    token = await _reddit_access_token(client)
    if token is None:
        return []  # not configured
    out: list[FetchedNews] = []
    for sub in get_settings().reddit_subreddits or list(DEFAULT_SUBREDDITS):
        try:
            r = await client.get(
                f"https://oauth.reddit.com/r/{sub}/top",
                params={"t": "day", "limit": 12, "raw_json": 1},
                headers={"Authorization": f"Bearer {token}"},
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("reddit_sub_failed", sub=sub, error=type(exc).__name__)
            continue
        for child in r.json().get("data", {}).get("children", []):
            p = child.get("data") or {}
            if p.get("stickied") or p.get("over_18") or not p.get("title"):
                continue
            discussion = f"https://www.reddit.com{p.get('permalink', '')}"
            url = p.get("url_overridden_by_dest") or discussion
            if not _valid_url(url):
                url = discussion
            image = None
            preview = (p.get("preview") or {}).get("images") or []
            if preview:
                image = (preview[0].get("source") or {}).get("url")
            out.append(
                _item(
                    title=p["title"],
                    url=url,
                    source=f"r/{p.get('subreddit') or sub}",
                    summary=p.get("selftext") or "",
                    image_url=image,
                    published_at=_ts(p.get("created_utc")),
                    kind=NewsKind.DISCUSSION if url == discussion else NewsKind.ARTICLE,
                    score=p.get("score") or 0,
                    comments=p.get("num_comments") or 0,
                    discussion_url=discussion,
                    author=p.get("author"),
                    tags=(sub.lower(), p.get("link_flair_text") or ""),
                )
            )
    return out


API_SOURCES: dict[str, Fetcher] = {
    "hacker_news": hacker_news,
    "dev_to": dev_to,
    "lobsters": lobsters,
    "github": github_trending,
    "reddit": reddit,
}


class AllSourcesProvider:
    """RSS blogs + every API source, fetched concurrently."""

    def __init__(
        self,
        *,
        sources: dict[str, Fetcher] | None = None,
        rss: RSSProvider | None = None,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.sources = API_SOURCES if sources is None else sources
        self.rss = rss if rss is not None else RSSProvider(timeout=timeout, transport=transport)
        self.timeout = timeout
        self.transport = transport

    async def fetch(self) -> list[FetchedNews]:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            transport=self.transport,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            names = list(self.sources)
            results = await asyncio.gather(
                self.rss.fetch(),
                *(self.sources[n](client) for n in names),
                return_exceptions=True,
            )
        items: list[FetchedNews] = []
        for name, result in zip(["rss", *names], results, strict=True):
            if isinstance(result, BaseException):
                log.warning("news_source_failed", source=name, error=type(result).__name__)
                continue
            items.extend(result)
        return items

    async def preview_images(self, urls: list[str], limit: int = 80) -> dict[str, str]:
        """og:image for new stories without a picture (HN and Lobsters links mostly)."""
        gate = asyncio.Semaphore(10)
        found: dict[str, str] = {}

        async def one(client: httpx.AsyncClient, url: str) -> None:
            async with gate:
                try:
                    image = await asyncio.wait_for(og_image(client, url), timeout=6)
                except Exception:
                    return
                if image:
                    found[url] = image

        async with httpx.AsyncClient(
            timeout=5.0,
            follow_redirects=True,
            transport=self.transport,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        ) as client:
            await asyncio.gather(*(one(client, u) for u in urls[:limit]))
        return found
