"""phase2 optimization tables and fields

Revision ID: 0003_phase2_optimization
Revises: 0002_phase1_runtime
Create Date: 2026-02-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_phase2_optimization"
down_revision = "0002_phase1_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("memories", sa.Column("card_type", sa.String(length=64), nullable=False, server_default="fact"))
    op.add_column("memories", sa.Column("pinned", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("memories", sa.Column("error_signature", sa.String(length=256), nullable=False, server_default=""))
    op.add_column("memories", sa.Column("fix_text", sa.Text(), nullable=False, server_default=""))
    op.add_column("memories", sa.Column("source", sa.String(length=64), nullable=False, server_default="runtime"))
    op.add_column("memories", sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"))
    op.add_column("memories", sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"))

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


def downgrade() -> None:
    op.drop_table("transfer_events")
    op.drop_column("memories", "success_count")
    op.drop_column("memories", "confidence")
    op.drop_column("memories", "source")
    op.drop_column("memories", "fix_text")
    op.drop_column("memories", "error_signature")
    op.drop_column("memories", "pinned")
    op.drop_column("memories", "card_type")
