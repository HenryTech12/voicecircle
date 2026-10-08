"""Pydantic request/response schemas (the API contract shared with the frontend)."""
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

E164 = re.compile(r"^\+[1-9]\d{6,14}$")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

Role = Literal["senior", "trusted_contact"]
Difficulty = Literal["easy", "medium", "hard"]


def check_phone(v):
    if v and not E164.match(v):
        raise ValueError("phone must be in E.164 format, e.g. +2348012345678")
    return v


def check_time(v):
    if v and not HHMM.match(v):
        raise ValueError("time must be HH:MM (24h)")
    return v


def check_tz(v):
    if v is None:
        return v
    from zoneinfo import ZoneInfo

    try:
        ZoneInfo(v)
    except Exception:
        raise ValueError("unknown timezone")
    return v


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth ----------
class DevLoginIn(BaseModel):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(ORM):
    id: str
    email: str
    full_name: str | None = None


class CircleBrief(BaseModel):
    id: str
    name: str
    role: str


class MeOut(UserOut):
    circles: list[CircleBrief]


class AuthConfigOut(BaseModel):
    auth_mode: str
    mock_providers: bool
    demo_mode: bool


# ---------- circles & members ----------
class CircleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    my_display_name: str | None = Field(default=None, max_length=120)
    my_relationship: str | None = Field(default=None, max_length=60)
    my_phone_e164: str | None = None

    @field_validator("my_phone_e164")
    @classmethod
    def _phone(cls, v):
        if v and not E164.match(v):
            raise ValueError("phone must be in E.164 format, e.g. +2348012345678")
        return v


class VoiceStatusOut(ORM):
    id: str | None = None
    status: Literal["none", "processing", "enrolled", "failed"] = "none"
    error: str | None = None
    consent_at: datetime | None = None
    created_at: datetime | None = None


class MemberOut(ORM):
    id: str
    circle_id: str
    user_id: str | None
    role: str
    display_name: str
    relationship: str | None = Field(default=None, validation_alias="relationship_label")
    phone_e164: str | None
    timezone: str
    companion_call_time: str | None
    companion_enabled: bool
    personal_facts: list[str] = []
    voice_status: str = "none"
    created_at: datetime


class MemberIn(BaseModel):
    role: Role
    display_name: str = Field(min_length=1, max_length=120)
    relationship: str | None = Field(default=None, max_length=60)
    phone_e164: str | None = None
    timezone: str = "Africa/Lagos"
    companion_call_time: str | None = None
    companion_enabled: bool = False
    personal_facts: list[str] = []
    link_to_me: bool = False  # trusted contact representing the current user

    @field_validator("phone_e164")
    @classmethod
    def _phone(cls, v):
        return check_phone(v)

    @field_validator("companion_call_time")
    @classmethod
    def _time(cls, v):
        return check_time(v)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v):
        return check_tz(v)


class MemberPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    relationship: str | None = Field(default=None, max_length=60)
    phone_e164: str | None = None
    timezone: str | None = None
    companion_call_time: str | None = None
    companion_enabled: bool | None = None
    personal_facts: list[str] | None = None

    @field_validator("phone_e164")
    @classmethod
    def _phone(cls, v):
        return check_phone(v)

    @field_validator("companion_call_time")
    @classmethod
    def _time(cls, v):
        return check_time(v)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v):
        return check_tz(v)


class CircleStats(BaseModel):
    voices_enrolled: int
    last_practice_score: int | None
    last_practice_at: datetime | None
    last_companion_at: datetime | None
    open_alerts: int
    detections: int


class CircleOut(ORM):
    id: str
    name: str
    owner_id: str
    created_at: datetime
    members: list[MemberOut]
    stats: CircleStats | None = None


# ---------- voice ----------
class VoicePromptsOut(BaseModel):
    prompts: list[str]
    consent_text: str
    consent_version: str


# ---------- practice ----------
class ScenarioOut(BaseModel):
    key: str
    title: str
    description: str
    difficulties: list[str]


class PracticeCallIn(BaseModel):
    senior_member_id: str
    voice_member_id: str
    scenario: str
    difficulty: Difficulty
    scheduled_for: datetime | None = None


class TranscriptLine(BaseModel):
    speaker: str
    text: str
    t_ms: int = 0


class PracticeCallOut(ORM):
    id: str
    circle_id: str
    senior_member_id: str
    voice_member_id: str
    scenario: str
    difficulty: str
    status: str
    outcome: str | None
    score: int | None
    feedback: dict[str, Any] | None
    transcript: list[TranscriptLine]
    turns: int
    safety_stop: bool
    duration_seconds: int | None
    scheduled_for: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


# ---------- detection ----------
class DetectionOut(ORM):
    id: str
    circle_id: str
    claimed_member_id: str
    claimed_member_name: str | None = None
    original_filename: str | None
    status: str
    verdict: str | None
    synthetic_score: float | None
    speaker_match_score: float | None
    explanation: str | None
    error: str | None
    created_at: datetime


# ---------- companion ----------
class CompanionCallOut(ORM):
    id: str
    circle_id: str
    senior_member_id: str
    status: str
    recall_question: str | None
    transcript: list[TranscriptLine]
    summary: str | None
    metrics: dict[str, Any] | None
    flags: list[Any]
    duration_seconds: int | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


class TrendPoint(BaseModel):
    date: str
    wpm: float | None = None
    latency_ms: float | None = None
    filler_rate: float | None = None
    recall: str | None = None
    mood: str | None = None


class TrendsOut(BaseModel):
    member_id: str
    days: int
    points: list[TrendPoint]
    baseline: dict[str, float | None]
    flags: list[str]


# ---------- alerts ----------
class AlertOut(ORM):
    id: str
    circle_id: str
    type: str
    severity: str
    title: str
    message: str
    source_id: str | None
    acknowledged_at: datetime | None
    created_at: datetime


# ---------- dev simulator ----------
class SimSayIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class OkOut(BaseModel):
    ok: bool = True
    detail: str | None = None


TokenOut.model_rebuild()
