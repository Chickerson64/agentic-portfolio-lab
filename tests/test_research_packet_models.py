from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from agentic_portfolio_lab.domain.research import (
    EvidenceItem,
    MissingData,
    MissingDataReason,
    ResearchBatch,
    ResearchPacket,
    ResearchSection,
)


def _evidence(evidence_id: str = " ev_01 ", source_date: date = date(2026, 8, 1)) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        source_type=" filing ",
        source_title=" Quarterly Report ",
        source_date=source_date,
        claim_supported="Revenue grew during the reported quarter.",
    )


def _packet(
    *,
    packet_id: str = " rp_aapl ",
    candidate_id: str = " cand_aapl ",
    ticker: str = " aapl ",
    security_type: str = " equity ",
    exchange: str | MissingData = " nasdaq ",
    currency: str | MissingData = " usd ",
    as_of_timestamp: datetime = datetime(2026, 8, 12, 14, tzinfo=timezone.utc),
    evidence_source_date: date = date(2026, 8, 1),
) -> ResearchPacket:
    return ResearchPacket(
        packet_id=packet_id,
        candidate_id=candidate_id,
        ticker=ticker,
        security_type=security_type,
        as_of_timestamp=as_of_timestamp,
        evidence_items=[_evidence(source_date=evidence_source_date)],
        sections=[
            ResearchSection(
                section_id=" business_overview ",
                content="The company sells consumer devices and services.",
                evidence_ids=[" ev_01 "],
            )
        ],
        company_name=" Apple Inc. ",
        exchange=exchange,
        currency=currency,
    )


def _batch(
    *,
    packets: list[ResearchPacket] | tuple[ResearchPacket, ...] | None = None,
    created_at: datetime = datetime(2026, 8, 12, 15, tzinfo=timezone.utc),
    as_of_timestamp: datetime = datetime(2026, 8, 12, 14, tzinfo=timezone.utc),
) -> ResearchBatch:
    return ResearchBatch(
        batch_id=" rb_001 ",
        decision_cycle_id=uuid4(),
        portfolio_id=uuid4(),
        manager_type=" value ",
        created_at=created_at,
        as_of_timestamp=as_of_timestamp,
        packets=packets if packets is not None else [_packet()],
    )


def test_research_packet_constructs_a_normalized_source_backed_security_packet() -> None:
    packet = _packet()

    assert packet.packet_id == "rp_aapl"
    assert packet.candidate_id == "cand_aapl"
    assert packet.ticker == "AAPL"
    assert packet.security_type == "EQUITY"
    assert packet.exchange == "NASDAQ"
    assert packet.currency == "USD"
    assert packet.evidence_items[0].evidence_id == "ev_01"
    assert packet.evidence_items[0].source_type == "FILING"
    assert packet.sections[0].section_id == "BUSINESS_OVERVIEW"
    assert packet.sections[0].evidence_ids == ("ev_01",)


def test_research_batch_is_an_ordered_decision_cycle_container() -> None:
    first = _packet(packet_id="rp_first", candidate_id="cand_first")
    second = _packet(packet_id="rp_second", candidate_id="cand_second", ticker="MSFT")

    batch = _batch(packets=[second, first])

    assert batch.manager_type == "VALUE"
    assert batch.packets == (second, first)
    assert batch.packets[0].packet_id == "rp_second"


def test_packet_and_batch_are_immutable() -> None:
    packet = _packet()
    batch = _batch()

    with pytest.raises(FrozenInstanceError):
        packet.ticker = "MSFT"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        batch.packets = tuple()  # type: ignore[misc]
    assert isinstance(packet.evidence_items, tuple)
    assert isinstance(batch.packets, tuple)


def test_packet_and_batch_require_timezone_aware_instants() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ResearchPacket(
            packet_id="rp_aapl", candidate_id="cand_aapl", ticker="AAPL", security_type="EQUITY",
            as_of_timestamp=datetime(2026, 8, 12, 14), evidence_items=[_evidence()],
            sections=[ResearchSection("business", "Summary", ["ev_01"])],
        )

    with pytest.raises(ValueError, match="timezone-aware"):
        ResearchBatch(
            batch_id="rb_001", decision_cycle_id=uuid4(), portfolio_id=uuid4(), manager_type="VALUE",
            created_at=datetime(2026, 8, 12, 15), as_of_timestamp=datetime(2026, 8, 12, 14, tzinfo=timezone.utc),
            packets=[_packet()],
        )


def test_evidence_source_date_is_date_only() -> None:
    with pytest.raises(TypeError, match="date, not a datetime"):
        EvidenceItem(
            evidence_id="ev_01", source_type="FILING", source_title="Quarterly Report",
            source_date=datetime(2026, 8, 1, tzinfo=timezone.utc),  # type: ignore[arg-type]
            claim_supported="Revenue grew.",
        )


def test_missing_data_is_explicit_and_not_none() -> None:
    packet = ResearchPacket(
        packet_id="rp_aapl", candidate_id="cand_aapl", ticker="AAPL", security_type="EQUITY",
        as_of_timestamp=datetime(2026, 8, 12, 14, tzinfo=timezone.utc), evidence_items=[_evidence()],
        sections=[ResearchSection("market_price", MissingData(MissingDataReason.NOT_AVAILABLE), [])],
        company_name=MissingData(MissingDataReason.UNKNOWN, "Issuer name was absent from the source."),
    )

    assert isinstance(packet.company_name, MissingData)
    assert packet.sections[0].content == MissingData(MissingDataReason.NOT_AVAILABLE)
    assert packet.sections[0].evidence_ids == tuple()
    with pytest.raises(TypeError):
        ResearchSection("market_price", None, [])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("evidence_items", "sections", "error"),
    [
        ([], [ResearchSection("business", "Summary", ["ev_01"])], "evidence_items must not be empty"),
        ([_evidence("ev_01"), _evidence(" ev_01 ")], [ResearchSection("business", "Summary", ["ev_01"])], "duplicate evidence_id"),
        ([_evidence()], [ResearchSection("business", "Summary", ["ev_missing"])], "reference evidence_items"),
        ([_evidence()], [], "sections must not be empty"),
    ],
)
def test_packet_rejects_malformed_evidence_and_section_references(
    evidence_items: list[EvidenceItem], sections: list[ResearchSection], error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        ResearchPacket(
            packet_id="rp_aapl", candidate_id="cand_aapl", ticker="AAPL", security_type="EQUITY",
            as_of_timestamp=datetime(2026, 8, 12, 14, tzinfo=timezone.utc),
            evidence_items=evidence_items, sections=sections,
        )


@pytest.mark.parametrize(
    "arguments",
    [
        {"evidence_id": "", "source_type": "FILING", "source_title": "Report", "source_date": date(2026, 8, 1), "claim_supported": "Claim"},
        {"evidence_id": "ev_01", "source_type": "", "source_title": "Report", "source_date": date(2026, 8, 1), "claim_supported": "Claim"},
        {"evidence_id": "ev_01", "source_type": "FILING", "source_title": "", "source_date": date(2026, 8, 1), "claim_supported": "Claim"},
        {"evidence_id": "ev_01", "source_type": "FILING", "source_title": "Report", "source_date": date(2026, 8, 1), "claim_supported": ""},
    ],
)
def test_evidence_item_rejects_malformed_required_fields(arguments: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        EvidenceItem(**arguments)  # type: ignore[arg-type]


def test_section_rejects_malformed_evidence_identifier_containers() -> None:
    with pytest.raises(TypeError, match="tuple or list"):
        ResearchSection("business", "Summary", "ev_01")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="string"):
        ResearchSection("business", "Summary", [1])  # type: ignore[list-item]
    with pytest.raises(ValueError, match="must not be empty"):
        ResearchSection("business", "Summary", [""])


def test_batch_rejects_duplicate_packet_and_candidate_identities() -> None:
    with pytest.raises(ValueError, match="duplicate packet_id"):
        _batch(packets=[_packet(packet_id="rp_same", candidate_id="cand_one"), _packet(packet_id=" rp_same ", candidate_id="cand_two")])
    with pytest.raises(ValueError, match="duplicate candidate_id"):
        _batch(packets=[_packet(packet_id="rp_one", candidate_id="cand_same"), _packet(packet_id="rp_two", candidate_id=" cand_same ")])


def test_batch_rejects_duplicate_normalized_security_identities() -> None:
    first = _packet(packet_id="rp_one", candidate_id="cand_one")
    same_security = _packet(
        packet_id="rp_two",
        candidate_id="cand_two",
        ticker=" AAPL ",
        security_type=" Equity ",
        exchange=" NASDAQ ",
        currency=" USD ",
    )

    with pytest.raises(ValueError, match="security identities"):
        _batch(packets=[first, same_security])


def test_batch_rejects_ambiguous_security_identity_with_missing_optional_fields() -> None:
    incomplete_identity = _packet(
        packet_id="rp_one",
        candidate_id="cand_one",
        exchange=MissingData(MissingDataReason.UNKNOWN),
    )
    known_identity = _packet(packet_id="rp_two", candidate_id="cand_two", exchange="NASDAQ")

    with pytest.raises(ValueError, match="security identities"):
        _batch(packets=[incomplete_identity, known_identity])


def test_batch_allows_genuinely_different_security_identities() -> None:
    aapl = _packet(packet_id="rp_aapl", candidate_id="cand_aapl")
    msft = _packet(packet_id="rp_msft", candidate_id="cand_msft", ticker="MSFT")

    batch = _batch(packets=[aapl, msft])

    assert batch.packets == (aapl, msft)


def test_batch_requires_at_least_one_packet() -> None:
    with pytest.raises(ValueError, match="packets must not be empty"):
        _batch(packets=[])


def test_batch_enforces_created_and_packet_freshness_boundaries() -> None:
    batch_as_of = datetime(2026, 8, 12, 14, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="created_at"):
        _batch(created_at=datetime(2026, 8, 12, 13, 59, tzinfo=timezone.utc), as_of_timestamp=batch_as_of)

    equal_timestamps = _batch(created_at=batch_as_of, as_of_timestamp=batch_as_of)
    assert equal_timestamps.created_at == equal_timestamps.as_of_timestamp

    future_packet = _packet(
        as_of_timestamp=datetime(2026, 8, 12, 15, tzinfo=timezone.utc),
        evidence_source_date=date(2026, 8, 12),
    )
    with pytest.raises(ValueError, match="packet as_of_timestamp"):
        _batch(packets=[future_packet], as_of_timestamp=batch_as_of)

    older_packet = _packet(as_of_timestamp=datetime(2026, 8, 12, 13, tzinfo=timezone.utc))
    batch = _batch(packets=[older_packet], as_of_timestamp=batch_as_of)
    assert batch.packets == (older_packet,)


def test_packet_rejects_evidence_published_after_its_freshness_cutoff() -> None:
    with pytest.raises(ValueError, match="source_date"):
        _packet(evidence_source_date=date(2026, 8, 13))

    packet = _packet(evidence_source_date=date(2026, 8, 12))
    assert packet.evidence_items[0].source_date == packet.as_of_timestamp.date()


def test_packets_and_batches_remain_separate_models() -> None:
    with pytest.raises(TypeError, match="ResearchPacket"):
        _batch(packets=["not-a-packet"])  # type: ignore[list-item]

    packet = _packet()
    assert not isinstance(packet, ResearchBatch)


def test_packet_defaults_fundamentals_and_batch_defaults_screening_run_id() -> None:
    packet = _packet()
    batch = _batch()

    assert packet.fundamentals is None
    assert batch.screening_run_id is None


def test_batch_rejects_non_uuid_screening_run_id() -> None:
    with pytest.raises(TypeError, match="screening_run_id must be a UUID"):
        ResearchBatch(
            batch_id="rb_001",
            decision_cycle_id=uuid4(),
            portfolio_id=uuid4(),
            manager_type="VALUE",
            created_at=datetime(2026, 8, 12, 15, tzinfo=timezone.utc),
            as_of_timestamp=datetime(2026, 8, 12, 14, tzinfo=timezone.utc),
            packets=[_packet()],
            screening_run_id="not-a-uuid",  # type: ignore[arg-type]
        )
