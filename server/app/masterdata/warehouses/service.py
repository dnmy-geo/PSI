from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.masterdata.warehouses import repository
from app.masterdata.warehouses.schemas import WarehouseCreate, WarehouseUpdate


def create_warehouse(db: Session, organization_id: UUID, actor_id: UUID, data: WarehouseCreate) -> dict:
    try:
        row = db.execute(
            text("""
                INSERT INTO warehouses (organization_id, code, name)
                VALUES (:organization_id, :code, :name)
                RETURNING id, organization_id, code, name, is_active, created_at, updated_at
            """),
            {"organization_id": organization_id, "code": data.code, "name": data.name.strip()},
        ).mappings().one()
        db.execute(
            text("""
                INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
                VALUES (:organization_id, :actor_id, 'warehouse.create', 'warehouse', :document_id)
            """),
            {"organization_id": organization_id, "actor_id": actor_id, "document_id": row["id"]},
        )
        db.commit()
        return dict(row)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="仓库编码已存在") from exc


def update_warehouse(
    db: Session, organization_id: UUID, actor_id: UUID, warehouse_id: UUID, data: WarehouseUpdate
) -> dict:
    current = repository.lock_warehouse(db, organization_id, warehouse_id)
    if current is None:
        raise HTTPException(status_code=404, detail="仓库不存在")
    if current["is_active"] and not data.is_active and repository.has_stock(db, organization_id, warehouse_id):
        raise HTTPException(status_code=409, detail="仓库还有结存")
    try:
        row = db.execute(
            text("""
                UPDATE warehouses SET code = :code, name = :name, is_active = :is_active
                WHERE id = :id AND organization_id = :organization_id
                RETURNING id, organization_id, code, name, is_active, created_at, updated_at
            """),
            {
                "id": warehouse_id,
                "organization_id": organization_id,
                "code": data.code,
                "name": data.name.strip(),
                "is_active": data.is_active,
            },
        ).mappings().one()
        db.execute(
            text("""
                INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
                VALUES (:organization_id, :actor_id, 'warehouse.update', 'warehouse', :document_id)
            """),
            {"organization_id": organization_id, "actor_id": actor_id, "document_id": warehouse_id},
        )
        db.commit()
        return dict(row)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="仓库编码已存在") from exc


def delete_warehouse(db: Session, organization_id: UUID, actor_id: UUID, warehouse_id: UUID) -> None:
    if repository.get_warehouse(db, organization_id, warehouse_id) is None:
        raise HTTPException(status_code=404, detail="仓库不存在")
    try:
        db.execute(
            text("DELETE FROM warehouses WHERE id = :id AND organization_id = :organization_id"),
            {"id": warehouse_id, "organization_id": organization_id},
        )
        db.execute(
            text("""
                INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
                VALUES (:organization_id, :actor_id, 'warehouse.delete', 'warehouse', :document_id)
            """),
            {"organization_id": organization_id, "actor_id": actor_id, "document_id": warehouse_id},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="仓库已有业务引用，请改为停用") from exc
