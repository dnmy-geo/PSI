from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.schemas import LoginRequest, UserSession
from app.auth.service import login
from app.core.db import get_db
from app.core.security import (
    COOKIE_NAME,
    SESSION_LIFETIME,
    CurrentUser,
    cookie_secure,
    csrf_token_for,
    get_current_user,
    hash_token,
    require_csrf,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserSession)
def login_route(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> dict:
    result, token = login(db, payload)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        secure=cookie_secure(),
        samesite="strict",
        path="/",
    )
    return result


@router.get("/me", response_model=UserSession)
def me(user: CurrentUser = Depends(get_current_user)) -> dict[str, str]:
    return {
        "user_id": str(user.id),
        "organization_id": str(user.organization_id),
        "username": user.username,
        "display_name": user.display_name,
        "csrf_token": csrf_token_for(user.session_token),
    }


@router.post("/logout", status_code=204, dependencies=[Depends(require_csrf)])
def logout(
    response: Response,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    db.execute(
        text("UPDATE auth_sessions SET revoked_at = now() WHERE token_hash = :token_hash"),
        {"token_hash": hash_token(user.session_token)},
    )
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")

