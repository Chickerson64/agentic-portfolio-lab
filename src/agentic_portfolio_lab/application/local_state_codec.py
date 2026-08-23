"""Explicit JSON codec for the local immutable state graph.

This is deliberately a small, whitelisted codec rather than pickle, repr, or a
general persistence framework.  Every document carries a visible type marker
and field values are represented with JSON-safe primitives.
"""

from __future__ import annotations

from dataclasses import MISSING, fields, is_dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from .local_state import LocalRunMetadata, PersistedRunState


def _apply_dataclass_defaults(model_type: type[object], decoded_fields: dict[str, Any]) -> dict[str, Any]:
    """Fill omitted dataclass fields from defaults so older documents still decode."""
    completed = dict(decoded_fields)
    for item in fields(model_type):
        if item.name in completed:
            continue
        if item.default is not MISSING:
            completed[item.name] = item.default
        elif item.default_factory is not MISSING:
            completed[item.name] = item.default_factory()
    return completed


def _types() -> dict[str, type[object]]:
    # Imports are intentionally explicit: only known local domain/application
    # artifacts may be rehydrated from a durable database document.
    from agentic_portfolio_lab.dashboard import DecisionHistoryArtifacts
    from agentic_portfolio_lab.domain import approval, benchmark_fulfillment, cash_events, constitution, journal, performance, policy, portfolio, provider_fundamentals, recommendations, research, research_provider, reviewer, risk_validation, screening, simulated_execution, trades, universe, valuation, value_manager, value_manager_workflow

    modules = (
        approval, benchmark_fulfillment, cash_events, constitution, journal, performance, policy, portfolio,
        provider_fundamentals, recommendations, research, research_provider, reviewer, risk_validation,
        screening, simulated_execution, trades, universe, valuation, value_manager, value_manager_workflow,
    )
    registry = {
        f"{LocalRunMetadata.__module__}.{LocalRunMetadata.__qualname__}": LocalRunMetadata,
        f"{PersistedRunState.__module__}.{PersistedRunState.__qualname__}": PersistedRunState,
        f"{DecisionHistoryArtifacts.__module__}.{DecisionHistoryArtifacts.__qualname__}": DecisionHistoryArtifacts,
    }
    for module in modules:
        for candidate in vars(module).values():
            if isinstance(candidate, type) and (is_dataclass(candidate) or issubclass(candidate, Enum)):
                registry[f"{candidate.__module__}.{candidate.__qualname__}"] = candidate
    return registry


def encode(value: Any) -> Any:
    if isinstance(value, Enum):
        return {"$type": f"enum:{value.__class__.__module__}.{value.__class__.__qualname__}", "value": value.value}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return {"$type": "decimal", "value": format(value, "f")}
    if isinstance(value, datetime):
        return {"$type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"$type": "date", "value": value.isoformat()}
    if isinstance(value, UUID):
        return {"$type": "uuid", "value": str(value)}
    if isinstance(value, tuple):
        return {"$type": "tuple", "items": [encode(item) for item in value]}
    if is_dataclass(value):
        type_name = f"{value.__class__.__module__}.{value.__class__.__qualname__}"
        return {"$type": type_name, "fields": {item.name: encode(getattr(value, item.name)) for item in fields(value)}}
    raise TypeError(f"unsupported local-state value: {type(value)!r}")


def decode(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if not isinstance(value, dict) or "$type" not in value:
        raise ValueError("persisted document contains an invalid value")
    marker = value["$type"]
    if marker == "decimal":
        return Decimal(value["value"])
    if marker == "datetime":
        return datetime.fromisoformat(value["value"])
    if marker == "date":
        return date.fromisoformat(value["value"])
    if marker == "uuid":
        return UUID(value["value"])
    if marker == "tuple":
        return tuple(decode(item) for item in value["items"])
    registry = _types()
    if marker.startswith("enum:"):
        enum_type = registry.get(marker.removeprefix("enum:"))
        if enum_type is None or not issubclass(enum_type, Enum):
            raise ValueError("persisted document contains an unsupported enum")
        return enum_type(value["value"])
    model_type = registry.get(marker)
    if model_type is None or not is_dataclass(model_type):
        raise ValueError("persisted document contains an unsupported type")
    raw_fields = value.get("fields")
    if not isinstance(raw_fields, dict):
        raise ValueError("persisted dataclass document is missing fields")
    decoded_fields = {name: decode(item) for name, item in raw_fields.items()}
    decoded_fields = _apply_dataclass_defaults(model_type, decoded_fields)
    # A history panel requires its approval to reference its exact in-memory
    # journal instance. Recreate that local edge before its constructor checks
    # run; decode_run_state later canonicalizes it to the aggregate journal.
    if marker == "agentic_portfolio_lab.dashboard.DecisionHistoryArtifacts":
        approval = decoded_fields.get("approval")
        journal = decoded_fields["journal_entry"]
        if approval is not None:
            from agentic_portfolio_lab.domain.approval import DecisionApproval

            decoded_fields["approval"] = DecisionApproval(
                journal_entry=journal,
                decision_maker_id=approval.decision_maker_id,
                decision=approval.decision,
                decided_at=approval.decided_at,
                comment=approval.comment,
            )
        trade = decoded_fields.get("executed_trade")
        if trade is not None:
            from agentic_portfolio_lab.domain.trades import ExecutedTrade

            decoded_fields["executed_trade"] = ExecutedTrade(
                validated_trade=journal.risk_validation_result.validated_trade,
                executed_quantity=trade.executed_quantity,
                execution_price=trade.execution_price,
                source_provider_identity=trade.source_provider_identity,
                market_date=trade.market_date,
                currency=trade.currency,
                price_convention=trade.price_convention,
                executed_at=trade.executed_at,
                execution_source=trade.execution_source,
                executed_trade_id=trade.executed_trade_id,
            )
    if marker == f"{PersistedRunState.__module__}.{PersistedRunState.__qualname__}":
        # The graph is decoded independently, then canonicalized below before
        # aggregate validation. Bypassing this one aggregate constructor here
        # does not bypass any domain constructor invariant.
        raw_state = object.__new__(PersistedRunState)
        for name, item in decoded_fields.items():
            object.__setattr__(raw_state, name, item)
        return raw_state
    return model_type(**decoded_fields)


def decode_run_state(value: Any) -> PersistedRunState:
    """Rehydrate one state graph and restore shared lineage object references."""
    state = decode(value)
    if not isinstance(state, PersistedRunState):
        raise ValueError("persisted document is not a local run state")
    from agentic_portfolio_lab.dashboard import DecisionHistoryArtifacts
    from agentic_portfolio_lab.domain.approval import DecisionApproval
    from agentic_portfolio_lab.domain.journal import DecisionJournalEntry
    from agentic_portfolio_lab.domain.reviewer import AIReviewerReviewContext, ReviewerResult
    from agentic_portfolio_lab.domain.risk_validation import ManagerConstitutionAssessment, TwoLayerEvaluationResult
    from agentic_portfolio_lab.domain.simulated_execution import SimulatedExecutionResult
    from agentic_portfolio_lab.domain.value_manager import ValueManagerDecisionContext
    from agentic_portfolio_lab.domain.value_manager_workflow import ValueManagerDecisionResult

    batches = {batch.batch_id: batch for batch in state.research_batches}
    canonical_journals = []
    for journal in state.journal_entries:
        raw_context = journal.decision_result.context
        research_batch = batches.get(raw_context.research_batch.batch_id)
        if research_batch is None:
            raise ValueError("persisted journal is missing its canonical ResearchBatch")
        context = ValueManagerDecisionContext(
            portfolio=raw_context.portfolio,
            research_batch=research_batch,
            constitution=raw_context.constitution,
            prior_reviewer_feedback=raw_context.prior_reviewer_feedback,
        )
        decision_result = ValueManagerDecisionResult(
            context=context,
            recommendation=journal.decision_result.recommendation,
            produced_at=journal.decision_result.produced_at,
        )
        validation = replace(journal.risk_validation_result, decision_result=decision_result)
        two_layer_evaluation = journal.two_layer_evaluation
        if two_layer_evaluation is not None:
            assessment = two_layer_evaluation.manager_assessment
            if assessment is not None:
                assessment = ManagerConstitutionAssessment(
                    decision_result=decision_result,
                    assessment_timestamp=assessment.assessment_timestamp,
                    manager_risk_constitution=assessment.manager_risk_constitution,
                    risk_evaluation_snapshot=assessment.risk_evaluation_snapshot,
                    findings=assessment.findings,
                )
            two_layer_evaluation = TwoLayerEvaluationResult(
                safety_validation=validation,
                manager_assessment=assessment,
            )
        reviewer = journal.reviewer_result
        if reviewer is not None:
            reviewer_context = AIReviewerReviewContext(
                decision_result=decision_result,
                risk_validation_result=validation,
                constitution=reviewer.context.constitution,
            )
            reviewer = ReviewerResult(
                context=reviewer_context,
                decision=reviewer.decision,
                findings=reviewer.findings,
                reviewed_at=reviewer.reviewed_at,
            )
        canonical_journals.append(DecisionJournalEntry(
            decision_result=decision_result,
            risk_validation_result=validation,
            journaled_at=journal.journaled_at,
            reviewer_result=reviewer,
            policy_reference=journal.policy_reference,
            two_layer_evaluation=two_layer_evaluation,
        ))
    journals = {journal.decision_cycle_id: journal for journal in canonical_journals}
    approvals = tuple(
        DecisionApproval(
            journal_entry=journals[approval.decision_cycle_id],
            decision_maker_id=approval.decision_maker_id,
            decision=approval.decision,
            decided_at=approval.decided_at,
            comment=approval.comment,
        )
        for approval in state.approvals
    )
    approvals_by_cycle = {approval.decision_cycle_id: approval for approval in approvals}
    executions = tuple(
        _canonical_execution(execution, journals=journals, approvals=approvals_by_cycle)
        for execution in state.executions
    )
    executions_by_cycle = {execution.decision_cycle_id: execution for execution in executions}
    history_entries = tuple(
        _canonical_history_entry(entry, journals=journals, approvals=approvals_by_cycle, executions=executions_by_cycle)
        for entry in state.history_entries
    )
    observations = tuple(state.price_observations)
    observations_by_identity = {(item.security, item.observed_at): item for item in observations}
    from agentic_portfolio_lab.domain.performance import BenchmarkPerformanceHistory, PerformanceSnapshot, PortfolioPerformanceHistory
    funding_by_id = {item.cash_event.event_id: item.cash_event for item in state.funding_results}

    def canonical_history(history):
        snapshots = tuple(
            PerformanceSnapshot(
                snapshot.portfolio, snapshot.valuation, snapshot.baseline_value,
                snapshot.cumulative_external_contributions,
                tuple(funding_by_id[event.event_id] for event in snapshot.cash_events),
            )
            for snapshot in history.snapshots
        )
        if isinstance(history, BenchmarkPerformanceHistory):
            return BenchmarkPerformanceHistory(history.benchmark_portfolio_id, history.benchmark_security, history.currency, snapshots)
        return PortfolioPerformanceHistory(history.portfolio_id, history.currency, snapshots)

    managed_history = canonical_history(state.managed_history)
    benchmark_history = canonical_history(state.benchmark_history)
    from agentic_portfolio_lab.domain.benchmark_fulfillment import PassiveIndexFulfillment
    canonical_fulfillments = tuple(
        PassiveIndexFulfillment(
            intent=item.intent,
            price_observation=observations_by_identity[(item.price_observation.security, item.price_observation.observed_at)],
            original_benchmark_portfolio=item.original_benchmark_portfolio,
            fulfilled_benchmark_portfolio=item.fulfilled_benchmark_portfolio,
            target_purchase=item.target_purchase,
            quantity=item.quantity,
            notional=item.notional,
            fulfilled_at=item.fulfilled_at,
            fulfillment_id=item.fulfillment_id,
        )
        for item in getattr(state, "benchmark_fulfillments", ())
    )
    return PersistedRunState(
        metadata=state.metadata,
        managed_portfolio=state.managed_portfolio,
        benchmark_portfolio=state.benchmark_portfolio,
        managed_history=managed_history,
        benchmark_history=benchmark_history,
        funding_results=state.funding_results,
        price_observations=observations,
        research_batches=state.research_batches,
        journal_entries=tuple(canonical_journals),
        approvals=approvals,
        executions=executions,
        history_entries=history_entries,
        benchmark_fulfillments=canonical_fulfillments,
        screening_runs=getattr(state, "screening_runs", ()),
        fundamental_records=getattr(state, "fundamental_records", ()),
        benchmark_fulfillment_status=getattr(state, "benchmark_fulfillment_status", "PENDING_NO_ELIGIBLE_PRICE"),
    )


def _canonical_execution(execution, *, journals, approvals):
    from agentic_portfolio_lab.domain.simulated_execution import SimulatedExecutionResult
    from agentic_portfolio_lab.domain.trades import ExecutedTrade

    cycle_id = execution.decision_cycle_id
    journal = journals.get(cycle_id)
    approval = approvals.get(cycle_id)
    if journal is None or approval is None:
        raise ValueError("persisted execution is missing its canonical journal or approval")
    authoritative_trade = journal.risk_validation_result.validated_trade
    if authoritative_trade is None:
        raise ValueError("persisted execution journal is missing its authoritative validated trade")
    raw_trade = execution.executed_trade
    canonical_trade = ExecutedTrade(
        validated_trade=authoritative_trade,
        executed_quantity=raw_trade.executed_quantity,
        execution_price=raw_trade.execution_price,
        source_provider_identity=raw_trade.source_provider_identity,
        market_date=raw_trade.market_date,
        currency=raw_trade.currency,
        price_convention=raw_trade.price_convention,
        executed_at=raw_trade.executed_at,
        execution_source=raw_trade.execution_source,
        executed_trade_id=raw_trade.executed_trade_id,
    )
    return SimulatedExecutionResult(
        approval=approval,
        original_portfolio=execution.original_portfolio,
        execution_observation=execution.execution_observation,
        execution_target_purchase=execution.execution_target_purchase,
        executed_trade=canonical_trade,
        updated_portfolio=execution.updated_portfolio,
    )


def _canonical_history_entry(entry, *, journals, approvals, executions):
    from agentic_portfolio_lab.dashboard import DecisionHistoryArtifacts

    cycle_id = entry.journal_entry.decision_cycle_id
    journal = journals.get(cycle_id)
    if journal is None:
        raise ValueError("persisted history entry is missing its canonical journal")
    execution = executions.get(cycle_id)
    if entry.executed_trade is not None and execution is None:
        raise ValueError("persisted history execution is missing its canonical execution artifact")
    if execution is not None and entry.executed_trade is None:
        raise ValueError("persisted canonical execution is omitted from history")
    return DecisionHistoryArtifacts(
        journal_entry=journal,
        approval=approvals.get(cycle_id),
        executed_trade=None if execution is None else execution.executed_trade,
    )
