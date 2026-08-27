"""Backend-owned lifecycle labels used by the history API."""

import pytest

from agentic_portfolio_lab.api.models import _history_lifecycle_label


@pytest.mark.parametrize(
    ("readiness_reason", "expected"),
    [
        ("REJECTED", "REJECTED"),
        ("NOT_APPROVED", "AWAITING APPROVAL"),
        ("POST_APPROVAL_QUOTE_REQUIRED", "APPROVED · AWAITING POST-APPROVAL QUOTE"),
        ("READY", "READY TO EXECUTE"),
        ("ALREADY_EXECUTED", "EXECUTED"),
        ("HOLD", "HOLD"),
        ("VALIDATION_FAILED", "VALIDATION FAILED"),
    ],
)
def test_history_lifecycle_labels_are_backend_owned(readiness_reason: str, expected: str) -> None:
    assert _history_lifecycle_label(readiness_reason) == expected


def test_expired_approval_is_not_collapsed_into_rejected() -> None:
    assert _history_lifecycle_label("REJECTED", approval_outcome="EXPIRED") == "EXPIRED"
