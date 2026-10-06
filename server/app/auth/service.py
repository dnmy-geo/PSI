from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.schemas import LoginRequest
from app.core.security import (
    csrf_token_for,
    hash_token,
    new_session_token,
    password_hash,
    session_expiry,
)


def login(db: Session, request: LoginRequest) -> tuple[dict[str, str], str]:
    organization_filter = "AND o.code = :organization_code" if request.organization_code else ""
    rows = db.execute(
        text(f"""
            SELECT u.id, u.organization_id, u.username, u.display_name, u.password_hash
            FROM users u JOIN organizations o ON o.id = u.organization_id
            WHERE u.username = :username
              AND o.is_active AND u.is_active
              {organization_filter}
            LIMIT 2
        """),
        {"username": request.username, **({"organization_code": request.organization_code} if request.organization_code else {})},
    ).mappings().all()
    # The UI uses username only. Refuse ambiguous names instead of picking an
    # arbitrary organization; legacy clients may still provide its code.
    row = rows[0] if len(rows) == 1 else None
    valid = False
    if row is not None:
        try:
            valid = password_hash.verify(request.password, row["password_hash"])
        except (ValueError, TypeError):
            valid = False
    if not valid:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = new_session_token()
    db.execute(
        text("""
            INSERT INTO auth_sessions (user_id, token_hash, expires_at)
            VALUES (:user_id, :token_hash, :expires_at)
        """),
        {"user_id": row["id"], "token_hash": hash_token(token), "expires_at": session_expiry()},
    )
    db.commit()
    return {
        "user_id": str(row["id"]),
        "organization_id": str(row["organization_id"]),
        "username": row["username"],
        "display_name": row["display_name"],
        "csrf_token": csrf_token_for(token),
    }, token
