"""Track unfinished external business imported at system activation.

Revision ID: 0005_carryover_documents
Revises: 0004_production_documents_menus
"""

from alembic import op

revision = "0005_carryover_documents"
down_revision = "0004_production_documents_menus"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE carryover_documents (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id),
            business_kind text NOT NULL CHECK (business_kind IN
                ('sales','purchase','production','outsourcing')),
            original_document_no text NOT NULL,
            document_no text NOT NULL,
            effective_date date NOT NULL,
            party_id uuid REFERENCES parties(id),
            document_id uuid NOT NULL,
            related_plan_id uuid REFERENCES production_plans(id),
            imported_by uuid REFERENCES users(id),
            imported_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (organization_id, business_kind, original_document_no),
            UNIQUE (organization_id, business_kind, document_no)
        )
    """)
    op.execute("""
        CREATE TABLE carryover_lines (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            carryover_document_id uuid NOT NULL REFERENCES carryover_documents(id) ON DELETE CASCADE,
            source_row_no integer NOT NULL,
            line_kind text NOT NULL CHECK (line_kind IN ('output','material')),
            item_id uuid NOT NULL REFERENCES items(id),
            unit_id uuid NOT NULL REFERENCES units(id),
            original_quantity_base numeric(20,6) NOT NULL CHECK (original_quantity_base > 0),
            completed_quantity_base numeric(20,6) NOT NULL CHECK (completed_quantity_base >= 0),
            remaining_quantity_base numeric(20,6) NOT NULL CHECK (remaining_quantity_base >= 0),
            unit_price numeric(18,6),
            supply_party text CHECK (supply_party IN ('self','processor')),
            CHECK (original_quantity_base = completed_quantity_base + remaining_quantity_base),
            UNIQUE (carryover_document_id, source_row_no)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE carryover_lines")
    op.execute("DROP TABLE carryover_documents")
