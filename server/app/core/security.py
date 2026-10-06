"""Password hashes, opaque sessions and CSRF tokens."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import secrets
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from pwdlib import PasswordHash
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db

COOKIE_NAME = "psi_session"
SESSION_LIFETIME = timedelta(hours=12)
password_hash = PasswordHash.recommended()


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    organization_id: UUID
    username: str
    display_name: str
    session_token: str


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_token_for(session_token: str) -> str:
    return hmac.new(session_token.encode("utf-8"), b"psi-csrf-v1", hashlib.sha256).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def session_expiry() -> datetime:
    return datetime.now(timezone.utc) + SESSION_LIFETIME


def cookie_secure() -> bool:
    return os.environ.get("PSI_COOKIE_SECURE", "true").lower() != "false"


def get_current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    row = db.execute(
        text("""
            SELECT u.id, u.organization_id, u.username, u.display_name
            FROM auth_sessions s
            JOIN users u ON u.id = s.user_id
            JOIN organizations o ON o.id = u.organization_id
            WHERE s.token_hash = :token_hash
              AND s.revoked_at IS NULL AND s.expires_at > now()
              AND u.is_active AND o.is_active
        """),
        {"token_hash": hash_token(token)},
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=401, detail="请先登录")
    return CurrentUser(**row, session_token=token)


def require_csrf(request: Request, user: CurrentUser = Depends(get_current_user)) -> None:
    provided = request.headers.get("X-CSRF-Token", "")
    if not hmac.compare_digest(provided, csrf_token_for(user.session_token)):
        raise HTTPException(status_code=403, detail="安全令牌已失效，请刷新页面后重试")


def require_admin(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CurrentUser:
    allowed = db.execute(
        text("""
            SELECT 1 FROM user_roles ur
            JOIN roles r ON r.id = ur.role_id
            WHERE ur.user_id = :user_id AND r.organization_id = :organization_id
              AND r.code = 'system_admin' AND r.is_active
            LIMIT 1
        """),
        {"user_id": user.id, "organization_id": user.organization_id},
    ).scalar_one_or_none()
    if not allowed:
        raise HTTPException(status_code=403, detail="没有权限")
    return user


def has_permission(db: Session, user: CurrentUser, menu_code: str,
                   action_code: str) -> bool:
    allowed = db.execute(text("""
            SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id
            WHERE ur.user_id = :user_id AND r.organization_id = :org
              AND r.code = 'system_admin' AND r.is_active LIMIT 1
        """), {"user_id": user.id, "org": user.organization_id}).scalar_one_or_none()
    if allowed:
        return True
    allowed = db.execute(text("""
            SELECT 1 FROM user_roles ur
            JOIN roles r ON r.id = ur.role_id
            JOIN role_permissions rp ON rp.role_id = r.id
            JOIN menus m ON m.id = rp.menu_id
            WHERE ur.user_id = :user_id AND r.organization_id = :org
              AND r.is_active AND m.is_active
              AND m.code = :menu_code AND rp.action_code = :action_code
            LIMIT 1
        """), {"user_id": user.id, "org": user.organization_id,
               "menu_code": menu_code, "action_code": action_code}).scalar_one_or_none()
    return bool(allowed)


def require_permission(menu_code: str, action_code: str):
    def check(user: CurrentUser = Depends(get_current_user),
              db: Session = Depends(get_db)) -> CurrentUser:
        if not has_permission(db, user, menu_code, action_code):
            raise HTTPException(status_code=403, detail="没有权限")
        return user
    return check
