from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from littlehive.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    telegram_user_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (UniqueConstraint("channel", "external_id", name="uq_sessions_channel_external"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False, default="local")
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    latest_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    summary: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class TaskStep(Base):
    __tablename__ = "task_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class MemoryRecord(Base):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(64), nullable=False, default="note")
    card_type: Mapped[str] = mapped_column(String(64), nullable=False, default="fact")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    pinned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_signature: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    fix_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="runtime")
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.5)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class SessionSummary(Base):
    __tablename__ = "session_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), unique=True, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id"), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class ProviderCall(Base):
    __tablename__ = "provider_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id"), nullable=True)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class TransferEvent(Base):
    __tablename__ = "transfer_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    from_agent: Mapped[str] = mapped_column(String(64), nullable=False)
    to_agent: Mapped[str] = mapped_column(String(64), nullable=False)
    subtask: Mapped[str] = mapped_column(String(512), nullable=False)
    relevant_memory_ids: Mapped[str] = mapped_column(Text, nullable=False, default="")
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class FailureFingerprint(Base):
    __tablename__ = "failure_fingerprints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    component: Mapped[str] = mapped_column(String(128), nullable=False)
    error_type: Mapped[str] = mapped_column(String(128), nullable=False)
    message_signature: Mapped[str] = mapped_column(String(256), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    recovered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_recovery_strategy: Mapped[str] = mapped_column(String(64), nullable=False, default="")


class TaskTraceSummary(Base):
    __tablename__ = "task_trace_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_sequence: Mapped[str] = mapped_column(Text, nullable=False, default="")
    transfer_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    breaker_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trim_event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_estimated_tokens: Mapped[float] = mapped_column(nullable=False, default=0.0)
    outcome_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
