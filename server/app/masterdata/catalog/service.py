from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.masterdata.catalog import repository
from app.masterdata.catalog.schemas import (
    ItemCreate, ItemUpdate, UnitCreate, UnitUpdate,
)


def _validate_base_unit(db: Session, organization_id: UUID, unit_id: UUID | None,
                        base_unit_id: UUID | None) -> None:
    """层级只允许两层：基本单位自身不能再挂基本单位，已经是别人基本单位的也不能再挂。"""
    if base_unit_id is None:
        return
    if base_unit_id == unit_id:
        raise HTTPException(status_code=422, detail="单位不能把自己作为基本单位")
    base = repository.get_unit(db, organization_id, base_unit_id)
    if base is None or not base["is_active"]:
        raise HTTPException(status_code=422, detail="基本单位不可用")
    if base["base_unit_id"] is not None:
        raise HTTPException(status_code=422,
                            detail="基本单位自身不能再有基本单位，层级最多两层")
    if unit_id is not None:
        dependents = db.execute(
            text("SELECT EXISTS (SELECT 1 FROM units WHERE base_unit_id = :id)"),
            {"id": unit_id},
        ).scalar_one()
        if dependents:
            raise HTTPException(
                status_code=409,
                detail="该单位已被其他单位作为基本单位，它自己不能再选择基本单位")


def create_unit(db: Session, organization_id: UUID, actor_id: UUID, data: UnitCreate) -> dict:
    _validate_base_unit(db, organization_id, None, data.base_unit_id)
    try:
        row = db.execute(
            text("""
                INSERT INTO units (organization_id, code, name, precision_scale,
                                   base_unit_id, base_quantity)
                VALUES (:organization_id, :code, :name, :precision_scale,
                        :base_unit_id, :base_quantity)
                RETURNING id, organization_id, code, name, precision_scale, is_active,
                          base_unit_id, base_quantity, created_at, updated_at
            """),
            {
                "organization_id": organization_id,
                "code": data.code,
                "name": data.name.strip(),
                "precision_scale": data.precision_scale,
                "base_unit_id": data.base_unit_id,
                "base_quantity": data.base_quantity,
            },
        ).mappings().one()
        db.execute(
            text("""
                INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
                VALUES (:organization_id, :actor_id, 'unit.create', 'unit', :id)
            """),
            {"organization_id": organization_id, "actor_id": actor_id, "id": row["id"]},
        )
        db.commit()
        return dict(row)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="计量单位编码已存在") from exc


def update_unit(db: Session, organization_id: UUID, actor_id: UUID, unit_id: UUID, data: UnitUpdate) -> dict:
    current = repository.lock_unit(db, organization_id, unit_id)
    if current is None:
        raise HTTPException(status_code=404, detail="计量单位不存在")
    if data.precision_scale < current["precision_scale"]:
        referenced = db.execute(
            text("""
                SELECT EXISTS (SELECT 1 FROM items WHERE base_unit_id = :id)
                    OR EXISTS (SELECT 1 FROM units WHERE base_unit_id = :id)
            """),
            {"id": unit_id},
        ).scalar_one()
        if referenced:
            raise HTTPException(status_code=409, detail="该单位已被使用，不能减小小数位数")
    _validate_base_unit(db, organization_id, unit_id, data.base_unit_id)
    if not data.is_active:
        active_base = db.execute(
            text("SELECT 1 FROM items WHERE base_unit_id = :id AND is_active LIMIT 1"),
            {"id": unit_id},
        ).scalar_one_or_none()
        if active_base:
            raise HTTPException(status_code=409, detail="该单位是某启用中物料的基本单位，不能停用")
    try:
        row = db.execute(
            text("""
                UPDATE units SET code = :code, name = :name,
                    precision_scale = :precision_scale, is_active = :is_active,
                    base_unit_id = :base_unit_id, base_quantity = :base_quantity
                WHERE id = :id AND organization_id = :organization_id
                RETURNING id, organization_id, code, name, precision_scale, is_active,
                          base_unit_id, base_quantity, created_at, updated_at
            """),
            {
                "id": unit_id, "organization_id": organization_id, "code": data.code,
                "name": data.name.strip(), "precision_scale": data.precision_scale,
                "is_active": data.is_active,
                "base_unit_id": data.base_unit_id, "base_quantity": data.base_quantity,
            },
        ).mappings().one()
        db.execute(
            text("""
                INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
                VALUES (:org, :actor, 'unit.update', 'unit', :id)
            """),
            {"org": organization_id, "actor": actor_id, "id": unit_id},
        )
        db.commit()
        return dict(row)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="计量单位编码已存在") from exc


def delete_unit(db: Session, organization_id: UUID, actor_id: UUID, unit_id: UUID) -> None:
    if repository.lock_unit(db, organization_id, unit_id) is None:
        raise HTTPException(status_code=404, detail="计量单位不存在")
    try:
        db.execute(text("DELETE FROM units WHERE id = :id AND organization_id = :org"),
                   {"id": unit_id, "org": organization_id})
        db.execute(
            text("""
                INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
                VALUES (:org, :actor, 'unit.delete', 'unit', :id)
            """),
            {"org": organization_id, "actor": actor_id, "id": unit_id},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="计量单位已有业务引用，请改为停用") from exc


def create_item(db: Session, organization_id: UUID, actor_id: UUID, data: ItemCreate) -> dict:
    unit = repository.get_unit(db, organization_id, data.base_unit_id)
    if unit is None or not unit["is_active"]:
        raise HTTPException(status_code=422, detail="基本单位不可用")
    if data.category_id:
        category_exists = db.execute(
            text("SELECT 1 FROM item_categories WHERE id = :id AND organization_id = :org"),
            {"id": data.category_id, "org": organization_id},
        ).scalar_one_or_none()
        if not category_exists:
            raise HTTPException(status_code=422, detail="物料分类不可用")
    try:
        row = db.execute(
            text("""
                INSERT INTO items (organization_id, code, name, item_type, base_unit_id, category_id)
                VALUES (:organization_id, :code, :name, :item_type, :base_unit_id, :category_id)
                RETURNING id, organization_id, code, name, item_type, base_unit_id, category_id,
                          is_active, created_at, updated_at
            """),
            {
                "organization_id": organization_id,
                "code": data.code,
                "name": data.name.strip(),
                "item_type": data.item_type,
                "base_unit_id": data.base_unit_id,
                "category_id": data.category_id,
            },
        ).mappings().one()
        db.execute(
            text("""
                INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
                VALUES (:organization_id, :actor_id, 'item.create', 'item', :id)
            """),
            {"organization_id": organization_id, "actor_id": actor_id, "id": row["id"]},
        )
        db.commit()
        return dict(row)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="物料编码已存在") from exc


def update_item(db: Session, organization_id: UUID, actor_id: UUID, item_id: UUID, data: ItemUpdate) -> dict:
    current = repository.lock_item(db, organization_id, item_id)
    if current is None:
        raise HTTPException(status_code=404, detail="物料不存在")
    if data.category_id is not None:
        found = db.execute(
            text("SELECT 1 FROM item_categories WHERE id = :id AND organization_id = :org"),
            {"id": data.category_id, "org": organization_id},
        ).scalar_one_or_none()
        if not found:
            raise HTTPException(status_code=422, detail="物料分类不可用")
    if current["is_active"] and not data.is_active:
        has_stock = db.execute(
            text("""
                SELECT 1 FROM stock_balances WHERE organization_id = :org
                  AND item_id = :id AND quantity_base > 0 LIMIT 1
            """),
            {"org": organization_id, "id": item_id},
        ).scalar_one_or_none()
        if has_stock:
            raise HTTPException(status_code=409, detail="物料还有结存")
    try:
        row = db.execute(
            text("""
                UPDATE items SET code = :code, name = :name,
                    category_id = :category_id, is_active = :is_active
                WHERE id = :id AND organization_id = :org
                RETURNING id, organization_id, code, name, item_type, base_unit_id, category_id,
                          is_active, created_at, updated_at
            """),
            {
                "id": item_id, "org": organization_id, "code": data.code,
                "name": data.name.strip(), "category_id": data.category_id,
                "is_active": data.is_active,
            },
        ).mappings().one()
        db.execute(
            text("""
                INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
                VALUES (:org, :actor, 'item.update', 'item', :id)
            """),
            {"org": organization_id, "actor": actor_id, "id": item_id},
        )
        db.commit()
        return dict(row)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="物料编码已存在") from exc


def delete_item(db: Session, organization_id: UUID, actor_id: UUID, item_id: UUID) -> None:
    if repository.lock_item(db, organization_id, item_id) is None:
        raise HTTPException(status_code=404, detail="物料不存在")
    try:
        db.execute(text("DELETE FROM items WHERE id = :id AND organization_id = :org"),
                   {"id": item_id, "org": organization_id})
        db.execute(
            text("""
                INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
                VALUES (:org, :actor, 'item.delete', 'item', :id)
            """),
            {"org": organization_id, "actor": actor_id, "id": item_id},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="物料已有业务引用，请改为停用") from exc

