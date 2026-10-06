"""Generate stocktake numbers when the user leaves them blank.

``PD`` = 盘点，与 SC/SCXH/SCRK/DB/XS/XC/XT/CG/CR/CT 同一套「前缀+日期+四位流水」。

Revision ID: 0018_stocktake_numbers
Revises: 0017_production_op_numbers
"""

from alembic import op

revision = "0018_stocktake_numbers"
down_revision = "0017_production_op_numbers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE stocktake_number_counters (
            organization_id uuid NOT NULL REFERENCES organizations(id),
            document_date date NOT NULL,
            last_value bigint NOT NULL CHECK (last_value > 0),
            PRIMARY KEY (organization_id, document_date)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE stocktake_number_counters")
