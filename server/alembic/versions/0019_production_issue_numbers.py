"""Generate production issue numbers when the user leaves them blank.

``SCLL`` = 生产领料，与 SC/SCXH/SCRK/PD/DB/XS/XC/XT/CG/CR/CT 同一套「前缀+日期+四位流水」。

Revision ID: 0019_production_issue_numbers
Revises: 0018_stocktake_numbers
"""

from alembic import op

revision = "0019_production_issue_numbers"
down_revision = "0018_stocktake_numbers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE production_issue_number_counters (
            organization_id uuid NOT NULL REFERENCES organizations(id),
            document_date date NOT NULL,
            last_value bigint NOT NULL CHECK (last_value > 0),
            PRIMARY KEY (organization_id, document_date)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE production_issue_number_counters")
