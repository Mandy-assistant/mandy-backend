"""Import every model so `Base.metadata` is complete (used by Alembic and tests)."""

from app.db.base import Base
from app.features.auth.models import PasskeyCredential, RecoveryCode, User
from app.features.focus.models import FocusSession
from app.features.jobs.models import Job, JobStatusEvent
from app.features.news.models import NewsItem, SavedNews
from app.features.profile.models import Education, Experience, Profile, Skill
from app.features.resumes.models import Resume, ResumeVersion
from app.features.roadmaps.models import Milestone, Roadmap
from app.features.tasks.models import Task

__all__ = [
    "Base",
    "Education",
    "Experience",
    "FocusSession",
    "Job",
    "JobStatusEvent",
    "Milestone",
    "NewsItem",
    "PasskeyCredential",
    "Profile",
    "RecoveryCode",
    "Resume",
    "ResumeVersion",
    "Roadmap",
    "SavedNews",
    "Skill",
    "Task",
    "User",
]
