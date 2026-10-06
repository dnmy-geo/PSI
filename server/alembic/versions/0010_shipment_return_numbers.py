"""Generate sales shipment and return numbers when the user leaves them blank.

Sales orders already auto-number as ``XS{date}{seq}``; shipments and returns
kept requiring a typed number. They get their own per-day counters so the form
can leave the field empty (``XC`` = 销售出库, ``XT`` = 销售退货).

Revision ID: 0010_shipment_return_numbers
Revises: 0009_line_sort_order
"""

from alembic import op

revision = "0010_shipment_return_numbers"
down_revision = "0009_line_sort_order"
branch_labels = None
depends_on = None

COUNTER_TABLES = ["sales_shipment_number_counters", "sales_return_number_counters"]


def upgrade() -> None:
    for table in COUNTER_TABLES:
        op.execute(f"""
            CREATE TABLE {table} (
                organization_id uuid NOT NULL REFERENCES organizations(id),
                document_date date NOT NULL,
                last_value bigint NOT NULL CHECK (last_value > 0),
                PRIMARY KEY (organization_id, document_date)
            )
        """)


def downgrade() -> None:
    for table in COUNTER_TABLES:
        op.execute(f"DROP TABLE {table}")
