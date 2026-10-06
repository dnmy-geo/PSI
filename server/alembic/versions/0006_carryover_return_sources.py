"""Reference historical fulfillment without replaying inventory or settlement.

Revision ID: 0006_carryover_return_sources
Revises: 0005_carryover_documents
"""

from alembic import op

revision = "0006_carryover_return_sources"
down_revision = "0005_carryover_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sales_shipments ADD COLUMN is_opening_reference boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE purchase_receipts ADD COLUMN is_opening_reference boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE carryover_documents ADD COLUMN historical_order_id uuid")
    op.execute("ALTER TABLE carryover_lines ADD COLUMN historical_source_id uuid")
    op.execute("ALTER TABLE carryover_lines ADD COLUMN historical_source_line_id uuid")


def downgrade() -> None:
    op.execute("ALTER TABLE carryover_lines DROP COLUMN historical_source_line_id")
    op.execute("ALTER TABLE carryover_lines DROP COLUMN historical_source_id")
    op.execute("ALTER TABLE carryover_documents DROP COLUMN historical_order_id")
    op.execute("ALTER TABLE purchase_receipts DROP COLUMN is_opening_reference")
    op.execute("ALTER TABLE sales_shipments DROP COLUMN is_opening_reference")
