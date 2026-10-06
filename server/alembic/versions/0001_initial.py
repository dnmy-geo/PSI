"""Initial PSI schema.

Revision ID: 0001_initial
Revises:
"""

from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = Path(__file__).with_suffix(".sql")
    statements = sql_path.read_text(encoding="utf-8").split(";")
    for statement in statements:
        if statement.strip():
            op.execute(sa.text(statement))


def downgrade() -> None:
    raise NotImplementedError("The baseline schema must not be dropped by migration downgrade")

