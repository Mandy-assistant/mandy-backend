"""Import every model so `Base.metadata` is complete (used by Alembic and tests)."""

from app.db.base import Base
from app.features.auth.models import PasskeyCredential, RecoveryCode, User
from app.features.discover.models import JobMatch, JobPosting
from app.features.focus.models import FocusSession
from app.features.jobs.models import Job, JobStatusEvent
from app.features.news.models import NewsInsight, NewsInteraction, NewsItem, SavedNews
from app.features.personalize.models import InterestProfile, SearchEvent
from app.features.profile.models import Education, Experience, Profile, Skill
from app.features.resumes.models import Resume, ResumeVersion
from app.features.roadmaps.models import Milestone, Roadmap
from app.features.tasks.models import Task

__all__ = [
    "Base",
    "Education",
    "Experience",
    "FocusSession",
    "InterestProfile",
    "Job",
    "JobMatch",
    "JobPosting",
    "JobStatusEvent",
    "Milestone",
    "NewsInsight",
    "NewsInteraction",
    "NewsItem",
    "PasskeyCredential",
    "Profile",
    "RecoveryCode",
    "Resume",
    "ResumeVersion",
    "Roadmap",
    "SavedNews",
    "SearchEvent",
    "Skill",
    "Task",
    "User",
]
