"""base schema snapshot

Revision ID: 0001_base_schema
Revises:
Create Date: 2026-02-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_base_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(length=128), nullable=False, unique=True),
        sa.Column("telegram_user_id", sa.Integer(), nullable=True, unique=True),
        sa.Column("display_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("preferred_timezone", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("city", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("country", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("profile_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("profile_updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("latest_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("channel", "external_id", name="uq_sessions_channel_external"),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("summary", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "task_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "memories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("memory_type", sa.String(length=64), nullable=False, server_default="note"),
        sa.Column("card_type", sa.String(length=64), nullable=False, server_default="fact"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("pinned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_signature", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("fix_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="runtime"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "session_summaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("sessions.id"), nullable=False, unique=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("sessions.id"), nullable=True),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "provider_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("sessions.id"), nullable=True),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "transfer_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("from_agent", sa.String(length=64), nullable=False),
        sa.Column("to_agent", sa.String(length=64), nullable=False),
        sa.Column("subtask", sa.String(length=512), nullable=False),
        sa.Column("relevant_memory_ids", sa.Text(), nullable=False, server_default=""),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "failure_fingerprints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("component", sa.String(length=128), nullable=False),
        sa.Column("error_type", sa.String(length=128), nullable=False),
        sa.Column("message_signature", sa.String(length=256), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("recovered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_recovery_strategy", sa.String(length=64), nullable=False, server_default=""),
    )

    op.create_table(
        "task_trace_summaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("agent_sequence", sa.Text(), nullable=False, server_default=""),
        sa.Column("transfer_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("breaker_events", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trim_event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_estimated_tokens", sa.Float(), nullable=False, server_default="0"),
        sa.Column("outcome_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "permission_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("current_profile", sa.String(length=64), nullable=False, server_default="execute_safe"),
        sa.Column("updated_by", sa.String(length=128), nullable=False, server_default="system"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "runtime_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("safe_mode", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(length=128), nullable=False, server_default="system"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "permission_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor", sa.String(length=128), nullable=False, server_default="system"),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("previous_profile", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("next_profile", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "pending_confirmations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("sessions.id"), nullable=True),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("action_summary", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="waiting_confirmation"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decided_by", sa.String(length=128), nullable=False, server_default=""),
    )
    op.create_index("ix_pending_confirmations_status", "pending_confirmations", ["status"], unique=False)

    op.create_table(
        "principals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel", sa.String(length=32), nullable=False, server_default="telegram"),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("channel", "external_id", name="uq_principals_channel_external"),
    )

    op.create_table(
        "principal_grants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("principal_id", sa.Integer(), sa.ForeignKey("principals.id"), nullable=False),
        sa.Column("grant_type", sa.String(length=64), nullable=False, server_default="chat_access"),
        sa.Column("is_allowed", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(length=128), nullable=False, server_default="system"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("principal_id", "grant_type", name="uq_principal_grants_type"),
    )

    op.create_table(
        "runtime_control_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(length=64), nullable=False, server_default="restart_services"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("requested_by", sa.String(length=128), nullable=False, server_default="system"),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("runtime_control_events")
    op.drop_table("principal_grants")
    op.drop_table("principals")
    op.drop_index("ix_pending_confirmations_status", table_name="pending_confirmations")
    op.drop_table("pending_confirmations")
    op.drop_table("permission_audit_events")
    op.drop_table("runtime_state")
    op.drop_table("permission_state")
    op.drop_table("task_trace_summaries")
    op.drop_table("failure_fingerprints")
    op.drop_table("transfer_events")
    op.drop_table("provider_calls")
    op.drop_table("tool_calls")
    op.drop_table("session_summaries")
    op.drop_table("memories")
    op.drop_table("task_steps")
    op.drop_table("tasks")
    op.drop_table("messages")
    op.drop_table("sessions")
    op.drop_table("users")
