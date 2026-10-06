"""Generate production consumption and receipt numbers when left blank.

``SCXH`` = 生产消耗，``SCRK`` = 生产入库，与 SC/DB/XS/XC/XT/CG/CR/CT 同一套
「前缀+日期+四位流水」。领料（尚未接入）留 SCLL。

Revision ID: 0017_production_op_numbers
Revises: 0016_production_plan_numbers
"""

from alembic import op

revision = "0017_production_op_numbers"
down_revision = "0016_production_plan_numbers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("production_consumption_number_counters", "production_receipt_number_counters"):
        op.execute(f"""
            CREATE TABLE {table} (
                organization_id uuid NOT NULL REFERENCES organizations(id),
                document_date date NOT NULL,
                last_value bigint NOT NULL CHECK (last_value > 0),
                PRIMARY KEY (organization_id, document_date)
            )
        """)


def downgrade() -> None:
    for table in ("production_receipt_number_counters", "production_consumption_number_counters"):
        op.execute(f"DROP TABLE {table}")
