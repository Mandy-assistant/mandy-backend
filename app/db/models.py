"""Import every model so `Base.metadata` is complete (used by Alembic and tests)."""

from app.db.base import Base
from app.features.auth.models import PasskeyCredential, RecoveryCode, User
from app.features.jobs.models import Job, JobStatusEvent
from app.features.profile.models import Education, Experience, Profile, Skill
from app.features.resumes.models import Resume, ResumeVersion
from app.features.roadmaps.models import Milestone, Roadmap
from app.features.tasks.models import Task

__all__ = [
    "Base",
    "Education",
    "Experience",
    "Job",
    "JobStatusEvent",
    "Milestone",
    "PasskeyCredential",
    "Profile",
    "RecoveryCode",
    "Resume",
    "ResumeVersion",
    "Roadmap",
    "Skill",
    "Task",
    "User",
]
