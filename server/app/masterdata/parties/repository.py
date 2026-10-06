from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


_SELECT = """
    SELECT p.id, p.organization_id, p.code, p.name, p.contact_name,
           p.contact_phone, p.is_active, p.created_at, p.updated_at,
           coalesce(array_agg(pt.party_type ORDER BY pt.party_type)
                    FILTER (WHERE pt.party_type IS NOT NULL), ARRAY[]::text[]) AS types
    FROM parties p LEFT JOIN party_types pt ON pt.party_id = p.id
"""
_GROUP = """
    GROUP BY p.id, p.organization_id, p.code, p.name,
             p.contact_name, p.contact_phone, p.is_active, p.created_at, p.updated_at
"""


def get_party(db: Session, organization_id: UUID, party_id: UUID) -> dict | None:
    row = db.execute(
        text(_SELECT + " WHERE p.organization_id = :org AND p.id = :id " + _GROUP),
        {"org": organization_id, "id": party_id},
    ).mappings().first()
    return dict(row) if row else None


def list_parties(db: Session, organization_id: UUID, party_type: str | None) -> list[dict]:
    type_filter = """
        AND EXISTS (
            SELECT 1 FROM party_types required
            WHERE required.party_id = p.id AND required.party_type = :party_type
        )
    """ if party_type else ""
    return [dict(row) for row in db.execute(
        text(_SELECT + " WHERE p.organization_id = :org " + type_filter + _GROUP
             + " ORDER BY p.created_at DESC, p.code"),
        {"org": organization_id, "party_type": party_type},
    ).mappings()]

