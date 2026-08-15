"""Collection-time isolation from a developer's live operator environment."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentic_portfolio_lab.api.app import create_app
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_pytest_collection_ignores_hostile_operator_environment(tmp_path: Path) -> None:
    sentinel = tmp_path / "operator-sentinel.sqlite3"
    environment = {
        **os.environ,
        "PYTHONPATH": str(_REPOSITORY_ROOT / "src"),
        "AGENTIC_PORTFOLIO_LAB_DB_PATH": str(sentinel),
        "TWELVE_DATA_API_KEY": "sentinel-twelve-data-key",
        "ALPHA_VANTAGE_API_KEY": "sentinel-alpha-vantage-key",
        "OPENAI_API_KEY": "sentinel-openai-key",
        "OPENAI_VALUE_MANAGER_MODEL": "",
        "OPENAI_VALUE_MANAGER_REASONING_EFFORT": "not-a-valid-effort",
    }

    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/test_api.py"],
        cwd=_REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    health = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q",
            "tests/test_api.py::test_health_endpoint_describes_the_explicit_demo_state",
        ],
        cwd=_REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert collected.returncode == 0, collected.stdout + collected.stderr
    assert health.returncode == 0, health.stdout + health.stderr
    assert not sentinel.exists()
    assert not any(tmp_path.rglob("*.sqlite3"))
    assert not any(tmp_path.rglob("*.sqlite"))


def test_create_app_still_honors_explicitly_configured_database_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database_path = tmp_path / "controlled-run.sqlite3"
    SQLiteLocalRunStore(database_path).initialize_run(
        initialized_at=datetime(2026, 8, 14, 21, tzinfo=timezone.utc),
    )
    monkeypatch.setenv("AGENTIC_PORTFOLIO_LAB_DB_PATH", str(database_path))

    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "state_mode": "local-sqlite",
        "persisted": True,
        "synthetic": False,
    }
    assert database_path.exists()
