"""Keep a per-day counter for generated sales order numbers.

Revision ID: 0007_sales_order_numbers
Revises: 0006_carryover_return_sources
"""

from alembic import op

revision = "0007_sales_order_numbers"
down_revision = "0006_carryover_return_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE sales_order_number_counters (
            organization_id uuid NOT NULL REFERENCES organizations(id),
            document_date date NOT NULL,
            last_value bigint NOT NULL CHECK (last_value > 0),
            PRIMARY KEY (organization_id, document_date)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE sales_order_number_counters")
