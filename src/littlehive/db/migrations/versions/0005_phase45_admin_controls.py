"""phase4+5 admin controls and confirmations

Revision ID: 0005_phase45_admin_controls
Revises: 0004_phase3_resilience
Create Date: 2026-02-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_phase45_admin_controls"
down_revision = "0004_phase3_resilience"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "permission_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("current_profile", sa.String(length=64), nullable=False, server_default="execute_safe"),
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


def downgrade() -> None:
    op.drop_index("ix_pending_confirmations_status", table_name="pending_confirmations")
    op.drop_table("pending_confirmations")
    op.drop_table("permission_audit_events")
    op.drop_table("permission_state")
