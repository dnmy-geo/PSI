"""Keep document detail lines in the order the user entered them.

Detail lines are written with their payload order but were read back with
``ORDER BY id``; because edits rebuild the lines with fresh UUIDs, the same
document showed a different row order after every save. Each line table now
carries an explicit ``sort_order`` (BOM lines already had one), written from the
payload index and used when reading. Existing rows are numbered by their current
``id`` order so nothing jumps on screen right after the migration.

Revision ID: 0009_line_sort_order
Revises: 0008_unit_hierarchy
"""

from alembic import op

revision = "0009_line_sort_order"
down_revision = "0008_unit_hierarchy"
branch_labels = None
depends_on = None

# (明细表, 所属单据外键列)。bom_lines 在 0001 就有 sort_order，不在此列。
LINE_TABLES = [
    ("production_plan_lines", "production_plan_id"),
    ("production_order_outputs", "production_order_id"),
    ("production_issue_lines", "issue_id"),
    ("production_consumption_lines", "consumption_id"),
    ("production_receipt_lines", "receipt_id"),
    ("purchase_order_lines", "purchase_order_id"),
    ("purchase_receipt_lines", "receipt_id"),
    ("purchase_return_lines", "purchase_return_id"),
    ("sales_order_lines", "sales_order_id"),
    ("sales_shipment_lines", "shipment_id"),
    ("sales_return_lines", "sales_return_id"),
    ("outsourcing_material_lines", "outsourcing_order_id"),
    ("outsourcing_output_lines", "outsourcing_order_id"),
    ("outsourcing_issue_lines", "issue_id"),
    ("outsourcing_receipt_lines", "receipt_id"),
    ("stock_adjustment_lines", "adjustment_id"),
    ("stocktake_lines", "stocktake_id"),
    ("stock_transfer_lines", "transfer_id"),
    ("opening_stock_lines", "opening_doc_id"),
]


def upgrade() -> None:
    for table, parent in LINE_TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN sort_order integer NOT NULL DEFAULT 0")
        # 既有明细按原展示顺序（id）编号，迁移后界面不会突然换序。
        op.execute(f"""
            UPDATE {table} AS target
            SET sort_order = numbered.position
            FROM (
                SELECT id, (row_number() OVER (PARTITION BY {parent} ORDER BY id) - 1)::int AS position
                FROM {table}
            ) AS numbered
            WHERE numbered.id = target.id
        """)


def downgrade() -> None:
    for table, _ in LINE_TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN sort_order")
