from datetime import date, timedelta
from typing import Any

import httpx
import pytest
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, SecretStr

from app.core import ai as ai_module
from app.core.ai import AIRateLimitedError, AIServiceError, ChatTurn, GeminiClient, ToolSpec
from app.core.config import get_settings
from app.features.assistant.schemas import PlannedMilestone, PlannedResource, RoadmapPlan
from app.features.assistant.service import schedule


class FakeAI:
    model = "fake-model"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.tool_results: list[dict[str, Any]] = []
        self.last_system = ""
        self.text = "Rewritten text"
        self.plan: RoadmapPlan | None = None
        self.reply = "Added it for you."

    async def generate_text(self, *, system: str, prompt: str) -> str:
        self.last_system = prompt
        return self.text

    async def generate_structured(self, *, system: str, prompt: str, schema: type) -> Any:
        assert self.plan is not None
        return self.plan

    async def chat_with_tools(self, *, system, history, message, tools, execute, max_rounds=4):  # type: ignore[no-untyped-def]
        self.last_system = system
        for name, args in self.calls:
            self.tool_results.append(await execute(name, args))
        return self.reply


@pytest.fixture
def fake_ai(app) -> FakeAI:  # type: ignore[no-untyped-def]
    fake = FakeAI()
    app.dependency_overrides[ai_module.get_ai_client] = lambda: fake
    return fake


async def test_status_and_unavailable(auth_client: httpx.AsyncClient) -> None:
    r = await auth_client.get("/assistant/status")
    assert r.json() == {"enabled": False, "model": "gemini-2.5-flash"}
    r = await auth_client.post("/assistant/ask", json={"message": "hi"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "AI_UNAVAILABLE"
    r = await auth_client.post("/ai/rewrite", json={"text": "x", "kind": "bullet"})
    assert r.status_code == 503
    r = await auth_client.post("/roadmaps/generate", json={"goal": "Learn Rust"})
    assert r.status_code == 503


async def test_get_ai_client_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings().model_copy(update={"gemini_api_key": SecretStr("k" * 10)})
    monkeypatch.setattr(ai_module, "get_settings", lambda: settings)
    client = ai_module.get_ai_client()
    assert isinstance(client, GeminiClient) and client.model == "gemini-2.5-flash"


async def test_ask_executes_tools(auth_client: httpx.AsyncClient, fake_ai: FakeAI) -> None:
    await auth_client.post("/jobs", json={"company": "Vercel", "role": "FE", "status": "interview"})
    await auth_client.post("/tasks", json={"title": "Old task", "due_date": "2020-01-01"})
    await auth_client.post("/roadmaps", json={"title": "ML", "milestones": [{"title": "Math"}]})
    await auth_client.put("/profile", json={"headline": "Aspiring ML engineer"})
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    fake_ai.calls = [
        ("create_task", {"title": "Revise CNNs", "due_date": tomorrow, "priority": "high"}),
        ("create_job", {"company": "Razorpay", "role": "SDE", "status": "applied", "url": ""}),
        ("create_task", {"title": ""}),
        ("launch_rockets", {}),
    ]
    r = await auth_client.post(
        "/assistant/ask",
        json={
            "message": "add stuff",
            "history": [{"role": "user", "content": "hi"}, {"role": "model", "content": "hello"}],
            "tz": "Asia/Kolkata",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"] == "Added it for you."
    assert [(a["type"], a["title"]) for a in body["actions"]] == [
        ("task_created", "Revise CNNs"),
        ("job_created", "SDE at Razorpay"),
    ]
    assert fake_ai.tool_results[2]["ok"] is False and "title" in fake_ai.tool_results[2]["error"]
    assert fake_ai.tool_results[3] == {"ok": False, "error": "Unknown tool launch_rockets"}
    assert "Vercel" in fake_ai.last_system and "Old task" in fake_ai.last_system
    assert "overdue" in fake_ai.last_system and "Current roadmap: ML" in fake_ai.last_system
    assert "Aspiring ML engineer" in fake_ai.last_system
    tasks = (await auth_client.get("/tasks")).json()
    assert any(t["title"] == "Revise CNNs" and t["priority"] == "high" for t in tasks)
    jobs = (await auth_client.get("/jobs", params={"q": "razorpay"})).json()
    assert jobs["items"][0]["applied_at"] is not None

    fake_ai.calls, fake_ai.reply = [], ""
    r = await auth_client.post("/assistant/ask", json={"message": "hm"})
    assert r.json()["reply"].startswith("Sorry")


async def test_ask_validation(auth_client: httpx.AsyncClient, fake_ai: FakeAI) -> None:
    r = await auth_client.post("/assistant/ask", json={"message": ""})
    assert r.status_code == 422
    r = await auth_client.post("/assistant/ask", json={"message": "x", "tz": "Bad/Zone"})
    assert r.status_code == 422


async def test_rewrite(auth_client: httpx.AsyncClient, fake_ai: FakeAI) -> None:
    r = await auth_client.post(
        "/ai/rewrite", json={"text": "did stuff", "kind": "bullet", "instruction": "more impact"}
    )
    assert r.json() == {"text": "Rewritten text"}
    assert "more impact" in fake_ai.last_system and "action verb" in fake_ai.last_system
    fake_ai.text = ""
    r = await auth_client.post("/ai/rewrite", json={"text": "x", "kind": "summary"})
    assert r.status_code == 502 and r.json()["error"]["code"] == "AI_ERROR"
    r = await auth_client.post("/ai/rewrite", json={"text": "x", "kind": "poem"})
    assert r.status_code == 422


async def test_generate_roadmap(auth_client: httpx.AsyncClient, fake_ai: FakeAI) -> None:
    res = [
        PlannedResource(title="Docs", url="https://doc.rust-lang.org/book/"),
        PlannedResource(title="Bad", url="javascript:alert(1)"),
    ]
    fake_ai.plan = RoadmapPlan(
        title="Rust in 3 months",
        goal="Write production Rust",
        milestones=[
            PlannedMilestone(title=f"Step {i}", description="d", estimated_weeks=w, resources=res)
            for i, w in enumerate([2, 2, 4, 40, 0])
        ],
    )
    target = (date.today() + timedelta(days=90)).isoformat()
    r = await auth_client.post(
        "/roadmaps/generate",
        json={"goal": "Learn Rust", "target_date": target, "hours_per_week": 6},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "Rust in 3 months" and body["milestone_count"] == 5
    assert body["target_date"] == target
    assert body["milestones"][-1]["target_date"] == target
    assert body["milestones"][0]["resources"] == [
        {"title": "Docs", "url": "https://doc.rust-lang.org/book/"}
    ]
    fake_ai.plan = RoadmapPlan(title="", goal="", milestones=[])
    r = await auth_client.post("/roadmaps/generate", json={"goal": "Learn Go"})
    assert r.status_code == 502


def test_schedule() -> None:
    start = date(2026, 1, 1)
    assert schedule([1, 1], start, None) == [date(2026, 1, 8), date(2026, 1, 15)]
    assert schedule([1, 3], start, date(2026, 1, 9))[-1] == date(2026, 1, 9)


# ---- GeminiClient against a mocked SDK ------------------------------------------------


def _text_response(text: str) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part.from_text(text=text)])
            )
        ]
    )


def _call_response(name: str, args: dict[str, Any]) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))],
                )
            )
        ]
    )


class _Models:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.requests: list[Any] = []

    async def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.requests.append(contents)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _client(responses: list[Any]) -> tuple[GeminiClient, _Models]:
    client = GeminiClient("test-key", "gemini-2.5-flash")
    models = _Models(responses)
    client._client = type("C", (), {"aio": type("A", (), {"models": models})()})()  # type: ignore[assignment]
    return client, models


class Out(BaseModel):
    answer: str


async def test_gemini_text_structured_and_tools() -> None:
    client, _ = _client([_text_response("  hi  ")])
    assert await client.generate_text(system="s", prompt="p") == "hi"

    client, _ = _client([_text_response('{"answer": "42"}')])
    out = await client.generate_structured(system="s", prompt="p", schema=Out)
    assert out.answer == "42"
    client, _ = _client([_text_response("not json")])
    with pytest.raises(AIServiceError):
        await client.generate_structured(system="s", prompt="p", schema=Out)

    seen: list[tuple[str, dict[str, Any]]] = []

    async def execute(name: str, args: dict[str, Any]) -> dict[str, Any]:
        seen.append((name, args))
        return {"ok": True}

    client, models = _client(
        [_call_response("create_task", {"title": "T"}), _text_response("Created T")]
    )
    reply = await client.chat_with_tools(
        system="s",
        history=[ChatTurn("user", "earlier")],
        message="add T",
        tools=[ToolSpec("create_task", "d", {"type": "object", "properties": {}})],
        execute=execute,
    )
    assert reply == "Created T" and seen == [("create_task", {"title": "T"})]
    assert len(models.requests[1]) == 4  # history, message, model call, tool response

    client, _ = _client([_call_response("create_task", {})] * 2)
    reply = await client.chat_with_tools(
        system="s", history=[], message="m", tools=[], execute=execute, max_rounds=2
    )
    assert reply == "Done."


async def test_gemini_error_mapping() -> None:
    quota = genai_errors.ClientError(
        429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota"}}
    )
    client, _ = _client([quota])
    with pytest.raises(AIRateLimitedError):
        await client.generate_text(system="s", prompt="p")
    server = genai_errors.ServerError(
        500, {"error": {"code": 500, "status": "INTERNAL", "message": "boom"}}
    )
    client, _ = _client([server])
    with pytest.raises(AIServiceError):
        await client.generate_text(system="s", prompt="p")
    client, _ = _client([TimeoutError()])
    with pytest.raises(AIServiceError):
        await client.generate_text(system="s", prompt="p")


async def test_rate_limited_maps_to_429(auth_client: httpx.AsyncClient, app) -> None:  # type: ignore[no-untyped-def]
    class Limited(FakeAI):
        async def generate_text(self, *, system: str, prompt: str) -> str:
            raise AIRateLimitedError()

    app.dependency_overrides[ai_module.get_ai_client] = lambda: Limited()
    r = await auth_client.post("/ai/rewrite", json={"text": "x", "kind": "bullet"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "AI_RATE_LIMITED"
