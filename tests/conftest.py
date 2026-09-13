"""Keep the suite hermetic against a local operator's live-run environment."""

from __future__ import annotations

import os

import pytest

_OPERATOR_ENV_VARS = (
    "AGENTIC_PORTFOLIO_LAB_DB_PATH",
    "TWELVE_DATA_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
    "ALPACA_API_KEY_ID",
    "ALPACA_API_SECRET_KEY",
    "OPENAI_API_KEY",
    "OPENAI_VALUE_MANAGER_MODEL",
    "OPENAI_VALUE_MANAGER_REASONING_EFFORT",
)


def _clear_operator_environment() -> None:
    for name in _OPERATOR_ENV_VARS:
        os.environ.pop(name, None)


# pytest imports this conftest before collecting test modules. Those modules
# import agentic_portfolio_lab.api.app, which constructs the module-level FastAPI
# app at import time. Strip live operator config here so collection cannot open
# the operator database or inherit live provider/OpenAI settings.
_clear_operator_environment()


def pytest_configure(config: pytest.Config) -> None:
    _clear_operator_environment()


@pytest.fixture(autouse=True)
def isolate_operator_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-clear around each test so leaked os.environ writes cannot persist."""
    for name in _OPERATOR_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
