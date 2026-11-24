"""Prompt-built resumes: look and content from the prompt, facts only from the profile."""

from datetime import date
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ai as ai_module
from app.features.auth.models import User
from app.features.profile.models import Experience, Profile
from app.features.resumes.ai import PlanItem, PlanSection, PlanStyle, ResumePlan


class FakeAI:
    model = "fake"

    def __init__(self, plan: ResumePlan) -> None:
        self.plan = plan
        self.prompts: list[str] = []

    async def generate_structured(self, *, system: str, prompt: str, schema: type) -> Any:
        assert schema is ResumePlan
        self.prompts.append(prompt)
        return self.plan


def _plan(accent: str = "#1f3a8a", template: str = "classic") -> ResumePlan:
    return ResumePlan(
        title="Backend - Acme",
        template=template,  # type: ignore[arg-type]
        style=PlanStyle(accent=accent, font="serif", density="compact"),
        headline="Backend engineer, Python and Postgres",
        sections=[
            PlanSection(type="summary", title="Profile", text="Builds APIs.", items=[]),
            PlanSection(
                type="experience",
                title="Experience",
                text="ignored for non-summary",
                items=[
                    PlanItem(
                        title="Engineer",
                        subtitle="Initech",
                        location=None,
                        start_date="Jan 2022",
                        end_date="Present",
                        description=None,
                        bullets=["Shipped the billing API", " "],
                        tags=[],
                        url="javascript:alert(1)",
                    )
                ],
            ),
        ],
        notes="Kept to one page.",
    )


async def _seed(db: AsyncSession, user: User) -> None:
    db.add(Profile(user_id=user.id, headline="Dev", phone="+91 1", location="Chennai"))
    db.add(
        Experience(
            user_id=user.id,
            company="Initech",
            title="Engineer",
            start_date=date(2022, 1, 1),
            current=True,
            highlights=["Built billing"],
        )
    )
    await db.commit()


async def test_generate_and_revise(
    app, auth_client: httpx.AsyncClient, db: AsyncSession, user: User
) -> None:  # type: ignore[no-untyped-def]
    await _seed(db, user)
    fake = FakeAI(_plan())
    app.dependency_overrides[ai_module.get_ai_client] = lambda: fake

    r = await auth_client.post(
        "/resumes/generate",
        json={"prompt": "One page, classic serif, navy", "job_description": "Python role at Acme"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    resume = body["resume"]
    assert body["notes"] == "Kept to one page."
    assert resume["title"] == "Backend - Acme" and resume["template"] == "classic"
    content = resume["content"]
    assert content["style"] == {"accent": "#1f3a8a", "font": "serif", "density": "compact"}
    # header facts come from the profile, the headline from the AI
    assert content["header"]["full_name"] == "Owner"
    assert content["header"]["email"] == "owner@example.com"
    assert content["header"]["location"] == "Chennai"
    assert content["header"]["headline"] == "Backend engineer, Python and Postgres"
    exp = content["sections"][1]
    assert exp["text"] is None and exp["items"][0]["bullets"] == ["Shipped the billing API"]
    assert exp["items"][0]["url"] is None  # only http(s) links survive
    prompt = fake.prompts[0]
    assert "One page, classic serif, navy" in prompt and "Python role at Acme" in prompt
    assert "Initech" in prompt and "Built billing" in prompt

    fake.plan = _plan(accent="not-a-colour", template="modern")
    r = await auth_client.post(
        f"/resumes/{resume['id']}/revise", json={"prompt": "Switch to the modern template"}
    )
    assert r.status_code == 200, r.text
    revised = r.json()["resume"]
    assert revised["template"] == "modern" and revised["current_version"] == 2
    assert revised["content"]["style"]["accent"] == "#7c5cff"  # invalid colour -> default
    assert "CURRENT LOOK: template classic" in fake.prompts[1]
    versions = (await auth_client.get(f"/resumes/{resume['id']}/versions")).json()
    assert [v["version"] for v in versions] == [2, 1]

    missing = "00000000-0000-0000-0000-000000000000"
    r = await auth_client.post(f"/resumes/{missing}/revise", json={"prompt": "hello"})
    assert r.status_code == 404


async def test_requires_ai(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post("/resumes/generate", json={"prompt": "Make me a resume"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "AI_UNAVAILABLE"


async def test_style_is_optional_and_validated(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.post("/resumes", json={"title": "Plain"})
    assert r.json()["content"]["style"] is None
    rid = r.json()["id"]
    bad = {"content": {"style": {"accent": "red"}}}
    assert (await auth_client.patch(f"/resumes/{rid}", json=bad)).status_code == 422
    good = {"content": {"style": {"accent": "#AA00ff", "font": "mono"}}}
    r = await auth_client.patch(f"/resumes/{rid}", json=good)
    assert r.json()["content"]["style"] == {
        "accent": "#AA00ff",
        "font": "mono",
        "density": "comfortable",
    }
