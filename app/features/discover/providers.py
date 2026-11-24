"""Public job boards with free APIs. Every source is best-effort and normalised to `FetchedPosting`.

Sources: Remotive, RemoteOK, Arbeitnow, Jobicy, Himalayas (worldwide + open to India) and the
monthly Hacker News "Who is hiring?" thread.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, TypeGuard

import httpx

from app.core.logging import get_logger
from app.features.news.provider import parse_date
from app.shared.text import clean_text, normalise_tag, words

log = get_logger(__name__)

USER_AGENT = "MandyJobsBot/1.0 (+personal job search assistant)"
SUMMARY_CHARS = 700

INDIA_PLACES = words(
    "india bangalore bengaluru hyderabad pune chennai mumbai delhi gurgaon gurugram noida "
    "kolkata ahmedabad kochi coimbatore trivandrum jaipur indore chandigarh"
)
OPEN_TO_ALL = words("worldwide anywhere global international apac asia emea+apac")


@dataclass(frozen=True)
class FetchedPosting:
    source: str
    url: str
    company: str
    role: str
    location: str
    remote: bool
    summary: str
    posted_at: datetime
    tags: tuple[str, ...] = ()
    salary: str | None = None
    employment_type: str | None = None
    logo_url: str | None = None
    regions: tuple[str, ...] = field(default=())


class JobsProvider(Protocol):
    async def fetch(self) -> list[FetchedPosting]: ...


def regions_for(location: str, remote: bool) -> tuple[str, ...]:
    """Where someone in India can take the job: "india" (based there) and/or "remote"."""
    loc = location.lower()
    found: list[str] = []
    if any(place in loc for place in INDIA_PLACES):
        found.append("india")
    if remote and (not loc.strip() or "india" in found or any(w in loc for w in OPEN_TO_ALL)):
        found.append("remote")
    return tuple(found)


def _ts(value: Any) -> datetime:
    if isinstance(value, int | float) or (isinstance(value, str) and value.isdigit()):
        return datetime.fromtimestamp(int(value), UTC)
    parsed = parse_date(str(value)) if value else None
    return parsed or datetime.now(UTC)


def _valid(url: Any) -> TypeGuard[str]:
    return isinstance(url, str) and url.startswith(("http://", "https://"))


def posting(
    *,
    source: str,
    url: str,
    company: str,
    role: str,
    location: str = "",
    remote: bool = False,
    description: str = "",
    posted_at: Any = None,
    tags: Any = (),
    salary: str | None = None,
    employment_type: str | None = None,
    logo_url: str | None = None,
) -> FetchedPosting:
    location = clean_text(location, 200)
    tag_list = tuple(dict.fromkeys(normalise_tag(str(t)) for t in (tags or ()) if t))[:12]
    return FetchedPosting(
        source=source,
        url=url[:1000],
        company=clean_text(company, 200) or "Unknown company",
        role=clean_text(role, 300),
        location=location,
        remote=remote,
        summary=clean_text(description, SUMMARY_CHARS),
        posted_at=_ts(posted_at),
        tags=tag_list,
        salary=clean_text(salary, 120) or None if salary else None,
        employment_type=clean_text(employment_type, 60) or None if employment_type else None,
        logo_url=logo_url[:1000] if _valid(logo_url) else None,
        regions=regions_for(location, remote),
    )


Fetcher = Callable[[httpx.AsyncClient], Awaitable[list[FetchedPosting]]]


async def remotive(client: httpx.AsyncClient) -> list[FetchedPosting]:
    r = await client.get(
        "https://remotive.com/api/remote-jobs", params={"category": "software-dev", "limit": 150}
    )
    r.raise_for_status()
    return [
        posting(
            source="Remotive",
            url=j["url"],
            company=j.get("company_name") or "",
            role=j.get("title") or "",
            location=j.get("candidate_required_location") or "Worldwide",
            remote=True,
            description=j.get("description") or "",
            posted_at=j.get("publication_date"),
            tags=j.get("tags") or (),
            salary=j.get("salary") or None,
            employment_type=(j.get("job_type") or "").replace("_", " ") or None,
            logo_url=j.get("company_logo") or j.get("company_logo_url"),
        )
        for j in r.json().get("jobs", [])
        if _valid(j.get("url")) and j.get("title")
    ]


async def remoteok(client: httpx.AsyncClient) -> list[FetchedPosting]:
    r = await client.get("https://remoteok.com/api")
    r.raise_for_status()
    out = []
    for j in r.json()[1:]:  # the first element is the API's legal notice
        if not isinstance(j, dict) or not _valid(j.get("url")) or not j.get("position"):
            continue
        lo, hi = int(j.get("salary_min") or 0), int(j.get("salary_max") or 0)
        salary = f"${lo:,}-${hi:,}" if lo and hi else None
        out.append(
            posting(
                source="RemoteOK",
                url=j["url"],
                company=j.get("company") or "",
                role=j["position"],
                location=j.get("location") or "Worldwide",
                remote=True,
                description=j.get("description") or "",
                posted_at=j.get("epoch") or j.get("date"),
                tags=j.get("tags") or (),
                salary=salary,
                logo_url=j.get("company_logo") or j.get("logo"),
            )
        )
    return out


async def arbeitnow(client: httpx.AsyncClient) -> list[FetchedPosting]:
    r = await client.get("https://www.arbeitnow.com/api/job-board-api")
    r.raise_for_status()
    return [
        posting(
            source="Arbeitnow",
            url=j["url"],
            company=j.get("company_name") or "",
            role=j.get("title") or "",
            location=j.get("location") or "",
            remote=bool(j.get("remote")),
            description=j.get("description") or "",
            posted_at=j.get("created_at"),
            tags=j.get("tags") or (),
            employment_type=", ".join(j.get("job_types") or []) or None,
        )
        for j in r.json().get("data", [])
        if _valid(j.get("url")) and j.get("title")
    ]


async def jobicy(client: httpx.AsyncClient) -> list[FetchedPosting]:
    r = await client.get(
        "https://jobicy.com/api/v2/remote-jobs", params={"count": 100, "industry": "engineering"}
    )
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        if not _valid(j.get("url")) or not j.get("jobTitle"):
            continue
        lo, hi, cur = j.get("salaryMin"), j.get("salaryMax"), j.get("salaryCurrency") or ""
        salary = (
            f"{cur} {lo:,}-{hi:,}".strip() if isinstance(lo, int) and isinstance(hi, int) else None
        )
        industry = j.get("jobIndustry") or []
        out.append(
            posting(
                source="Jobicy",
                url=j["url"],
                company=j.get("companyName") or "",
                role=j["jobTitle"],
                location=j.get("jobGeo") or "Anywhere",
                remote=True,
                description=j.get("jobExcerpt") or j.get("jobDescription") or "",
                posted_at=j.get("pubDate"),
                tags=industry if isinstance(industry, list) else [industry],
                salary=salary,
                employment_type=", ".join(j.get("jobType") or []) or None,
                logo_url=j.get("companyLogo"),
            )
        )
    return out


def _himalayas(j: dict[str, Any]) -> FetchedPosting | None:
    url = j.get("applicationLink") or j.get("guid")
    if not _valid(url) or not j.get("title"):
        return None
    restrictions = j.get("locationRestrictions") or []
    location = ", ".join(restrictions) if restrictions else "Worldwide"
    lo, hi = j.get("minSalary"), j.get("maxSalary")
    salary = (
        f"{j.get('currency') or ''} {lo:,}-{hi:,}".strip()
        if isinstance(lo, int) and isinstance(hi, int)
        else None
    )
    return posting(
        source="Himalayas",
        url=url,
        company=j.get("companyName") or "",
        role=j["title"],
        location=location,
        remote=True,
        description=j.get("excerpt") or j.get("description") or "",
        posted_at=j.get("pubDate"),
        tags=list(j.get("categories") or [])[:8],
        salary=salary,
        employment_type=j.get("employmentType"),
        logo_url=j.get("companyLogo"),
    )


async def himalayas(client: httpx.AsyncClient) -> list[FetchedPosting]:
    """Latest remote jobs, plus a search for jobs open to people in India."""
    out: list[FetchedPosting] = []
    r = await client.get("https://himalayas.app/jobs/api", params={"limit": 100})
    r.raise_for_status()
    out.extend(p for j in r.json().get("jobs", []) if (p := _himalayas(j)))
    r = await client.get(
        "https://himalayas.app/jobs/api/search",
        params={"country": "India", "q": "engineer developer", "limit": 100},
    )
    if r.status_code == 200:
        out.extend(p for j in r.json().get("jobs", []) if (p := _himalayas(j)))
    return out


_ROLE_WORDS = words(
    "engineer engineers developer developers scientist designer manager sre devops architect "
    "lead analyst researcher programmer swe frontend backend fullstack full-stack ml data"
)
_REMOTE_RE = re.compile(r"\bremote\b", re.I)


def parse_hn_comment(text: str) -> tuple[str, str, str, bool] | None:
    """'Company | Role | Location | REMOTE | ...' -> (company, role, location, remote)."""
    first = clean_text(text.split("<p>")[0], 300)
    parts = [p.strip() for p in first.split("|") if p.strip()]
    if len(parts) < 2:
        return None
    company = parts[0][:200]
    rest = parts[1:]
    role = next((p for p in rest if set(p.lower().replace(",", " ").split()) & _ROLE_WORDS), None)
    role = role or rest[0]
    others = [p for p in rest if p is not role]
    location = ", ".join(
        p for p in others if not p.lower().startswith(("http", "$", "€", "£", "full", "part"))
    )[:200]
    return company, role, location, bool(_REMOTE_RE.search(first))


async def hn_who_is_hiring(client: httpx.AsyncClient) -> list[FetchedPosting]:
    r = await client.get(
        "https://hn.algolia.com/api/v1/search_by_date",
        params={"tags": "story,author_whoishiring", "hitsPerPage": 5},
    )
    r.raise_for_status()
    story = next(
        (h for h in r.json().get("hits", []) if "who is hiring" in (h.get("title") or "").lower()),
        None,
    )
    if story is None:
        return []
    story_id = int(story["objectID"])
    r = await client.get(
        "https://hn.algolia.com/api/v1/search",
        params={"tags": f"comment,story_{story_id}", "hitsPerPage": 500},
    )
    r.raise_for_status()
    out = []
    for c in r.json().get("hits", []):
        if c.get("parent_id") != story_id or not c.get("comment_text"):
            continue
        parsed = parse_hn_comment(c["comment_text"])
        if parsed is None:
            continue
        company, role, location, remote = parsed
        out.append(
            posting(
                source="HN Who is hiring",
                url=f"https://news.ycombinator.com/item?id={c['objectID']}",
                company=company,
                role=role,
                location=location,
                remote=remote,
                description=c["comment_text"],
                posted_at=c.get("created_at_i"),
            )
        )
    return out


JOB_SOURCES: dict[str, Fetcher] = {
    "remotive": remotive,
    "remoteok": remoteok,
    "arbeitnow": arbeitnow,
    "jobicy": jobicy,
    "himalayas": himalayas,
    "hn": hn_who_is_hiring,
}


class AllJobBoardsProvider:
    def __init__(
        self,
        sources: dict[str, Fetcher] | None = None,
        *,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.sources = JOB_SOURCES if sources is None else sources
        self.timeout = timeout
        self.transport = transport

    async def fetch(self) -> list[FetchedPosting]:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            transport=self.transport,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        ) as client:
            names = list(self.sources)
            results = await asyncio.gather(
                *(self.sources[n](client) for n in names), return_exceptions=True
            )
        out: list[FetchedPosting] = []
        for name, result in zip(names, results, strict=True):
            if isinstance(result, BaseException):
                log.warning("job_source_failed", source=name, error=type(result).__name__)
                continue
            out.extend(result)
        return out


class NullJobsProvider:
    async def fetch(self) -> list[FetchedPosting]:
        return []
