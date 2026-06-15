from datetime import datetime
from enum import Enum
from typing import Optional
from sqlmodel import Field, SQLModel


class ApplicationStatus(str, Enum):
    new = "new"
    prepared = "prepared"
    applied = "applied"
    interview = "interview"
    offer = "offer"
    rejected = "rejected"


class JobCategory(str, Enum):
    it = "it"
    wirtschaft = "wirtschaft"
    unknown = "unknown"


class JobSource(str, Enum):
    ba = "ba"
    adzuna = "adzuna"
    arbeitnow = "arbeitnow"
    himalayas = "himalayas"


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: Optional[int] = Field(default=None, primary_key=True)
    external_id: str = Field(unique=True, index=True)
    source: JobSource
    title: str
    company: str
    location: str
    description: str
    url: str
    category: JobCategory = JobCategory.unknown
    relevance_score: Optional[int] = None
    relevance_reason: Optional[str] = None
    posted_at: Optional[datetime] = None
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    extra_data: Optional[str] = None  # JSON: industry, work_time, contract, tags, remote
    workspace: str = Field(default="default", index=True)


class Application(SQLModel, table=True):
    __tablename__ = "applications"

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", unique=True, index=True)
    status: ApplicationStatus = ApplicationStatus.new
    saved: bool = False
    dismissed: bool = False
    viewed: bool = False
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    applied_at: Optional[datetime] = None


class CoverLetter(SQLModel, table=True):
    __tablename__ = "cover_letters"

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", unique=True, index=True)
    content: str
    is_edited: bool = False
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    edited_at: Optional[datetime] = None


class Config(SQLModel, table=True):
    __tablename__ = "config"

    id: int = Field(default=1, primary_key=True)
    profile_json: str = "{}"
    preferences_json: str = "{}"
