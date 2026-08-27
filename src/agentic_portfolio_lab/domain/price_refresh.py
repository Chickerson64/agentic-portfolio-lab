"""Durable lifecycle metadata for one provider price-refresh attempt."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class PriceRefreshOperationStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class PriceRefreshOperation:
    operation_id: UUID
    status: PriceRefreshOperationStatus
    started_at: datetime
    provider_identity: str
    expected_security_count: int
    completed_at: datetime | None = None
    persisted_observation_count: int | None = None
    latest_source_timestamp: datetime | None = None
    failure_code: str | None = None
    failure_message: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, UUID):
            raise TypeError("operation_id must be a UUID")
        if not isinstance(self.status, PriceRefreshOperationStatus):
            raise TypeError("status must be PriceRefreshOperationStatus")
        if not isinstance(self.started_at, datetime) or self.started_at.tzinfo is None:
            raise ValueError("started_at must be timezone-aware")
        if not isinstance(self.provider_identity, str) or not self.provider_identity.strip():
            raise ValueError("provider_identity must be non-empty")
        if not isinstance(self.expected_security_count, int) or self.expected_security_count < 1:
            raise ValueError("expected_security_count must be positive")
        if self.status is PriceRefreshOperationStatus.IN_PROGRESS:
            if any(value is not None for value in (self.completed_at, self.persisted_observation_count, self.latest_source_timestamp, self.failure_code, self.failure_message)):
                raise ValueError("in-progress refresh operation must not have terminal metadata")
            return
        if not isinstance(self.completed_at, datetime) or self.completed_at.tzinfo is None or self.completed_at < self.started_at:
            raise ValueError("terminal refresh operation requires completed_at at or after started_at")
        if self.status is PriceRefreshOperationStatus.COMPLETED:
            if not isinstance(self.persisted_observation_count, int) or self.persisted_observation_count < 0:
                raise ValueError("completed refresh operation requires persisted_observation_count")
            if not isinstance(self.latest_source_timestamp, datetime) or self.latest_source_timestamp.tzinfo is None:
                raise ValueError("completed refresh operation requires latest_source_timestamp")
            if self.failure_code is not None or self.failure_message is not None:
                raise ValueError("completed refresh operation must not have failure metadata")
        elif not isinstance(self.failure_code, str) or not self.failure_code.strip() or not isinstance(self.failure_message, str) or not self.failure_message.strip():
            raise ValueError("failed refresh operation requires failure code and message")

