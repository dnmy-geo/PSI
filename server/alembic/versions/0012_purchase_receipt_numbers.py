"""Generate purchase receipt numbers when the user leaves them blank.

``CR`` = 采购入库，与 XS/XC/XT/CG 同一套「前缀+日期+四位流水」。

Revision ID: 0012_purchase_receipt_numbers
Revises: 0011_purchase_order_numbers
"""

from alembic import op

revision = "0012_purchase_receipt_numbers"
down_revision = "0011_purchase_order_numbers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE purchase_receipt_number_counters (
            organization_id uuid NOT NULL REFERENCES organizations(id),
            document_date date NOT NULL,
            last_value bigint NOT NULL CHECK (last_value > 0),
            PRIMARY KEY (organization_id, document_date)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE purchase_receipt_number_counters")
