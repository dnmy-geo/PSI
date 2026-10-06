"""Generate production plan numbers when the user leaves them blank.

``SC`` = 生产（计划），与 XS/XC/XT/CG/CR/CT/DB 同一套「前缀+日期+四位流水」。
其它生产单据（订单/领料/消耗/入库）接入自动取号时要另选前缀，别和 SC 撞。

Revision ID: 0016_production_plan_numbers
Revises: 0015_transfer_numbers
"""

from alembic import op

revision = "0016_production_plan_numbers"
down_revision = "0015_transfer_numbers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE production_plan_number_counters (
            organization_id uuid NOT NULL REFERENCES organizations(id),
            document_date date NOT NULL,
            last_value bigint NOT NULL CHECK (last_value > 0),
            PRIMARY KEY (organization_id, document_date)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE production_plan_number_counters")
