from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from littlehive.core.permissions.policy_engine import PermissionProfile


class ProviderStatusModel(BaseModel):
    name: str
    health: bool
    score: float
    breaker_state: str
    failures: int
    latency_ms: float


class OverviewModel(BaseModel):
    version: str
    environment: str
    instance: str
    safe_mode: bool
    active_tasks: int
    total_tasks: int
    providers_configured: list[str]
    uptime_seconds: int


class TaskSummaryModel(BaseModel):
    task_id: int
    session_id: int
    status: str
    summary: str
    created_at: datetime
    updated_at: datetime


class TraceSummaryModel(BaseModel):
    task_id: int
    session_id: int
    request_id: str
    agent_sequence: str
    transfer_count: int
    provider_attempts: int
    tool_attempts: int
    retry_count: int
    breaker_events: int
    trim_event_count: int
    avg_estimated_tokens: float
    outcome_status: str
    created_at: datetime


class PermissionProfileResponse(BaseModel):
    current_profile: PermissionProfile
    safe_mode: bool
    updated_by: str
    updated_at: datetime


class PermissionProfileUpdateRequest(BaseModel):
    profile: PermissionProfile


class PendingConfirmationModel(BaseModel):
    id: int
    task_id: int | None
    session_id: int | None
    action_type: str
    action_summary: str
    status: str
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None
    decided_by: str


class ConfirmationDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(confirm|deny)$")
    actor: str = "operator"


class ConfirmationCreateRequest(BaseModel):
    action_type: str
    action_summary: str
    task_id: int | None = None
    session_id: int | None = None
    ttl_seconds: int = 300
    payload: dict = Field(default_factory=dict)


class AgentUpdateRequest(BaseModel):
    safe_mode: bool | None = None


class UsageSummaryModel(BaseModel):
    avg_estimated_prompt_tokens: float
    trim_event_count: int
    over_budget_incidents: int
    trace_count: int


class FailureSummaryModel(BaseModel):
    category: str
    component: str
    error_type: str
    signature: str
    count: int
    recovered: int
    last_strategy: str
    last_seen: str


class UserProfileModel(BaseModel):
    id: int
    telegram_user_id: int | None
    external_id: str
    display_name: str
    preferred_timezone: str
    city: str
    country: str
    profile_notes: str
    profile_updated_at: datetime
    created_at: datetime


class UserProfileUpdateRequest(BaseModel):
    display_name: str | None = None
    preferred_timezone: str | None = None
    city: str | None = None
    country: str | None = None
    profile_notes: str | None = None
