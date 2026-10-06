"""Load simple KEY=VALUE settings from the server's local .env file."""

from __future__ import annotations

import os
from pathlib import Path


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def load_local_env(path: Path = ENV_FILE) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#") or "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        key = key.strip()
        if not key or not key.isidentifier():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(key, value)
