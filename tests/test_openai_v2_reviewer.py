from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from agentic_portfolio_lab.application.active_policy import load_active_value_policy
from agentic_portfolio_lab.application.v2_advisory import V2ManagerRiskService
from agentic_portfolio_lab.domain import V2PriceSnapshot, build_batch_trade_plan, evaluate_batch_plan_safety
from agentic_portfolio_lab.domain.openai_v2_reviewer import OpenAIV2Reviewer
from agentic_portfolio_lab.domain.v2_advisory import V2AdvisoryStatus, V2ReviewerResult
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore
from tests.test_v2_weekly_cycle import NOW, artifacts, quote


class _Responses:
    def __init__(self, response: object | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class _Client:
    def __init__(self, response: object | Exception) -> None:
        self.responses = _Responses(response)


def _inputs(tmp_path):
    store = SQLiteLocalRunStore(tmp_path / "state.sqlite")
    portfolio = store.initialize_run(initialized_at=NOW).managed_portfolio
    screening, research, target = artifacts(portfolio)
    snapshot = V2PriceSnapshot((quote("AAPL", "10"),))
    plan = build_batch_trade_plan(target, portfolio, snapshot, created_at=NOW)
    safety = evaluate_batch_plan_safety(plan, evaluated_at=NOW)
    risk = V2ManagerRiskService(load_active_value_policy().manager_risk_constitution).assess(
        portfolio=portfolio, target=target, plan=plan, research=research, assessed_at=NOW,
    )
    return portfolio, target, plan, safety, risk, research


def _completed(payload: object) -> object:
    return SimpleNamespace(status="completed", output_text=json.dumps(payload))


def test_openai_v2_reviewer_returns_typed_exact_provenanced_result_and_complete_lineage(tmp_path) -> None:
    inputs = _inputs(tmp_path)
    client = _Client(_completed({"status": "ATTENTION", "findings": ["Review concentration."], "rationale": "Evidence supports an advisory note."}))
    reviewer = OpenAIV2Reviewer(client=client, model="review-model", reasoning_effort="high", clock=lambda: NOW)

    result = reviewer.review(portfolio=inputs[0], target=inputs[1], plan=inputs[2], system_safety=inputs[3], manager_risk=inputs[4], research=inputs[5])

    assert isinstance(result, V2ReviewerResult)
    assert result.status is V2AdvisoryStatus.ATTENTION
    assert result.target is inputs[1] and result.plan is inputs[2]
    assert result.target_identity == inputs[2].target_identity
    assert result.plan_identity == inputs[2].identity
    assert (result.provider_identity, result.model, result.reviewer_identity, result.reviewer_version) == ("openai", "review-model", "openai-v2-reviewer", "v1")
    call = client.responses.calls[0]
    assert call["model"] == "review-model"
    assert call["reasoning"] == {"effort": "high"}
    payload = json.loads(call["input"][1]["content"][0]["text"])
    assert payload["system_safety"]["passed"] is True
    assert payload["system_safety"]["plan"]["plan_id"] == str(inputs[2].plan_id)
    assert payload["manager_risk"]["target"]["portfolio_id"] == str(inputs[1].portfolio_id)
    assert payload["manager_risk"]["plan"]["plan_id"] == str(inputs[2].plan_id)
    assert payload["research"]["batch_id"] == inputs[5].batch_id
    assert payload["research"]["subjects"][0]["evidence"]


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (_completed("not json"), "malformed structured output"),
        (_completed({"status": "RECORDED", "findings": "not-a-list", "rationale": "fine"}), "malformed structured output"),
        (_completed({"status": "APPROVE", "findings": [], "rationale": "fine"}), "malformed structured output"),
        (SimpleNamespace(status="in_progress", output_text="{}"), "response was not completed"),
    ],
)
def test_openai_v2_reviewer_fails_closed_for_invalid_or_incomplete_provider_output(tmp_path, response, error) -> None:
    inputs = _inputs(tmp_path)
    reviewer = OpenAIV2Reviewer(client=_Client(response), clock=lambda: NOW)
    with pytest.raises(ValueError if "malformed" in error else RuntimeError, match=error):
        reviewer.review(portfolio=inputs[0], target=inputs[1], plan=inputs[2], system_safety=inputs[3], manager_risk=inputs[4], research=inputs[5])


def test_openai_v2_reviewer_fails_explicitly_for_provider_exception(tmp_path) -> None:
    inputs = _inputs(tmp_path)
    reviewer = OpenAIV2Reviewer(client=_Client(ConnectionError("offline")), clock=lambda: NOW)
    with pytest.raises(RuntimeError, match="provider call failed"):
        reviewer.review(portfolio=inputs[0], target=inputs[1], plan=inputs[2], system_safety=inputs[3], manager_risk=inputs[4], research=inputs[5], reviewed_at=NOW + timedelta(minutes=1))
