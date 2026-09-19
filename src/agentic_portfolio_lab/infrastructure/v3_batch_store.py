"""Append-only SQLite serialization for V3 research batches."""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from uuid import UUID

from agentic_portfolio_lab.application.local_state_codec import decode, encode
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.research_v3 import CompanyResearchVersion, ResearchBatchV3


class SQLiteResearchV3Store:
    def __init__(self, database_path: str | Path) -> None:
        self._path = str(database_path)
        with sqlite3.connect(self._path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS research_v3_batches (batch_id TEXT PRIMARY KEY, document TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS research_v3_company_versions (version_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, security_type TEXT NOT NULL, exchange_name TEXT NOT NULL, currency TEXT NOT NULL, retrieved_at TEXT NOT NULL, document TEXT NOT NULL)")
            connection.execute("CREATE INDEX IF NOT EXISTS research_v3_company_versions_latest ON research_v3_company_versions (ticker, security_type, exchange_name, currency, retrieved_at DESC)")
            connection.execute("CREATE TABLE IF NOT EXISTS research_v3_daily_budget (budget_date TEXT PRIMARY KEY, consumed_subjects INTEGER NOT NULL)")

    def save(self, batch: ResearchBatchV3) -> None:
        if not isinstance(batch, ResearchBatchV3):
            raise TypeError("batch must be ResearchBatchV3")
        document = json.dumps(encode(batch), sort_keys=True, separators=(",", ":"))
        with sqlite3.connect(self._path) as connection:
            row = connection.execute("SELECT document FROM research_v3_batches WHERE batch_id = ?", (batch.batch_id,)).fetchone()
            if row is not None and row[0] != document:
                raise ValueError("V3 batches must not be rewritten")
            if row is None:
                connection.execute("INSERT INTO research_v3_batches VALUES (?, ?)", (batch.batch_id, document))

    def load(self, batch_id: str) -> ResearchBatchV3 | None:
        with sqlite3.connect(self._path) as connection:
            row = connection.execute("SELECT document FROM research_v3_batches WHERE batch_id = ?", (batch_id,)).fetchone()
        if row is None:
            return None
        batch = decode(json.loads(row[0]))
        if not isinstance(batch, ResearchBatchV3):
            raise ValueError("invalid persisted V3 batch")
        return batch

    def save_company_research(self, version: CompanyResearchVersion) -> None:
        """Append a successful provider response; never revise an old one."""
        if not isinstance(version, CompanyResearchVersion):
            raise TypeError("version must be CompanyResearchVersion")
        document = json.dumps(encode(version), sort_keys=True, separators=(",", ":"))
        security = version.security
        with sqlite3.connect(self._path) as connection:
            row = connection.execute("SELECT document FROM research_v3_company_versions WHERE version_id = ?", (version.version_id,)).fetchone()
            if row is not None:
                if row[0] != document:
                    raise ValueError("company research versions must not be rewritten")
                return
            connection.execute(
                "INSERT INTO research_v3_company_versions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (version.version_id, security.ticker, security.security_type, security.exchange, security.currency, version.retrieved_at.isoformat(), document),
            )

    def latest_company_research(self, security: SecurityIdentity) -> CompanyResearchVersion | None:
        if not isinstance(security, SecurityIdentity):
            raise TypeError("security must be SecurityIdentity")
        with sqlite3.connect(self._path) as connection:
            row = connection.execute(
                "SELECT document FROM research_v3_company_versions WHERE ticker = ? AND security_type = ? AND exchange_name = ? AND currency = ? ORDER BY retrieved_at DESC LIMIT 1",
                (security.ticker, security.security_type, security.exchange, security.currency),
            ).fetchone()
        if row is None:
            return None
        version = decode(json.loads(row[0]))
        if not isinstance(version, CompanyResearchVersion):
            raise ValueError("invalid persisted V3 company research version")
        return version

    def company_research_history(self, security: SecurityIdentity) -> tuple[CompanyResearchVersion, ...]:
        """Return immutable versions newest first for audit and recovery tooling."""
        if not isinstance(security, SecurityIdentity):
            raise TypeError("security must be SecurityIdentity")
        with sqlite3.connect(self._path) as connection:
            rows = connection.execute(
                "SELECT document FROM research_v3_company_versions WHERE ticker = ? AND security_type = ? AND exchange_name = ? AND currency = ? ORDER BY retrieved_at DESC",
                (security.ticker, security.security_type, security.exchange, security.currency),
            ).fetchall()
        versions = tuple(decode(json.loads(row[0])) for row in rows)
        if not all(isinstance(version, CompanyResearchVersion) for version in versions):
            raise ValueError("invalid persisted V3 company research version")
        return versions

    def consume_daily_deep_research_budget(self, budget_date: date, *, limit: int) -> bool:
        """Atomically reserve one company-sized (three-call) retrieval slot."""
        if not isinstance(budget_date, date) or limit <= 0:
            raise ValueError("budget_date and positive limit are required")
        with sqlite3.connect(self._path) as connection:
            result = connection.execute(
                "INSERT INTO research_v3_daily_budget (budget_date, consumed_subjects) VALUES (?, 1) "
                "ON CONFLICT(budget_date) DO UPDATE SET consumed_subjects = consumed_subjects + 1 "
                "WHERE consumed_subjects < ?",
                (budget_date.isoformat(), limit),
            )
        return result.rowcount == 1
