"""Append-only SQLite serialization for V3 research batches."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import UUID

from agentic_portfolio_lab.application.local_state_codec import decode, encode
from agentic_portfolio_lab.domain.research_v3 import ResearchBatchV3


class SQLiteResearchV3Store:
    def __init__(self, database_path: str | Path) -> None:
        self._path = str(database_path)
        with sqlite3.connect(self._path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS research_v3_batches (batch_id TEXT PRIMARY KEY, document TEXT NOT NULL)")

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
