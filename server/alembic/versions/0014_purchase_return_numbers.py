"""Generate purchase return numbers when the user leaves them blank.

``CT`` = 采购退货，与 XS/XC/XT/CG/CR 同一套「前缀+日期+四位流水」。

Revision ID: 0014_purchase_return_numbers
Revises: 0013_timestamps_everywhere
"""

from alembic import op

revision = "0014_purchase_return_numbers"
down_revision = "0013_timestamps_everywhere"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE purchase_return_number_counters (
            organization_id uuid NOT NULL REFERENCES organizations(id),
            document_date date NOT NULL,
            last_value bigint NOT NULL CHECK (last_value > 0),
            PRIMARY KEY (organization_id, document_date)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE purchase_return_number_counters")
