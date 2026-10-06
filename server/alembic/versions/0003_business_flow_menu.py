"""Add the read-only business flow navigation page.

Revision ID: 0003_business_flow_menu
Revises: 0002_reconciliation_accounts
"""

from alembic import op

revision = "0003_business_flow_menu"
down_revision = "0002_reconciliation_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO menus (code, name, path, sort_order)
        VALUES ('business_flow', '业务全景', '/business-flow', 150)
        ON CONFLICT (code) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE menu_id IN (SELECT id FROM menus WHERE code = 'business_flow')")
    op.execute("DELETE FROM menus WHERE code = 'business_flow'")
