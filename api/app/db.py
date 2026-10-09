"""Database engine, session factory and ORM models (SQLAlchemy 2, async)."""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from sqlalchemy import JSON, TypeDecorator, inspect, text, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .config import settings


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class TZDateTime(TypeDecorator):
    """DateTime that always returns timezone-aware UTC values (SQLite drops tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class Circle(Base):
    __tablename__ = "circles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    members: Mapped[list["CircleMember"]] = relationship(
        back_populates="circle", cascade="all, delete-orphan", lazy="selectin"
    )


class CircleMember(Base):
    __tablename__ = "circle_members"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    circle_id: Mapped[str] = mapped_column(ForeignKey("circles.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(20))  # senior | trusted_contact
    display_name: Mapped[str] = mapped_column(String(120))
    relationship_label: Mapped[str | None] = mapped_column("relationship", String(60), nullable=True)
    phone_e164: Mapped[str | None] = mapped_column(String(20), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Africa/Lagos")
    companion_call_time: Mapped[str | None] = mapped_column(String(5), nullable=True)  # "09:00"
    companion_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    personal_facts: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    circle: Mapped[Circle] = relationship(back_populates="members")
    voice: Mapped["VoiceProfile | None"] = relationship(
        back_populates="member", cascade="all, delete-orphan", lazy="selectin", uselist=False
    )


class VoiceProfile(Base):
    __tablename__ = "voice_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    member_id: Mapped[str] = mapped_column(
        ForeignKey("circle_members.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[str] = mapped_column(String(20), default="processing")
    sample_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resemble_voice_uuid: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resemble_identity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    consent_text_version: Mapped[str] = mapped_column(String(20))
    consent_at: Mapped[datetime] = mapped_column(TZDateTime())
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    member: Mapped[CircleMember] = relationship(back_populates="voice")


class PracticeCall(Base):
    __tablename__ = "practice_calls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    circle_id: Mapped[str] = mapped_column(ForeignKey("circles.id", ondelete="CASCADE"), index=True)
    senior_member_id: Mapped[str] = mapped_column(ForeignKey("circle_members.id"))
    voice_member_id: Mapped[str] = mapped_column(ForeignKey("circle_members.id"))
    scenario: Mapped[str] = mapped_column(String(60))
    difficulty: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    provider_call_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    transcript: Mapped[list[Any]] = mapped_column(JSON, default=list)
    turns: Mapped[int] = mapped_column(Integer, default=0)
    safety_stop: Mapped[bool] = mapped_column(Boolean, default=False)
    engine_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class DetectionCheck(Base):
    __tablename__ = "detection_checks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    circle_id: Mapped[str] = mapped_column(ForeignKey("circles.id", ondelete="CASCADE"), index=True)
    claimed_member_id: Mapped[str] = mapped_column(ForeignKey("circle_members.id"))
    audio_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="processing")
    synthetic_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    speaker_match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class CompanionCall(Base):
    __tablename__ = "companion_calls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    circle_id: Mapped[str] = mapped_column(ForeignKey("circles.id", ondelete="CASCADE"), index=True)
    senior_member_id: Mapped[str] = mapped_column(ForeignKey("circle_members.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    provider_call_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    recall_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[list[Any]] = mapped_column(JSON, default=list)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    flags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    turns: Mapped[int] = mapped_column(Integer, default=0)
    engine_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    circle_id: Mapped[str] = mapped_column(ForeignKey("circles.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(30))  # scam_risk | wellbeing_change | detection_fake
    severity: Mapped[str] = mapped_column(String(10))  # info | warning | urgent
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    circle_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class ProcessedEvent(Base):
    __tablename__ = "processed_webhook_events"
    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


if settings.is_sqlite:
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(settings.DATABASE_URL, connect_args={"timeout": 30}, poolclass=NullPool)
else:
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


def _add_missing_columns(sync_conn) -> None:
    """Lightweight auto-migration: create_all() never alters existing tables, so a database created by an
    older version of the schema would be missing newer columns (e.g. practice_calls.provider_call_id).
    Add any column the models define that the live table lacks."""
    log = logging.getLogger("voicecircle.db")
    insp = inspect(sync_conn)
    dialect = sync_conn.dialect
    preparer = dialect.identifier_preparer
    existing_tables = set(insp.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            ddl = f"ALTER TABLE {preparer.quote(table.name)} ADD COLUMN {preparer.quote(col.name)} {col.type.compile(dialect=dialect)}"
            default = getattr(col.default, "arg", None) if col.default is not None else None
            if isinstance(default, bool):
                ddl += f" DEFAULT {'TRUE' if default else 'FALSE'}" if not dialect.name == "sqlite" else f" DEFAULT {int(default)}"
            elif isinstance(default, (int, float)):
                ddl += f" DEFAULT {default}"
            elif isinstance(default, str):
                ddl += " DEFAULT '" + default.replace("'", "''") + "'"
            # Added nullable on purpose: existing rows have no value, and NOT NULL would fail the ALTER.
            sync_conn.execute(text(ddl))
            log.warning("Migrated: added column %s.%s", table.name, col.name)
            if col.index:
                idx = f"ix_{table.name}_{col.name}"
                sync_conn.execute(
                    text(f"CREATE INDEX IF NOT EXISTS {preparer.quote(idx)} ON {preparer.quote(table.name)} ({preparer.quote(col.name)})")
                )


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
