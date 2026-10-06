"""Run API tests in a disposable PostgreSQL database."""

import os
import subprocess
import sys
from uuid import uuid4

from sqlalchemy import create_engine, text

from app.core.db import get_engine


def main() -> int:
    test_targets = sys.argv[1:] or ["tests/test_production_plan_api.py"]
    base_url = get_engine().url
    database_name = f"psi_test_production_{uuid4().hex[:12]}"
    admin_engine = create_engine(base_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    try:
        environment = {**os.environ, "PSI_DATABASE_URL": base_url.set(database=database_name).render_as_string(hide_password=False)}
        for command in (
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            [sys.executable, "-m", "pytest", *test_targets, "-q"],
        ):
            result = subprocess.run(command, env=environment, check=False)
            if result.returncode:
                return result.returncode
        return 0
    finally:
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{database_name}" WITH (FORCE)'))
        admin_engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
