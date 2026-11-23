"""Small AI client abstraction over Google Gemini (google-genai SDK).

Everything that talks to Gemini goes through `AIClient`, so tests can swap in a fake via the
`get_ai_client` dependency.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal, Protocol

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

log = get_logger(__name__)


class AIUnavailableError(AppError):
    status_code = 503
    code = "AI_UNAVAILABLE"
    message = "AI features are not configured (set GEMINI_API_KEY)"


class AIRateLimitedError(AppError):
    status_code = 429
    code = "AI_RATE_LIMITED"
    message = "The AI quota is exhausted for now, try again in a minute"


class AIServiceError(AppError):
    status_code = 502
    code = "AI_ERROR"
    message = "The AI service returned an error"


@dataclass(frozen=True)
class ChatTurn:
    role: Literal["user", "model"]
    content: str


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema of an object


ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class AIClient(Protocol):
    model: str

    async def generate_text(self, *, system: str, prompt: str) -> str: ...

    async def generate_structured[T: BaseModel](
        self, *, system: str, prompt: str, schema: type[T]
    ) -> T: ...

    async def chat_with_tools(
        self,
        *,
        system: str,
        history: list[ChatTurn],
        message: str,
        tools: list[ToolSpec],
        execute: ToolExecutor,
        max_rounds: int = 4,
    ) -> str: ...


def _translate(exc: Exception) -> AppError:
    if isinstance(exc, genai_errors.APIError):
        status = str(getattr(exc, "status", "") or "")
        if exc.code == 429 or "RESOURCE_EXHAUSTED" in status:
            return AIRateLimitedError()
        log.warning("gemini_error", code=exc.code, status=status)
        return AIServiceError()
    log.warning("gemini_failure", error_type=type(exc).__name__)
    return AIServiceError()


class GeminiClient:
    def __init__(self, api_key: str, model: str) -> None:
        self.model = model
        self._client = genai.Client(api_key=api_key)

    async def _generate(
        self, contents: Any, config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        try:
            return await self._client.aio.models.generate_content(
                model=self.model, contents=contents, config=config
            )
        except Exception as exc:
            raise _translate(exc) from exc

    async def generate_text(self, *, system: str, prompt: str) -> str:
        response = await self._generate(
            prompt, types.GenerateContentConfig(system_instruction=system, temperature=0.6)
        )
        return (response.text or "").strip()

    async def generate_structured[T: BaseModel](
        self, *, system: str, prompt: str, schema: type[T]
    ) -> T:
        response = await self._generate(
            prompt,
            types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.4,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        if isinstance(response.parsed, schema):
            return response.parsed
        try:
            return schema.model_validate_json(response.text or "")
        except ValueError as exc:
            raise AIServiceError("The AI returned an unexpected format") from exc

    async def chat_with_tools(
        self,
        *,
        system: str,
        history: list[ChatTurn],
        message: str,
        tools: list[ToolSpec],
        execute: ToolExecutor,
        max_rounds: int = 4,
    ) -> str:
        contents: list[types.Content] = [
            types.Content(role=t.role, parts=[types.Part.from_text(text=t.content)])
            for t in history
        ]
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=message)]))
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.5,
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t.name,
                            description=t.description,
                            parameters_json_schema=t.parameters,
                        )
                        for t in tools
                    ]
                )
            ],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        text = ""
        for _ in range(max_rounds):
            response = await self._generate(contents, config)
            calls = response.function_calls or []
            text = (response.text or "").strip() if not calls else text
            if not calls:
                return text
            if response.candidates and response.candidates[0].content:
                contents.append(response.candidates[0].content)
            parts = []
            for call in calls:
                result = await execute(call.name or "", dict(call.args or {}))
                parts.append(
                    types.Part.from_function_response(name=call.name or "", response=result)
                )
            contents.append(types.Content(role="user", parts=parts))
        return text or "Done."


@lru_cache
def _gemini(api_key: str, model: str) -> GeminiClient:
    return GeminiClient(api_key, model)


def get_ai_client() -> AIClient:
    """FastAPI dependency: the configured client, or 503 AI_UNAVAILABLE."""
    settings = get_settings()
    if not settings.ai_enabled:
        raise AIUnavailableError()
    return _gemini(settings.gemini_api_key.get_secret_value(), settings.gemini_model)


def get_optional_ai_client() -> AIClient | None:
    """FastAPI dependency for features that work without AI and get better with it."""
    settings = get_settings()
    if not settings.ai_enabled:
        return None
    return _gemini(settings.gemini_api_key.get_secret_value(), settings.gemini_model)
