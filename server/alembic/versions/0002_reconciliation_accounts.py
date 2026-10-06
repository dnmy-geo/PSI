"""Separate customer, supplier and processor settlement accounts.

Revision ID: 0002_reconciliation_accounts
Revises: 0001_initial
"""

from alembic import op

revision = "0002_reconciliation_accounts"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE cash_records ADD COLUMN account_type text;
        ALTER TABLE party_opening_balances ADD COLUMN account_type text;

        UPDATE cash_records c SET account_type = CASE
            WHEN c.record_type = 'receipt' THEN 'customer'
            WHEN EXISTS (SELECT 1 FROM party_types t WHERE t.party_id = c.party_id
                         AND t.party_type = 'supplier')
             AND NOT EXISTS (SELECT 1 FROM party_types t WHERE t.party_id = c.party_id
                             AND t.party_type = 'processor') THEN 'supplier'
            WHEN EXISTS (SELECT 1 FROM party_types t WHERE t.party_id = c.party_id
                         AND t.party_type = 'processor')
             AND NOT EXISTS (SELECT 1 FROM party_types t WHERE t.party_id = c.party_id
                             AND t.party_type = 'supplier') THEN 'processor'
        END;
        UPDATE party_opening_balances b SET account_type = CASE
            WHEN b.direction = 'receivable' THEN 'customer'
            WHEN EXISTS (SELECT 1 FROM party_types t WHERE t.party_id = b.party_id
                         AND t.party_type = 'supplier')
             AND NOT EXISTS (SELECT 1 FROM party_types t WHERE t.party_id = b.party_id
                             AND t.party_type = 'processor') THEN 'supplier'
            WHEN EXISTS (SELECT 1 FROM party_types t WHERE t.party_id = b.party_id
                         AND t.party_type = 'processor')
             AND NOT EXISTS (SELECT 1 FROM party_types t WHERE t.party_id = b.party_id
                             AND t.party_type = 'supplier') THEN 'processor'
        END;
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM cash_records WHERE account_type IS NULL)
               OR EXISTS (SELECT 1 FROM party_opening_balances WHERE account_type IS NULL) THEN
                RAISE EXCEPTION 'Legacy payable records for multi-role parties need account classification';
            END IF;
        END $$;
        ALTER TABLE cash_records ALTER COLUMN account_type SET NOT NULL;
        ALTER TABLE party_opening_balances ALTER COLUMN account_type SET NOT NULL;
        ALTER TABLE cash_records ADD CONSTRAINT cash_account_type_check
            CHECK ((record_type = 'receipt' AND account_type = 'customer')
                OR (record_type = 'payment' AND account_type IN ('supplier','processor')));
        ALTER TABLE party_opening_balances ADD CONSTRAINT opening_account_type_check
            CHECK ((direction = 'receivable' AND account_type = 'customer')
                OR (direction = 'payable' AND account_type IN ('supplier','processor')));
        ALTER TABLE party_opening_balances
            DROP CONSTRAINT party_opening_balances_organization_id_party_id_direction_e_key;
        ALTER TABLE party_opening_balances
            ADD CONSTRAINT party_opening_account_date_unique
            UNIQUE (organization_id, party_id, account_type, effective_date);
    """)


def downgrade() -> None:
    raise NotImplementedError("Reconciliation account classification cannot be safely discarded")
