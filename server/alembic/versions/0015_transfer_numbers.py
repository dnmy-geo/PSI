"""Generate stock transfer numbers when the user leaves them blank.

``DB`` = 调拨，与 XS/XC/XT/CG/CR/CT 同一套「前缀+日期+四位流水」。

Revision ID: 0015_transfer_numbers
Revises: 0014_purchase_return_numbers
"""

from alembic import op

revision = "0015_transfer_numbers"
down_revision = "0014_purchase_return_numbers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE stock_transfer_number_counters (
            organization_id uuid NOT NULL REFERENCES organizations(id),
            document_date date NOT NULL,
            last_value bigint NOT NULL CHECK (last_value > 0),
            PRIMARY KEY (organization_id, document_date)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE stock_transfer_number_counters")
