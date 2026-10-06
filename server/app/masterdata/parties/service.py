from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.masterdata.parties import repository
from app.masterdata.parties.schemas import PartyUpdate, PartyWrite

_ROLE_REFERENCES = {
    "customer": ("sales_orders", "customer_id"),
    "supplier": ("purchase_orders", "supplier_id"),
    "processor": ("outsourcing_orders", "processor_id"),
}


def create_party(db: Session, organization_id: UUID, actor_id: UUID, data: PartyWrite) -> dict:
    try:
        party_id = db.execute(
            text("""
                INSERT INTO parties (organization_id, code, name, contact_name, contact_phone)
                VALUES (:org, :code, :name, :contact_name, :contact_phone) RETURNING id
            """),
            {
                "org": organization_id, "code": data.code, "name": data.name.strip(),
                "contact_name": data.contact_name, "contact_phone": data.contact_phone,
            },
        ).scalar_one()
        for role in sorted(data.types):
            db.execute(
                text("INSERT INTO party_types (party_id, party_type) VALUES (:id, :role)"),
                {"id": party_id, "role": role},
            )
        db.execute(
            text("""
                INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
                VALUES (:org, :actor, 'party.create', 'party', :id)
            """),
            {"org": organization_id, "actor": actor_id, "id": party_id},
        )
        result = repository.get_party(db, organization_id, party_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="往来单位编码已存在") from exc


def update_party(db: Session, organization_id: UUID, actor_id: UUID, party_id: UUID, data: PartyUpdate) -> dict:
    locked = db.execute(
        text("SELECT id FROM parties WHERE id = :id AND organization_id = :org FOR UPDATE"),
        {"id": party_id, "org": organization_id},
    ).scalar_one_or_none()
    if locked is None:
        raise HTTPException(status_code=404, detail="往来单位不存在")
    current = repository.get_party(db, organization_id, party_id)
    assert current is not None
    removed = set(current["types"]) - data.types
    for role in removed:
        table, column = _ROLE_REFERENCES[role]
        # Table and column names come exclusively from the fixed map above.
        used = db.execute(
            text(f"SELECT 1 FROM {table} WHERE {column} = :id LIMIT 1"),
            {"id": party_id},
        ).scalar_one_or_none()
        if used:
            raise HTTPException(status_code=409, detail=f"party role {role} has business references")
    try:
        db.execute(
            text("""
                UPDATE parties SET code = :code, name = :name, contact_name = :contact_name,
                    contact_phone = :contact_phone, is_active = :is_active
                WHERE id = :id AND organization_id = :org
            """),
            {
                "id": party_id, "org": organization_id, "code": data.code,
                "name": data.name.strip(), "contact_name": data.contact_name,
                "contact_phone": data.contact_phone, "is_active": data.is_active,
            },
        )
        for role in removed:
            db.execute(
                text("DELETE FROM party_types WHERE party_id = :id AND party_type = :role"),
                {"id": party_id, "role": role},
            )
        for role in data.types - set(current["types"]):
            db.execute(
                text("INSERT INTO party_types (party_id, party_type) VALUES (:id, :role)"),
                {"id": party_id, "role": role},
            )
        db.execute(
            text("""
                INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
                VALUES (:org, :actor, 'party.update', 'party', :id)
            """),
            {"org": organization_id, "actor": actor_id, "id": party_id},
        )
        result = repository.get_party(db, organization_id, party_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="往来单位编码已存在") from exc


def delete_party(db: Session, organization_id: UUID, actor_id: UUID, party_id: UUID) -> None:
    if repository.get_party(db, organization_id, party_id) is None:
        raise HTTPException(status_code=404, detail="往来单位不存在")
    try:
        db.execute(text("DELETE FROM parties WHERE id = :id AND organization_id = :org"),
                   {"id": party_id, "org": organization_id})
        db.execute(
            text("""
                INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
                VALUES (:org, :actor, 'party.delete', 'party', :id)
            """),
            {"org": organization_id, "actor": actor_id, "id": party_id},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="往来单位已有业务引用，请改为停用") from exc

