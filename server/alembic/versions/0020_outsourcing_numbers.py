"""Generate outsourcing order/issue/receipt numbers when left blank.

``WW`` = 委外单，``WWFL`` = 委外发料，``WWRK`` = 委外入库，与 SC/SCXH/SCRK/SCLL/PD/DB
及销售采购那套共用「前缀+日期+四位流水」。

Revision ID: 0020_outsourcing_numbers
Revises: 0019_production_issue_numbers
"""

from alembic import op

revision = "0020_outsourcing_numbers"
down_revision = "0019_production_issue_numbers"
branch_labels = None
depends_on = None

TABLES = ("outsourcing_order_number_counters", "outsourcing_issue_number_counters",
          "outsourcing_receipt_number_counters")


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"""
            CREATE TABLE {table} (
                organization_id uuid NOT NULL REFERENCES organizations(id),
                document_date date NOT NULL,
                last_value bigint NOT NULL CHECK (last_value > 0),
                PRIMARY KEY (organization_id, document_date)
            )
        """)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE {table}")
