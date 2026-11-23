"""Gemini-backed assistant: chat with tool calls, text rewriting, roadmap planning."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai import AIClient, AIServiceError, ChatTurn, ToolSpec
from app.features.assistant.schemas import (
    AskIn,
    AskOut,
    AssistantAction,
    RewriteIn,
    RoadmapPlan,
)
from app.features.auth.models import User
from app.features.jobs import service as job_service
from app.features.jobs.models import Job, JobStatus
from app.features.jobs.schemas import JobCreate
from app.features.personalize import service as interests
from app.features.profile.models import Profile
from app.features.roadmaps import service as roadmap_service
from app.features.roadmaps.models import MilestoneStatus, Roadmap, RoadmapStatus
from app.features.roadmaps.schemas import (
    MilestoneCreate,
    Resource,
    RoadmapCreate,
    RoadmapDetail,
    RoadmapGenerate,
)
from app.features.tasks import service as task_service
from app.features.tasks.models import Task, TaskStatus
from app.features.tasks.schemas import TaskCreate
from app.shared.timeutil import local_today, parse_tz

TOOLS = [
    ToolSpec(
        name="create_task",
        description="Create a study/to-do task for the user.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short task title"},
                "due_date": {"type": "string", "description": "Due date, YYYY-MM-DD"},
                "priority": {"type": "string", "enum": ["low", "medium", "high"]},
            },
            "required": ["title"],
        },
    ),
    ToolSpec(
        name="create_job",
        description="Add a job application to the user's tracker.",
        parameters={
            "type": "object",
            "properties": {
                "company": {"type": "string"},
                "role": {"type": "string"},
                "location": {"type": "string"},
                "url": {"type": "string"},
                "status": {"type": "string", "enum": [s.value for s in JobStatus]},
            },
            "required": ["company", "role"],
        },
    ),
]

ASSISTANT_SYSTEM = """You are Mandy, a concise, friendly career and study assistant for {name}.
Today is {today} ({tz}). Answer in Markdown, short paragraphs or bullet lists.
When the user asks you to add/create/remember a task or a job application, call the matching
tool instead of only describing it, then confirm what you created. Resolve relative dates
("tomorrow", "Friday") against today's date. Never invent data that is not in the context.

Context about the user:
{context}"""

REWRITE_SYSTEM = (
    "You are an expert resume and career writer. Rewrite the user's text. Return only the "
    "rewritten text, no preamble, no quotes, no Markdown headings."
)
REWRITE_GUIDE = {
    "summary": "Make it a crisp 2-4 sentence professional summary in first person without 'I'.",
    "bullet": "Make it one strong resume bullet: start with an action verb, show impact, "
    "quantify if the text allows, max ~30 words.",
    "cover_note": "Make it a short, warm, specific cover note (under 150 words).",
}

ROADMAP_SYSTEM = """You plan practical learning roadmaps. Produce 4 to 8 milestones in order.
Each milestone has a clear title, a 1-2 sentence description, estimated_weeks (1-12) and 2-4
high-quality free resources with real, well-known URLs (official docs, reputable courses)."""


async def build_context(db: AsyncSession, user: User, today: date) -> str:
    lines: list[str] = [await interests.context(db, user)]
    profile = await db.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile and (profile.headline or profile.target_roles):
        lines.append(
            f"Headline: {profile.headline or '-'}; target roles: "
            f"{', '.join(profile.target_roles or []) or '-'}"
        )
    tasks = (
        await db.scalars(
            select(Task)
            .where(Task.user_id == user.id, Task.status == TaskStatus.TODO)
            .order_by(Task.due_date.asc().nulls_last(), task_service.PRIORITY_RANK)
            .limit(15)
        )
    ).unique()
    task_lines = [
        f"- {t.title} (due {t.due_date or 'no date'}, {t.priority.value} priority"
        f"{', overdue' if t.due_date and t.due_date < today else ''})"
        for t in tasks
    ]
    lines.append("Open tasks:\n" + ("\n".join(task_lines) or "- none"))
    jobs = await db.scalars(
        select(Job)
        .where(Job.user_id == user.id, Job.status != JobStatus.REJECTED)
        .order_by(Job.updated_at.desc())
        .limit(12)
    )
    job_lines = [
        f"- {j.company} — {j.role}: {j.status.value}"
        + (f", interview {j.interview_at:%Y-%m-%d %H:%M} UTC" if j.interview_at else "")
        for j in jobs
    ]
    lines.append("Job pipeline:\n" + ("\n".join(job_lines) or "- none"))
    roadmap = await db.scalar(
        select(Roadmap)
        .where(Roadmap.user_id == user.id, Roadmap.status == RoadmapStatus.ACTIVE)
        .order_by(Roadmap.updated_at.desc())
        .limit(1)
    )
    if roadmap:
        milestones = await roadmap_service.list_milestones(db, roadmap.id)
        done = sum(1 for m in milestones if m.status == MilestoneStatus.DONE)
        nxt = next((m.title for m in milestones if m.status != MilestoneStatus.DONE), None)
        lines.append(
            f"Current roadmap: {roadmap.title} ({done}/{len(milestones)} milestones done"
            f"{', next: ' + nxt if nxt else ''})"
        )
    return "\n".join(lines)


def _validation_message(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())


async def ask(db: AsyncSession, user: User, ai: AIClient, data: AskIn) -> AskOut:
    tz = parse_tz(data.tz)
    today = local_today(tz)
    actions: list[AssistantAction] = []

    async def execute(name: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            if name == "create_task":
                task = await task_service.create_task(
                    db, user.id, TaskCreate.model_validate({k: v for k, v in args.items() if v})
                )
                actions.append(AssistantAction(type="task_created", id=task.id, title=task.title))
                return {
                    "ok": True,
                    "id": str(task.id),
                    "title": task.title,
                    "due_date": str(task.due_date) if task.due_date else None,
                }
            if name == "create_job":
                job = await job_service.create_job(
                    db, user.id, JobCreate.model_validate({k: v for k, v in args.items() if v})
                )
                title = f"{job.role} at {job.company}"
                actions.append(AssistantAction(type="job_created", id=job.id, title=title))
                return {"ok": True, "id": str(job.id), "title": title, "status": job.status.value}
        except ValidationError as exc:
            return {"ok": False, "error": _validation_message(exc)}
        return {"ok": False, "error": f"Unknown tool {name}"}

    system = ASSISTANT_SYSTEM.format(
        name=user.display_name,
        today=f"{today:%A, %Y-%m-%d}",
        tz=tz.key,
        context=await build_context(db, user, today),
    )
    reply = await ai.chat_with_tools(
        system=system,
        history=[ChatTurn(role=h.role, content=h.content) for h in data.history],
        message=data.message,
        tools=TOOLS,
        execute=execute,
    )
    if not reply:
        reply = "Done." if actions else "Sorry, I couldn't come up with an answer."
    return AskOut(reply=reply, actions=actions)


async def rewrite(ai: AIClient, data: RewriteIn) -> str:
    prompt = f"{REWRITE_GUIDE[data.kind]}\n"
    if data.instruction:
        prompt += f"Extra instruction from the user: {data.instruction}\n"
    prompt += f"\nText:\n{data.text}"
    text = await ai.generate_text(system=REWRITE_SYSTEM, prompt=prompt)
    if not text:
        raise AIServiceError("The AI returned an empty answer")
    return text


def schedule(weeks: list[int], start: date, target: date | None) -> list[date]:
    """Cumulative milestone due dates; squeezed/stretched to end on `target` when given."""
    total = sum(weeks)
    span_days = (target - start).days if target and target > start else total * 7
    dates, acc = [], 0
    for w in weeks:
        acc += w
        dates.append(start + timedelta(days=max(1, round(span_days * acc / total))))
    return dates


async def generate_roadmap(
    db: AsyncSession, user: User, ai: AIClient, data: RoadmapGenerate
) -> RoadmapDetail:
    prompt = f"Goal: {data.goal}\n"
    if data.hours_per_week:
        prompt += f"Available time: {data.hours_per_week} hours per week.\n"
    if data.target_date:
        prompt += f"Target date: {data.target_date.isoformat()}.\n"
    plan = await ai.generate_structured(system=ROADMAP_SYSTEM, prompt=prompt, schema=RoadmapPlan)
    planned = [m for m in plan.milestones if m.title.strip()][:8]
    if not planned:
        raise AIServiceError("The AI did not return any milestones")
    start = datetime.now(UTC).date()
    weeks = [min(max(m.estimated_weeks, 1), 12) for m in planned]
    due = schedule(weeks, start, data.target_date)
    milestones = [
        MilestoneCreate(
            title=m.title.strip()[:200],
            description=m.description.strip(),
            resources=[
                Resource(title=r.title[:200], url=r.url[:1000])
                for r in m.resources[:6]
                if r.url.startswith(("http://", "https://"))
            ],
            target_date=d,
        )
        for m, d in zip(planned, due, strict=True)
    ]
    return await roadmap_service.create_roadmap(
        db,
        user.id,
        RoadmapCreate(
            title=(plan.title.strip() or data.goal)[:200],
            goal=plan.goal.strip() or data.goal,
            target_date=data.target_date or due[-1],
            milestones=milestones,
        ),
    )
