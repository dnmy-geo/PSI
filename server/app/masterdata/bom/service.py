from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.masterdata.bom import repository
from app.masterdata.bom.schemas import BomLineWrite, BomWrite


def _lock_organization(db: Session, organization_id: UUID) -> None:
    db.execute(text("SELECT id FROM organizations WHERE id = :id FOR UPDATE"),
               {"id": organization_id}).scalar_one()


def _validate_items(
    db: Session, organization_id: UUID, parent_item_id: UUID, lines: list[BomLineWrite]
) -> None:
    parent = db.execute(
        text("""
            SELECT item_type, is_active FROM items WHERE id = :id AND organization_id = :org
        """),
        {"id": parent_item_id, "org": organization_id},
    ).mappings().first()
    if parent is None or not parent["is_active"] or parent["item_type"] == "raw_material":
        raise HTTPException(status_code=422, detail="用料清单的产出物料必须是启用中的半成品或成品")
    child_ids = [line.child_item_id for line in lines]
    if len(set(child_ids)) != len(child_ids):
        raise HTTPException(status_code=422, detail="用料清单的子物料重复")
    if parent_item_id in child_ids:
        raise HTTPException(status_code=422, detail="用料清单不能直接引用自身")
    for child_id in child_ids:
        active = db.execute(
            text("SELECT is_active FROM items WHERE id = :id AND organization_id = :org"),
            {"id": child_id, "org": organization_id},
        ).scalar_one_or_none()
        if not active:
            raise HTTPException(status_code=422, detail="用料清单的子物料不可用")


def _write_lines(db: Session, bom_id: UUID, lines: list[BomLineWrite]) -> None:
    for line in lines:
        db.execute(
            text("""
                INSERT INTO bom_lines (bom_id, child_item_id, quantity_base, sort_order)
                VALUES (:bom_id, :child_item_id, :quantity_base, :sort_order)
            """),
            {
                "bom_id": bom_id, "child_item_id": line.child_item_id,
                "quantity_base": line.quantity_base, "sort_order": line.sort_order,
            },
        )


def create_bom(db: Session, organization_id: UUID, actor_id: UUID, data: BomWrite) -> dict:
    _lock_organization(db, organization_id)
    _validate_items(db, organization_id, data.parent_item_id, data.lines)
    try:
        bom_id = db.execute(
            text("""
                INSERT INTO bom_headers (organization_id, parent_item_id, version, is_active)
                VALUES (:org, :parent_id, :version, false) RETURNING id
            """),
            {"org": organization_id, "parent_id": data.parent_item_id, "version": data.version},
        ).scalar_one()
        _write_lines(db, bom_id, data.lines)
        db.execute(
            text("""
                INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
                VALUES (:org, :actor, 'bom.create', 'bom', :id)
            """),
            {"org": organization_id, "actor": actor_id, "id": bom_id},
        )
        result = repository.get_bom(db, organization_id, bom_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="该版本号的用料清单已存在") from exc


def update_bom(db: Session, organization_id: UUID, actor_id: UUID, bom_id: UUID, data: BomWrite) -> dict:
    _lock_organization(db, organization_id)
    current = repository.get_bom(db, organization_id, bom_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="用料清单不存在")
    if current["is_active"]:
        raise HTTPException(status_code=409, detail="启用中的用料清单不能修改，请新建版本")
    _validate_items(db, organization_id, data.parent_item_id, data.lines)
    try:
        db.execute(
            text("""
                UPDATE bom_headers SET parent_item_id = :parent_id, version = :version
                WHERE id = :id AND organization_id = :org
            """),
            {
                "id": bom_id, "org": organization_id,
                "parent_id": data.parent_item_id, "version": data.version,
            },
        )
        db.execute(text("DELETE FROM bom_lines WHERE bom_id = :id"), {"id": bom_id})
        _write_lines(db, bom_id, data.lines)
        db.execute(
            text("""
                INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
                VALUES (:org, :actor, 'bom.update', 'bom', :id)
            """),
            {"org": organization_id, "actor": actor_id, "id": bom_id},
        )
        result = repository.get_bom(db, organization_id, bom_id)
        db.commit()
        assert result is not None
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="该版本号的用料清单已存在") from exc


def _check_cycle(db: Session, organization_id: UUID, parent_item_id: UUID, child_item_id: UUID) -> None:
    cycle = db.execute(
        text("""
            WITH RECURSIVE descendants(item_id) AS (
                SELECT CAST(:child_item_id AS uuid)
                UNION
                SELECT lines.child_item_id
                FROM descendants d
                JOIN bom_headers headers ON headers.parent_item_id = d.item_id
                  AND headers.organization_id = :org AND headers.is_active
                  AND headers.parent_item_id <> :parent_item_id
                JOIN bom_lines lines ON lines.bom_id = headers.id
            )
            SELECT 1 FROM descendants WHERE item_id = :parent_item_id LIMIT 1
        """),
        {
            "child_item_id": child_item_id,
            "parent_item_id": parent_item_id,
            "org": organization_id,
        },
    ).scalar_one_or_none()
    if cycle:
        raise HTTPException(status_code=422, detail="用料清单的层级不能成环")


def activate_bom(db: Session, organization_id: UUID, actor_id: UUID, bom_id: UUID) -> dict:
    try:
        _lock_organization(db, organization_id)
        current = repository.get_bom(db, organization_id, bom_id, lock=True)
        if current is None:
            raise HTTPException(status_code=404, detail="用料清单不存在")
        if current["is_active"]:
            return current
        lines = [BomLineWrite.model_validate(line) for line in current["lines"]]
        _validate_items(db, organization_id, current["parent_item_id"], lines)
        for line in lines:
            _check_cycle(db, organization_id, current["parent_item_id"], line.child_item_id)
        db.execute(
            text("""
                UPDATE bom_headers SET is_active = false
                WHERE organization_id = :org AND parent_item_id = :parent_id AND is_active
            """),
            {"org": organization_id, "parent_id": current["parent_item_id"]},
        )
        db.execute(text("UPDATE bom_headers SET is_active = true WHERE id = :id"), {"id": bom_id})
        db.execute(
            text("""
                INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
                VALUES (:org, :actor, 'bom.activate', 'bom', :id)
            """),
            {"org": organization_id, "actor": actor_id, "id": bom_id},
        )
        db.commit()
        current["is_active"] = True
        return current
    except Exception:
        db.rollback()
        raise


def delete_bom(db: Session, organization_id: UUID, actor_id: UUID, bom_id: UUID) -> None:
    _lock_organization(db, organization_id)
    current = repository.get_bom(db, organization_id, bom_id, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="用料清单不存在")
    if current["is_active"]:
        raise HTTPException(status_code=409, detail="启用中的用料清单不能删除")
    db.execute(text("DELETE FROM bom_headers WHERE id = :id AND organization_id = :org"),
               {"id": bom_id, "org": organization_id})
    db.execute(
        text("""
            INSERT INTO audit_logs (organization_id, actor_id, action_code, document_type, document_id)
            VALUES (:org, :actor, 'bom.delete', 'bom', :id)
        """),
        {"org": organization_id, "actor": actor_id, "id": bom_id},
    )
    db.commit()
