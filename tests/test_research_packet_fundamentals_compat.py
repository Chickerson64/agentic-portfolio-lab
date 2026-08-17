from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from agentic_portfolio_lab.application.local_state_codec import decode, encode
from agentic_portfolio_lab.domain.provider_fundamentals import (
    FreshnessClass,
    ProviderEndpoint,
    ReliabilityClass,
    ReuseStatus,
)
from agentic_portfolio_lab.domain.research import (
    EvidenceItem,
    PacketComponentCoverage,
    PacketFundamentals,
    ResearchBatch,
    ResearchPacket,
    ResearchSection,
)


UTC = timezone.utc


def _packet(**overrides: object) -> ResearchPacket:
    values = dict(
        packet_id="rp_aapl",
        candidate_id="cand_aapl",
        ticker="AAPL",
        security_type="EQUITY",
        as_of_timestamp=datetime(2026, 8, 12, 14, tzinfo=UTC),
        evidence_items=(
            EvidenceItem("ev_01", "FILING", "Quarterly Report", date(2026, 8, 1), "Revenue grew."),
        ),
        sections=(ResearchSection("business", "Summary", ("ev_01",)),),
    )
    values.update(overrides)
    return ResearchPacket(**values)  # type: ignore[arg-type]


def test_research_packet_defaults_fundamentals_to_none() -> None:
    packet = _packet()

    assert packet.fundamentals is None


def test_research_batch_defaults_screening_run_id_to_none() -> None:
    batch = ResearchBatch(
        batch_id="rb_001",
        decision_cycle_id=uuid4(),
        portfolio_id=uuid4(),
        manager_type="VALUE",
        created_at=datetime(2026, 8, 12, 15, tzinfo=UTC),
        as_of_timestamp=datetime(2026, 8, 12, 14, tzinfo=UTC),
        packets=(_packet(),),
    )

    assert batch.screening_run_id is None


def test_codec_round_trips_old_packet_without_fundamentals_key() -> None:
    packet = _packet()
    document = encode(packet)
    document["fields"].pop("fundamentals", None)

    decoded = decode(document)

    assert isinstance(decoded, ResearchPacket)
    assert decoded.fundamentals is None
    assert decoded.packet_id == packet.packet_id


def test_codec_round_trips_packet_with_fundamentals() -> None:
    fundamentals = PacketFundamentals(
        coverage=(
            PacketComponentCoverage(
                endpoint=ProviderEndpoint.OVERVIEW,
                reuse_status=ReuseStatus.REUSED_CURRENT,
                freshness=FreshnessClass.FRESH,
                reliability=ReliabilityClass.PRIMARY_STATEMENT,
                fiscal_period=date(2026, 6, 30),
                source_date=date(2026, 6, 30),
                fetched_at=datetime(2026, 8, 10, 12, tzinfo=UTC),
            ),
        ),
    )
    packet = _packet(fundamentals=fundamentals)

    decoded = decode(encode(packet))

    assert decoded == packet
    assert decoded.fundamentals == fundamentals
