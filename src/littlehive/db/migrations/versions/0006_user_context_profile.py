"""add optional user context profile fields

Revision ID: 0006_user_context_profile
Revises: 0005_phase45_admin_controls
Create Date: 2026-02-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_user_context_profile"
down_revision = "0005_phase45_admin_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(length=128), nullable=False, server_default=""))
    op.add_column("users", sa.Column("preferred_timezone", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("users", sa.Column("city", sa.String(length=128), nullable=False, server_default=""))
    op.add_column("users", sa.Column("country", sa.String(length=128), nullable=False, server_default=""))
    op.add_column("users", sa.Column("profile_notes", sa.Text(), nullable=False, server_default=""))
    op.add_column(
        "users",
        sa.Column("profile_updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.alter_column("users", "profile_updated_at", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "profile_updated_at")
    op.drop_column("users", "profile_notes")
    op.drop_column("users", "country")
    op.drop_column("users", "city")
    op.drop_column("users", "preferred_timezone")
    op.drop_column("users", "display_name")
