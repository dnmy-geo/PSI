"""Local configuration keeps shell overrides and accepts simple .env entries."""

import os

from app.core.local_env import load_local_env


def test_local_env_reads_values_without_overriding_shell(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(
        "# local settings\nPSI_TEST_EXISTING=from-file\n"
        "PSI_TEST_QUOTED='value with spaces'\nPSI_TEST_URL=postgresql://host/db?x=a=b\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PSI_TEST_EXISTING", "from-shell")
    monkeypatch.delenv("PSI_TEST_QUOTED", raising=False)
    monkeypatch.delenv("PSI_TEST_URL", raising=False)

    load_local_env(path)

    assert os.environ["PSI_TEST_EXISTING"] == "from-shell"
    assert os.environ["PSI_TEST_QUOTED"] == "value with spaces"
    assert os.environ["PSI_TEST_URL"] == "postgresql://host/db?x=a=b"
