"""record the classifying model on classification_log

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    # Nullable: rows written before this column existed have no recorded model.
    op.execute("ALTER TABLE classification_log ADD COLUMN model TEXT")


def downgrade():
    op.execute("ALTER TABLE classification_log DROP COLUMN model")
