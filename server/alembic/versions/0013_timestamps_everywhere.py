"""Give every listable table a ``created_at`` and an auto-maintained ``updated_at``.

列表页要显示创建/修改时间并按创建时间排序。多数业务表已有 ``created_at``；
这里补齐缺的（往来单位、单位、物料分类、部门、角色、菜单），给所有业务/资料/系统表加
``updated_at``（默认取 ``created_at``），并用触发器在每次 UPDATE 时自动刷新，
服务层代码无需逐个记得维护。

Revision ID: 0013_timestamps_everywhere
Revises: 0012_purchase_receipt_numbers
"""

from alembic import op

revision = "0013_timestamps_everywhere"
down_revision = "0012_purchase_receipt_numbers"
branch_labels = None
depends_on = None

# 需要 created_at 的表（若无）
NEED_CREATED = [
    "parties", "units", "item_categories", "departments", "roles", "menus",
]
# 需要 created_at + updated_at + 触发器的表：单据、资料与系统管理
TABLES = [
    # 单据
    "production_plans", "production_orders", "production_issues",
    "production_consumptions", "production_receipts",
    "purchase_orders", "purchase_receipts", "purchase_returns",
    "sales_orders", "sales_shipments", "sales_returns",
    "outsourcing_orders", "outsourcing_issues", "outsourcing_receipts",
    "stock_transfers", "stock_adjustments", "stocktakes", "opening_stock_docs",
    "cash_records", "party_opening_balances",
    # 基础资料
    "items", "item_categories", "parties", "units", "warehouses", "bom_headers",
    # 系统管理
    "departments", "roles", "users", "menus", "organizations",
]


def upgrade() -> None:
    for table in NEED_CREATED:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now()")
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS updated_at timestamptz")
        # 既有数据：修改时间就等于创建时间，界面上不会突然出现一批"刚改过"的老单据。
        op.execute(f"UPDATE {table} SET updated_at = COALESCE(updated_at, created_at)")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN updated_at SET NOT NULL")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN updated_at SET DEFAULT now()")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}")
        op.execute(f"""
            CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """)


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}")
        op.execute(f"ALTER TABLE {table} DROP COLUMN updated_at")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    for table in NEED_CREATED:
        op.execute(f"ALTER TABLE {table} DROP COLUMN created_at")
