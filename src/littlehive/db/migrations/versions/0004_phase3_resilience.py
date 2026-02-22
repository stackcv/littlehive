"""phase3 resilience tables

Revision ID: 0004_phase3_resilience
Revises: 0003_phase2_optimization
Create Date: 2026-02-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_phase3_resilience"
down_revision = "0003_phase2_optimization"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
    op.create_index(
        "ix_failure_fingerprint_key",
        "failure_fingerprints",
        ["category", "component", "error_type", "message_signature"],
        unique=False,
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


def downgrade() -> None:
    op.drop_table("task_trace_summaries")
    op.drop_index("ix_failure_fingerprint_key", table_name="failure_fingerprints")
    op.drop_table("failure_fingerprints")
