"""Synchronous PostgreSQL sessions shared by API modules."""

from functools import lru_cache
import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from app.core.local_env import load_local_env


load_local_env()


@lru_cache
def get_engine() -> Engine:
    url = os.environ.get("PSI_DATABASE_URL")
    if not url:
        raise RuntimeError("PSI_DATABASE_URL is required")
    if make_url(url).get_backend_name() != "postgresql":
        raise RuntimeError("PSI_DATABASE_URL must point to PostgreSQL")
    return create_engine(url, pool_pre_ping=True)


def get_db() -> Iterator[Session]:
    with Session(get_engine()) as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
