from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.masterdata.categories import repository
from app.masterdata.categories.schemas import CategoryWrite


def _lock_organization(db: Session, organization_id: UUID) -> None:
    db.execute(
        text("SELECT id FROM organizations WHERE id = :id FOR UPDATE"),
        {"id": organization_id},
    ).scalar_one()


def _validate_parent(db: Session, organization_id: UUID, category_id: UUID | None, parent_id: UUID | None) -> None:
    if parent_id is None:
        return
    if parent_id == category_id:
        raise HTTPException(status_code=422, detail="分类不能作为自己的上级")
    if repository.get_category(db, organization_id, parent_id) is None:
        raise HTTPException(status_code=422, detail="上级分类不存在")
    if category_id is not None:
        has_cycle = db.execute(
            text("""
                WITH RECURSIVE ancestors(id, parent_id) AS (
                    SELECT id, parent_id FROM item_categories WHERE id = :parent_id AND organization_id = :org
                    UNION
                    SELECT c.id, c.parent_id FROM item_categories c
                    JOIN ancestors a ON c.id = a.parent_id
                    WHERE c.organization_id = :org
                )
                SELECT 1 FROM ancestors WHERE id = :category_id LIMIT 1
            """),
            {"parent_id": parent_id, "category_id": category_id, "org": organization_id},
        ).scalar_one_or_none()
        if has_cycle:
            raise HTTPException(status_code=422, detail="物料分类层级不能成环")


def create_category(db: Session, organization_id: UUID, actor_id: UUID, data: CategoryWrite) -> dict:
    _lock_organization(db, organization_id)
    _validate_parent(db, organization_id, None, data.parent_id)
    try:
        row = db.execute(
            text("""
                INSERT INTO item_categories (organization_id, code, name, parent_id)
                VALUES (:org, :code, :name, :parent_id)
                RETURNING id, organization_id, code, name, parent_id, created_at, updated_at
            """),
            {"org": organization_id, "code": data.code, "name": data.name.strip(), "parent_id": data.parent_id},
        ).mappings().one()
        db.execute(
            text("""
                INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
                VALUES (:org, :actor, 'category.create', 'item_category', :id)
            """),
            {"org": organization_id, "actor": actor_id, "id": row["id"]},
        )
        db.commit()
        return dict(row)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="物料分类编码已存在") from exc


def update_category(
    db: Session, organization_id: UUID, actor_id: UUID, category_id: UUID, data: CategoryWrite
) -> dict:
    _lock_organization(db, organization_id)
    if repository.get_category(db, organization_id, category_id) is None:
        raise HTTPException(status_code=404, detail="物料分类不存在")
    _validate_parent(db, organization_id, category_id, data.parent_id)
    try:
        row = db.execute(
            text("""
                UPDATE item_categories SET code = :code, name = :name, parent_id = :parent_id
                WHERE id = :id AND organization_id = :org
                RETURNING id, organization_id, code, name, parent_id, created_at, updated_at
            """),
            {
                "id": category_id, "org": organization_id, "code": data.code,
                "name": data.name.strip(), "parent_id": data.parent_id,
            },
        ).mappings().one()
        db.execute(
            text("""
                INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
                VALUES (:org, :actor, 'category.update', 'item_category', :id)
            """),
            {"org": organization_id, "actor": actor_id, "id": category_id},
        )
        db.commit()
        return dict(row)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="物料分类编码已存在") from exc


def delete_category(db: Session, organization_id: UUID, actor_id: UUID, category_id: UUID) -> None:
    _lock_organization(db, organization_id)
    if repository.get_category(db, organization_id, category_id) is None:
        raise HTTPException(status_code=404, detail="物料分类不存在")
    try:
        db.execute(text("DELETE FROM item_categories WHERE id = :id AND organization_id = :org"),
                   {"id": category_id, "org": organization_id})
        db.execute(
            text("""
                INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
                VALUES (:org, :actor, 'category.delete', 'item_category', :id)
            """),
            {"org": organization_id, "actor": actor_id, "id": category_id},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="分类下还有子分类或物料") from exc

