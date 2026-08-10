"""Deterministic loading for the approved Value Manager constitution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import re
from uuid import UUID

from .portfolio import (
    SecurityIdentity,
    _canonical_upper_text,
    _require_non_empty_text,
    _require_positive_decimal,
)
from .valuation import BenchmarkPortfolio

_VALUE_MANAGER_TYPE = "VALUE"
_SEMANTIC_VERSION_PATTERN = re.compile(r"^[a-z][a-z0-9-]*-v[0-9]+\.[0-9]+\.[0-9]+$")
_PASSIVE_INDEX_BUY_ACTION = "BUY"
NEXT_APPLICABLE_REGULAR_SESSION_CLOSE = "NEXT_APPLICABLE_REGULAR_SESSION_CLOSE"


@dataclass(frozen=True, slots=True)
class ConstitutionVersion:
    """A stable, semantic-style identifier for one approved constitution."""

    value: str

    def __post_init__(self) -> None:
        value = _require_non_empty_text(self.value, field_name="constitution version").strip()
        if not _SEMANTIC_VERSION_PATTERN.fullmatch(value):
            raise ValueError("constitution version must use the form '<manager>-v<major>.<minor>.<patch>'")
        object.__setattr__(self, "value", value)


_PASSIVE_INDEX_VERSION = ConstitutionVersion("passive-index-v1.0.0")


@dataclass(frozen=True, slots=True)
class PassiveIndexInvestmentIntent:
    """The complete deterministic instruction for later SPY deployment.

    This intent does not calculate a price, quantity, or timestamp. Those facts
    belong to the future deterministic validation and execution boundary.
    """

    benchmark_portfolio: BenchmarkPortfolio
    action: str
    deployment_rule: str
    constitution_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.benchmark_portfolio, BenchmarkPortfolio):
            raise TypeError("benchmark_portfolio must be a BenchmarkPortfolio")
        if self.benchmark_portfolio.benchmark_security.ticker != "SPY":
            raise ValueError("Passive Index intent security must be SPY")
        _require_positive_decimal(self.benchmark_portfolio.portfolio.cash_balance.amount, field_name="investable_cash")
        if _canonical_upper_text(self.action, field_name="action") != _PASSIVE_INDEX_BUY_ACTION:
            raise ValueError("Passive Index intent action must be BUY")
        object.__setattr__(self, "action", _PASSIVE_INDEX_BUY_ACTION)
        if self.deployment_rule != NEXT_APPLICABLE_REGULAR_SESSION_CLOSE:
            raise ValueError("deployment_rule must be NEXT_APPLICABLE_REGULAR_SESSION_CLOSE")
        version = ConstitutionVersion(self.constitution_version)
        if version.value != _PASSIVE_INDEX_VERSION.value:
            raise ValueError("constitution_version must match the Passive Index Constitution")
        object.__setattr__(self, "constitution_version", version.value)

    @property
    def benchmark_portfolio_id(self) -> UUID:
        """The identity of the benchmark state this intent describes."""
        return self.benchmark_portfolio.portfolio.portfolio_id

    @property
    def security(self) -> SecurityIdentity:
        """The benchmark's only permitted security: SPY."""
        return self.benchmark_portfolio.benchmark_security

    @property
    def investable_cash(self) -> Decimal:
        """All currently available benchmark cash; partial deployment is unsupported."""
        return self.benchmark_portfolio.portfolio.cash_balance.amount

    @property
    def currency(self) -> str:
        """The benchmark cash and portfolio base currency."""
        return self.benchmark_portfolio.portfolio.base_currency


@dataclass(frozen=True, slots=True)
class PassiveIndexConstitution:
    """Mechanically deploy all benchmark cash into SPY at the stated close rule."""

    version: ConstitutionVersion = _PASSIVE_INDEX_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.version, ConstitutionVersion):
            raise TypeError("version must be a ConstitutionVersion")
        if self.version.value != _PASSIVE_INDEX_VERSION.value:
            raise ValueError("Passive Index Constitution version must be passive-index-v1.0.0")

    @property
    def constitution_version(self) -> str:
        return self.version.value

    def evaluate(self, benchmark_portfolio: BenchmarkPortfolio) -> PassiveIndexInvestmentIntent | None:
        """Return one all-cash SPY intent, or no intent when cash is unavailable."""
        if not isinstance(benchmark_portfolio, BenchmarkPortfolio):
            raise TypeError("benchmark_portfolio must be a BenchmarkPortfolio")
        if benchmark_portfolio.benchmark_security.ticker != "SPY":
            raise ValueError("benchmark security must be SPY")
        investable_cash = benchmark_portfolio.portfolio.cash_balance.amount
        if investable_cash < 0:
            raise ValueError("investable cash must not be negative")
        if investable_cash.is_zero():
            return None
        return PassiveIndexInvestmentIntent(
            benchmark_portfolio=benchmark_portfolio,
            action=_PASSIVE_INDEX_BUY_ACTION,
            deployment_rule=NEXT_APPLICABLE_REGULAR_SESSION_CLOSE,
            constitution_version=self.constitution_version,
        )


@dataclass(frozen=True, slots=True)
class ValueManagerConstitution:
    """The immutable approved methodology artifact supplied to a Value Manager.

    ``content`` is preserved as source text rather than interpreted at runtime.
    This value object identifies and audits the artifact; it is not a policy
    engine or a parser for investment methodology.
    """

    version: ConstitutionVersion
    manager_type: str
    name: str
    description: str
    loading_source: str
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.version, ConstitutionVersion):
            raise TypeError("version must be a ConstitutionVersion")
        manager_type = _canonical_upper_text(self.manager_type, field_name="manager_type")
        if manager_type != _VALUE_MANAGER_TYPE:
            raise ValueError("ValueManagerConstitution manager_type must be VALUE")
        version_namespace = self.version.value.rsplit("-v", maxsplit=1)[0]
        if version_namespace != manager_type.lower():
            raise ValueError("constitution version namespace must match manager_type")
        object.__setattr__(self, "manager_type", manager_type)
        object.__setattr__(self, "name", _require_non_empty_text(self.name, field_name="name").strip())
        object.__setattr__(
            self,
            "description",
            _require_non_empty_text(self.description, field_name="description").strip(),
        )
        object.__setattr__(
            self,
            "loading_source",
            _require_non_empty_text(self.loading_source, field_name="loading_source").strip(),
        )
        object.__setattr__(self, "content", _require_non_empty_text(self.content, field_name="content"))

    @property
    def constitution_version(self) -> str:
        """Return the authoritative version identifier used in decision lineage."""
        return self.version.value


class ConstitutionLoader:
    """Loads the single approved Value constitution from this repository."""

    _VERSION = ConstitutionVersion("value-v1.0.0")
    _SOURCE = "docs/value-manager-constitution.md"

    @classmethod
    def load_value_manager_constitution(cls) -> ValueManagerConstitution:
        """Return the approved repository artifact without parsing its methodology."""
        source_path = Path(__file__).resolve().parents[3] / cls._SOURCE
        try:
            content = source_path.read_text(encoding="utf-8")
        except OSError as error:
            raise ValueError(f"unable to load Value Manager constitution from {cls._SOURCE}") from error
        return ValueManagerConstitution(
            version=cls._VERSION,
            manager_type=_VALUE_MANAGER_TYPE,
            name="Value Manager Constitution",
            description="Approved methodology for the first Value Manager.",
            loading_source=cls._SOURCE,
            content=content,
        )
