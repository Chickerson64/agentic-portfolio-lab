"""Durable append-only storage for V2 target batch audit trails."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from uuid import UUID

from agentic_portfolio_lab.application.local_state_codec import decode, encode
from agentic_portfolio_lab.domain.portfolio_decisions_v2 import PortfolioTargetAllocation
from agentic_portfolio_lab.domain.target_execution_v2 import BatchApproval, BatchTradePlan, SimulatedBatchExecution


@dataclass(frozen=True, slots=True)
class V2BatchAuditTrail:
    """One durable immutable target → plan → approval → execution lineage."""
    target: PortfolioTargetAllocation
    plan: BatchTradePlan
    approval: BatchApproval | None = None
    execution: SimulatedBatchExecution | None = None

    def __post_init__(self) -> None:
        if self.plan.target != self.target:
            raise ValueError("plan must retain the exact target")
        if self.approval is not None and self.approval.plan != self.plan:
            raise ValueError("approval must retain the exact plan")
        if self.execution is not None:
            if self.approval is None or self.execution.approval != self.approval:
                raise ValueError("execution must retain the exact approval")


class SQLiteV2BatchAuditStore:
    """Small independent SQLite repository; writes replace only a later stage.

    The one-document transaction preserves an all-or-nothing audit graph and
    lets V2 coexist with, rather than alter, V1 local-run history tables.
    """
    def __init__(self, database_path: str | Path) -> None:
        self._path = str(database_path)
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS v2_batch_audit (plan_id TEXT PRIMARY KEY, document TEXT NOT NULL)")

    def _connect(self):
        return sqlite3.connect(self._path)

    def save(self, trail: V2BatchAuditTrail) -> None:
        if not isinstance(trail, V2BatchAuditTrail): raise TypeError("trail must be V2BatchAuditTrail")
        document = __import__("json").dumps(encode(trail), separators=(",", ":"), sort_keys=True)
        with self._connect() as connection:
            existing = connection.execute("SELECT document FROM v2_batch_audit WHERE plan_id = ?", (str(trail.plan.plan_id),)).fetchone()
            if existing is not None:
                previous = decode(__import__("json").loads(existing[0]))
                if not isinstance(previous, V2BatchAuditTrail): raise ValueError("invalid persisted V2 audit trail")
                if previous.target != trail.target or previous.plan != trail.plan: raise ValueError("immutable V2 target or plan cannot be rewritten")
                if previous.approval is not None and previous.approval != trail.approval: raise ValueError("immutable V2 approval cannot be rewritten")
                if previous.execution is not None and previous.execution != trail.execution: raise ValueError("immutable V2 execution cannot be rewritten")
            connection.execute("INSERT OR REPLACE INTO v2_batch_audit VALUES (?, ?)", (str(trail.plan.plan_id), document))

    def load(self, plan_id: UUID) -> V2BatchAuditTrail | None:
        with self._connect() as connection:
            row = connection.execute("SELECT document FROM v2_batch_audit WHERE plan_id = ?", (str(plan_id),)).fetchone()
        if row is None: return None
        result = decode(__import__("json").loads(row[0]))
        if not isinstance(result, V2BatchAuditTrail): raise ValueError("invalid persisted V2 audit trail")
        return result
