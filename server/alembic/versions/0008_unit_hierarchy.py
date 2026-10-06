"""Move unit conversion onto a global two-level unit hierarchy.

A business unit may hang off a base unit: 1 business unit = base_quantity base units
(e.g. 1 箱 = 12 个). Only two levels are allowed, so a unit that already serves as
somebody's base unit cannot itself declare one; that half of the rule needs the rows
to be visible, so it lives in the service layer rather than a CHECK constraint.

The per-item conversion table is dropped: it held no rows and the global hierarchy
replaces it, leaving the system with a single notion of "conversion".

Revision ID: 0008_unit_hierarchy
Revises: 0007_sales_order_numbers
"""

from alembic import op

revision = "0008_unit_hierarchy"
down_revision = "0007_sales_order_numbers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE units ADD COLUMN base_unit_id uuid REFERENCES units(id)")
    op.execute("ALTER TABLE units ADD COLUMN base_quantity numeric(20,6)")
    # 基本单位与基本数量必须成对出现
    op.execute("""
        ALTER TABLE units ADD CONSTRAINT units_base_pair_check
        CHECK ((base_unit_id IS NULL) = (base_quantity IS NULL))
    """)
    op.execute("""
        ALTER TABLE units ADD CONSTRAINT units_base_quantity_check
        CHECK (base_quantity IS NULL OR base_quantity > 0)
    """)
    op.execute("""
        ALTER TABLE units ADD CONSTRAINT units_base_not_self_check
        CHECK (base_unit_id IS NULL OR base_unit_id <> id)
    """)
    op.execute("DROP TABLE item_unit_conversions")


def downgrade() -> None:
    op.execute("""
        CREATE TABLE item_unit_conversions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            item_id uuid NOT NULL REFERENCES items(id) ON DELETE CASCADE,
            unit_id uuid NOT NULL REFERENCES units(id),
            factor_to_base numeric(20,6) NOT NULL CHECK (factor_to_base > 0),
            UNIQUE (item_id, unit_id)
        )
    """)
    op.execute("ALTER TABLE units DROP CONSTRAINT units_base_not_self_check")
    op.execute("ALTER TABLE units DROP CONSTRAINT units_base_quantity_check")
    op.execute("ALTER TABLE units DROP CONSTRAINT units_base_pair_check")
    op.execute("ALTER TABLE units DROP COLUMN base_quantity")
    op.execute("ALTER TABLE units DROP COLUMN base_unit_id")
