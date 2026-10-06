"""One-time setup of the first organization, administrator and default warehouses."""

from __future__ import annotations

import os

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.security import password_hash
from app.system.menu_seed import seed_menus


def bootstrap(db: Session, *, org_code: str, org_name: str, admin_username: str, admin_password: str) -> None:
    if len(admin_password) < 6:
        raise ValueError("Administrator password must contain at least 6 characters")
    if not org_code.strip() or not org_name.strip() or not admin_username.strip():
        raise ValueError("Organization and administrator fields must not be empty")
    if db.execute(text("SELECT EXISTS (SELECT 1 FROM organizations)")).scalar_one():
        raise RuntimeError("Organization already exists; bootstrap is a one-time operation")

    organization_id = db.execute(
        text("INSERT INTO organizations (code, name) VALUES (:code, :name) RETURNING id"),
        {"code": org_code.strip(), "name": org_name.strip()},
    ).scalar_one()
    role_id = db.execute(
        text("""
            INSERT INTO roles (organization_id, code, name)
            VALUES (:organization_id, 'system_admin', '系统管理员') RETURNING id
        """),
        {"organization_id": organization_id},
    ).scalar_one()
    user_id = db.execute(
        text("""
            INSERT INTO users (organization_id, username, display_name, password_hash)
            VALUES (:organization_id, :username, :display_name, :password_hash) RETURNING id
        """),
        {
            "organization_id": organization_id,
            "username": admin_username.strip(),
            "display_name": "系统管理员",
            "password_hash": password_hash.hash(admin_password),
        },
    ).scalar_one()
    db.execute(
        text("INSERT INTO user_roles (user_id, role_id) VALUES (:user_id, :role_id)"),
        {"user_id": user_id, "role_id": role_id},
    )
    seed_menus(db)
    for document_type in ("sales_order", "stocktake"):
        config_id = db.execute(text("""
            INSERT INTO approval_configs (organization_id, document_type)
            VALUES (:organization_id, :document_type) RETURNING id
        """), {"organization_id": organization_id,
               "document_type": document_type}).scalar_one()
        db.execute(text("""
            INSERT INTO approval_config_steps (config_id, step_no, approver_role_id)
            VALUES (:config_id, 1, :role_id)
        """), {"config_id": config_id, "role_id": role_id})
    for code, name in (
        ("RAW", "原材料仓"),
        ("FINISHED", "成品仓"),
        ("SITE", "现场仓"),
    ):
        db.execute(
            text("INSERT INTO warehouses (organization_id, code, name) VALUES (:organization_id, :code, :name)"),
            {"organization_id": organization_id, "code": code, "name": name},
        )
    db.commit()


def main() -> None:
    required = ("PSI_ORG_CODE", "PSI_ORG_NAME", "PSI_ADMIN_USERNAME", "PSI_ADMIN_PASSWORD")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Missing environment variables: " + ", ".join(missing))
    with Session(get_engine()) as db:
        try:
            bootstrap(
                db,
                org_code=os.environ["PSI_ORG_CODE"],
                org_name=os.environ["PSI_ORG_NAME"],
                admin_username=os.environ["PSI_ADMIN_USERNAME"],
                admin_password=os.environ["PSI_ADMIN_PASSWORD"],
            )
        except Exception:
            db.rollback()
            raise
    print("Initial organization, administrator and three warehouses created.")


if __name__ == "__main__":
    main()
