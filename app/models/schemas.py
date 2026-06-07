"""
Domain models for the outreach pipeline.

Every data structure flowing through the pipeline is a typed Pydantic model.
This guarantees:
  - Runtime validation at API boundaries
  - Serialization to JSON / CSV for export
  - Clear contracts between pipeline stages
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── Enums ────────────────────────────────────────────────────

class PipelineStage(str, Enum):
    """Stages in the outreach pipeline."""
    COMPANY_SEARCH = "company_search"
    CONTACT_DISCOVERY = "contact_discovery"
    EMAIL_RESOLUTION = "email_resolution"
    OUTREACH_GENERATION = "outreach_generation"
    EMAIL_SENDING = "email_sending"


# ── Core Models ──────────────────────────────────────────────

class Company(BaseModel):
    """A target company discovered through lookalike search."""
    domain: str = Field(..., description="Company website domain")
    name: str = Field(default="", description="Company display name")
    industry: str = Field(default="", description="Primary industry")
    size: str = Field(default="", description="Employee count range")
    country: str = Field(default="", description="HQ country")
    description: str = Field(default="", description="Brief company description")
    similarity_score: Optional[float] = Field(default=None, description="Lookalike match score 0-1")
    source_domain: str = Field(default="", description="The seed domain this was matched from")

    @field_validator("domain", mode="before")
    @classmethod
    def normalize_domain(cls, v: str) -> str:
        """Strip protocol and trailing slashes for consistency."""
        if isinstance(v, str):
            v = v.strip().lower()
            for prefix in ("https://", "http://", "www."):
                if v.startswith(prefix):
                    v = v[len(prefix):]
            v = v.rstrip("/")
        return v


class Contact(BaseModel):
    """A decision maker discovered at a target company."""
    person_id: str = Field(default="", description="Unique identifier from source")
    first_name: str = Field(default="", description="First name")
    last_name: str = Field(default="", description="Last name")
    full_name: str = Field(default="", description="Full display name")
    title: str = Field(default="", description="Job title")
    seniority: str = Field(default="", description="Seniority level")
    company_domain: str = Field(default="", description="Associated company domain")
    company_name: str = Field(default="", description="Associated company name")
    linkedin_url: str = Field(default="", description="LinkedIn profile URL")
    location: str = Field(default="", description="Geographic location")

    @property
    def display_name(self) -> str:
        """Return the best available display name."""
        if self.full_name:
            return self.full_name
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) if parts else "Unknown"


class EmailRecord(BaseModel):
    """A verified email address for a contact."""
    email: str = Field(..., description="Verified email address")
    contact_name: str = Field(default="", description="Associated contact name")
    contact_title: str = Field(default="", description="Contact job title")
    company_domain: str = Field(default="", description="Company domain")
    company_name: str = Field(default="", description="Company name")
    verification_status: str = Field(default="unknown", description="Verification result")
    confidence: Optional[float] = Field(default=None, description="Confidence score 0-1")
    source: str = Field(default="", description="Resolution source (prospeo/eazyreach)")


class OutreachMessage(BaseModel):
    """A personalized outreach email ready for sending."""
    to_email: str = Field(..., description="Recipient email address")
    to_name: str = Field(default="", description="Recipient display name")
    to_title: str = Field(default="", description="Recipient job title")
    company_name: str = Field(default="", description="Recipient company")
    company_domain: str = Field(default="", description="Recipient company domain")
    subject: str = Field(..., description="Email subject line")
    body_html: str = Field(..., description="Email body in HTML")
    body_text: str = Field(default="", description="Plain text fallback")
    status: str = Field(default="pending", description="pending | sent | failed | dry_run")
    sent_at: Optional[datetime] = Field(default=None, description="Timestamp of send")
    message_id: Optional[str] = Field(default=None, description="Brevo message ID")
    error: Optional[str] = Field(default=None, description="Error message if failed")


# ── Pipeline Result Models ───────────────────────────────────

class StageResult(BaseModel):
    """Result of a single pipeline stage execution."""
    stage: PipelineStage
    success: bool = True
    count: int = 0
    errors: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class PipelineResult(BaseModel):
    """Complete result of a pipeline execution."""
    run_id: str = Field(..., description="Unique run identifier")
    seed_domain: str = Field(..., description="Input seed domain")
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    dry_run: bool = False

    # Stage results
    stages: list[StageResult] = Field(default_factory=list)

    # Collected data
    companies: list[Company] = Field(default_factory=list)
    contacts: list[Contact] = Field(default_factory=list)
    emails: list[EmailRecord] = Field(default_factory=list)
    messages: list[OutreachMessage] = Field(default_factory=list)

    # Summary stats
    total_companies: int = 0
    total_contacts: int = 0
    total_emails: int = 0
    total_sent: int = 0
    total_failed: int = 0

    # Failed contacts report
    failed_contacts: list[dict] = Field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return 0.0

    @property
    def success_rate(self) -> float:
        if self.total_emails == 0:
            return 0.0
        return (self.total_sent / self.total_emails) * 100


class RunHistory(BaseModel):
    """Lightweight run record for history display."""
    run_id: str
    seed_domain: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    total_companies: int = 0
    total_contacts: int = 0
    total_emails: int = 0
    total_sent: int = 0
    total_failed: int = 0
    dry_run: bool = False
    status: str = "completed"
