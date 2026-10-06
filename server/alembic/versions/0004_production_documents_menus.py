"""Expose production issue, consumption and receipt as production menus.

Revision ID: 0004_production_documents_menus
Revises: 0003_business_flow_menu
"""

from alembic import op

revision = "0004_production_documents_menus"
down_revision = "0003_business_flow_menu"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO menus (parent_id, code, name, path, sort_order)
        SELECT parent.id, entry.code, entry.name, entry.path, entry.sort_order
        FROM menus parent
        CROSS JOIN (VALUES
            ('production.issues', '生产领料', '/production/issues', 603),
            ('production.consumptions', '生产消耗', '/production/consumptions', 604),
            ('production.receipts', '生产入库', '/production/receipts', 605)
        ) AS entry(code, name, path, sort_order)
        WHERE parent.code = 'production'
        ON CONFLICT (code) DO NOTHING
    """)
    op.execute("""
        INSERT INTO role_permissions (role_id, menu_id, action_code)
        SELECT rp.role_id, target.id, rp.action_code
        FROM role_permissions rp
        JOIN menus source ON source.id = rp.menu_id AND source.code = 'production.orders'
        JOIN menus target ON target.code IN (
            'production.issues', 'production.consumptions', 'production.receipts'
        )
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM role_permissions
        WHERE menu_id IN (SELECT id FROM menus WHERE code IN (
            'production.issues', 'production.consumptions', 'production.receipts'
        ))
    """)
    op.execute("""
        DELETE FROM menus WHERE code IN (
            'production.issues', 'production.consumptions', 'production.receipts'
        )
    """)
