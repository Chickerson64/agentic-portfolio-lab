"""Lane 6 durable AI Reviewer integration, using fake adapters only."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from agentic_portfolio_lab.api.app import create_app
from agentic_portfolio_lab.application.decision_commands import (
    DecisionApprovalService,
    DecisionCommandConflict,
    ReviewDecisionService,
    RunValueManagerService,
)
from agentic_portfolio_lab.domain.approval import ApprovalDecision
from agentic_portfolio_lab.domain.reviewer import (
    AIReviewerReviewContext,
    ReviewFinding,
    ReviewerMetadata,
    ReviewerResult,
)
from agentic_portfolio_lab.domain.openai_reviewer import OpenAIReviewer
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore

from .test_decision_commands import START, _Manager, _prepared_store


class _Reviewer:
    def __init__(self, *, decision: str = "REQUEST_CHANGES") -> None:
        self.contexts: list[AIReviewerReviewContext] = []
        self.decision = decision

    def review(self, context: AIReviewerReviewContext) -> ReviewerResult:
        self.contexts.append(context)
        return ReviewerResult(
            context=context,
            decision=self.decision,
            findings=(ReviewFinding(
                severity="WARNING", category="SPY_COMPARISON_QUALITY",
                message="The supplied packet does not establish a durable advantage over SPY.",
                related_evidence_ids=(context.decision_result.context.research_batch.packets[0].evidence_items[0].evidence_id,),
                related_recommendation_field="why_not_spy",
                what_would_change="A directly comparable, cited SPY analysis would resolve this concern.",
            ),),
            reviewed_at=START + timedelta(minutes=4),
            metadata=ReviewerMetadata("fake-reviewer", "test-v1", "fake", "fake-model"),
            rationale="The recommendation is mechanically valid but evidence quality remains advisory concern.",
        )


class _Response:
    status = "completed"
    id = "response-review"
    _request_id = "request-review"
    output_text = '''{"decision":"REQUEST_CHANGES","rationale":"Evidence needs normalization.","findings":[{"severity":"WARNING","category":"REASONING_QUALITY","message":"FCF normalization is not established.","related_evidence_ids":["%s"],"related_recommendation_field":"valuation","what_would_change":"A normalized FCF bridge."}]}'''

    def __init__(self, evidence_id: str) -> None:
        self.output_text = self.output_text % evidence_id


class _Responses:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


class _Client:
    def __init__(self, response: _Response) -> None:
        self.responses = _Responses(response)


def _reviewed(tmp_path):
    store, batch, _ = _prepared_store(tmp_path)
    journal = RunValueManagerService(store, manager=_Manager()).run(occurred_at=START + timedelta(minutes=3)).journal_entry
    reviewer = _Reviewer()
    result = ReviewDecisionService(store, reviewer=reviewer).review(decision_cycle_id=journal.decision_cycle_id)
    return store, batch, journal, reviewer, result.reviewer_result


def test_review_persists_exact_current_artifacts_and_survives_restart(tmp_path) -> None:
    store, batch, journal, reviewer, result = _reviewed(tmp_path)

    assert reviewer.contexts == [result.context]
    assert result.context.decision_result == journal.decision_result
    assert result.context.decision_result.context.research_batch == batch
    assert result.context.policy_reference == journal.policy_reference
    assert result.context.manager_assessment == journal.two_layer_evaluation.manager_assessment
    reopened = SQLiteLocalRunStore(tmp_path / "run.sqlite").open_run()
    assert reopened is not None
    assert reopened.reviewer_results[0].decision_cycle_id == journal.decision_cycle_id
    assert reopened.reviewer_results[0].context.research_batch_id == batch.batch_id
    assert reopened.reviewer_results[0].metadata == result.metadata


def test_review_is_advisory_and_human_approval_remains_required(tmp_path) -> None:
    store, _, journal, _, result = _reviewed(tmp_path)

    assert result.decision.value == "REQUEST_CHANGES"
    assert not store.open_run().approvals
    approval = DecisionApprovalService(store).decide(
        decision_cycle_id=journal.decision_cycle_id, decision=ApprovalDecision.APPROVED,
        decision_maker_id="operator", decided_at=START + timedelta(minutes=5),
        comment="Human accepts advisory concern for paper experiment.",
    )
    assert approval.decision is ApprovalDecision.APPROVED
    assert journal.decision_result.recommendation.target_weight == result.context.decision_result.recommendation.target_weight
    from fastapi.testclient import TestClient
    history = TestClient(create_app(database_path=str(tmp_path / "run.sqlite"), reviewer=_Reviewer())).get("/decisions")
    assert history.status_code == 200
    assert history.json()["entries_newest_first"][0]["reviewer_outcome"] == "REQUEST_CHANGES"


def test_duplicate_and_cross_cycle_reviewer_artifacts_are_rejected(tmp_path) -> None:
    store, batch, journal, reviewer, _ = _reviewed(tmp_path)
    with pytest.raises(DecisionCommandConflict, match="immutable reviewer result"):
        ReviewDecisionService(store, reviewer=reviewer).review(decision_cycle_id=journal.decision_cycle_id)

    state = store.open_run()
    assert state is not None
    other_batch = replace(batch, batch_id="other", decision_cycle_id=__import__("uuid").uuid4(), created_at=START + timedelta(minutes=6), as_of_timestamp=START + timedelta(minutes=6))
    store.save_transition(replace(state, research_batches=(*state.research_batches, other_batch)))
    with pytest.raises(ValueError, match="no canonical persisted journal"):
        ReviewDecisionService(store, reviewer=reviewer).review(decision_cycle_id=other_batch.decision_cycle_id)


def test_failed_safety_and_hold_do_not_become_executable_from_reviewer(tmp_path) -> None:
    failed_store, _, _ = _prepared_store(tmp_path / "failed", include_price=False)
    failed = RunValueManagerService(failed_store, manager=_Manager()).run(occurred_at=START + timedelta(minutes=3)).journal_entry
    with pytest.raises(DecisionCommandConflict, match="System Safety"):
        ReviewDecisionService(failed_store, reviewer=_Reviewer()).review(decision_cycle_id=failed.decision_cycle_id)

    hold_store, _, _ = _prepared_store(tmp_path / "hold")
    hold = RunValueManagerService(hold_store, manager=_Manager("HOLD")).run(occurred_at=START + timedelta(minutes=3)).journal_entry
    ReviewDecisionService(hold_store, reviewer=_Reviewer()).review(decision_cycle_id=hold.decision_cycle_id)
    assert hold.risk_validation_result.validated_trade is None
    assert not hold_store.open_run().executions


def test_review_api_projects_metadata_findings_and_legacy_null(tmp_path) -> None:
    from fastapi.testclient import TestClient

    store, batch, _, _, _ = _reviewed(tmp_path)
    client = TestClient(create_app(database_path=str(tmp_path / "run.sqlite"), reviewer=_Reviewer()))
    response = client.get("/decisions/latest")
    assert response.status_code == 200
    reviewer = response.json()["reviewer"]
    assert reviewer["decision"] == "REQUEST_CHANGES"
    assert reviewer["provider"] == "fake"
    assert reviewer["findings"][0]["what_would_change"].startswith("A directly")
    duplicate = client.post(f"/commands/decisions/{batch.decision_cycle_id}/review")
    assert duplicate.status_code == 409


def test_openai_reviewer_uses_only_exact_serialized_artifacts_and_structured_output(tmp_path) -> None:
    _, _, _, reviewer, result = _reviewed(tmp_path)
    evidence_id = result.context.decision_result.context.research_batch.packets[0].evidence_items[0].evidence_id
    client = _Client(_Response(evidence_id))
    adapter = OpenAIReviewer(client=client, model="review-test", clock=lambda: START + timedelta(minutes=5))

    reviewed = adapter.review(reviewer.contexts[0])

    assert reviewed.metadata is not None and reviewed.metadata.response_id == "response-review"
    assert reviewed.context is reviewer.contexts[0]
    request = client.responses.kwargs
    assert request["store"] is False
    assert request["text"]["format"]["name"] == "ai_reviewer_result"
    prompt = request["input"][1]["content"][0]["text"]
    assert "screening_run_id" not in prompt and "slot_role" not in prompt and "rank" not in prompt
    assert "risk_evaluation_snapshot" in prompt and "price_observation" in prompt and "source_provider_identity" in prompt
    assert "position_valuations" in prompt and "endpoint_coverage" in prompt and "derived_metrics" in prompt and "actual_value" in prompt
