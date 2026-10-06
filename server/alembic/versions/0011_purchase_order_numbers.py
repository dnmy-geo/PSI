"""Generate purchase order numbers when the user leaves them blank.

Same ``前缀+日期+流水`` shape as the sales documents: ``CG`` = 采购订单. The
counter is per organization and day, matching ``sales_order_number_counters``.

Revision ID: 0011_purchase_order_numbers
Revises: 0010_shipment_return_numbers
"""

from alembic import op

revision = "0011_purchase_order_numbers"
down_revision = "0010_shipment_return_numbers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE purchase_order_number_counters (
            organization_id uuid NOT NULL REFERENCES organizations(id),
            document_date date NOT NULL,
            last_value bigint NOT NULL CHECK (last_value > 0),
            PRIMARY KEY (organization_id, document_date)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE purchase_order_number_counters")
