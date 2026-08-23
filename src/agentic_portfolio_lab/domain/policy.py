"""Typed manager-risk policy artifacts and immutable evaluation inputs.

Lane 1 establishes typed, hashable policy objects and deterministic evidence
coverage/snapshot inputs without activating manager-specific validation in the
production workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
import re
import unicodedata

from .constitution import ConstitutionLoader, ConstitutionVersion, ValueManagerConstitution
from .portfolio import (
    Portfolio,
    SecurityIdentity,
    _calculate_decimal,
    _calculate_informational_decimal,
    _canonical_upper_text,
    _require_aware_datetime,
    _require_non_empty_text,
)
from .provider_fundamentals import FreshnessClass, ProviderEndpoint, ReliabilityClass, ReuseStatus
from .research import DerivedMetric, EvidenceItem, MissingData, PacketComponentCoverage, ResearchPacket
from .valuation import PortfolioValuation, PriceObservation

_SEMANTIC_VERSION_PATTERN = re.compile(r"^[a-z][a-z0-9-]*-v[0-9]+\.[0-9]+\.[0-9]+$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_POLICY_SCHEMA_VERSION = "policy-domain.v1"
_CURRENT_POLICY_KIND = "CURRENT"
_LEGACY_POLICY_KIND = "LEGACY_MECHANICAL"
_VALUE_MANAGER_TYPE = "VALUE"
_SYSTEM_SAFETY_NAMESPACE = "system-safety"
_LEGACY_PRESENTATION_IDENTITY = "legacy-mechanical-v0.1.0"
_HASH_EXCLUDED_FIELDS = frozenset({"loading_source", "content_hash"})
_BASELINE_ALLOWED_REUSE = (ReuseStatus.FETCHED_THIS_CYCLE, ReuseStatus.REUSED_CURRENT)
_BASELINE_DERIVED_METRIC_IDS = (
    "net_debt",
    "current_ratio",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "fcf",
    "ttm_ocf",
    "ttm_capex",
    "ttm_fcf",
    "ttm_net_income",
    "ttm_revenue",
    "cash_conversion",
    "share_count_change",
    "market_cap",
    "enterprise_value",
    "fcf_yield",
)


def _require_finite_decimal(value: Decimal, *, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return Decimal("0") if value.is_zero() else value


def _require_fractional_weight(value: Decimal, *, field_name: str, allow_zero: bool = True) -> Decimal:
    value = _require_finite_decimal(value, field_name=field_name)
    lower_bound = Decimal("0") if allow_zero else Decimal("0.00000000000000000001")
    if value < lower_bound:
        raise ValueError(f"{field_name} must not be negative")
    if value > Decimal("1"):
        raise ValueError(f"{field_name} must be less than or equal to 1")
    if not allow_zero and value.is_zero():
        raise ValueError(f"{field_name} must be greater than zero")
    return value


def _require_sha256_hex(value: str, *, field_name: str) -> str:
    value = _require_non_empty_text(value, field_name=field_name).strip()
    if not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must be a 64-character lowercase hexadecimal SHA-256 digest")
    return value


def _normalize_scalar_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = unicodedata.normalize("NFC", value)
    if any(0xD800 <= ord(character) <= 0xDFFF for character in normalized):
        raise ValueError(f"{field_name} must not contain surrogate code points")
    return normalized


def _canonical_decimal_string(value: Decimal) -> str:
    value = _require_finite_decimal(value, field_name="Decimal value")
    if value.is_zero():
        return "0"
    sign, digits, exponent = value.as_tuple()
    digits_list = list(digits)
    while digits_list and digits_list[-1] == 0:
        digits_list.pop()
        exponent += 1
    digit_text = "".join(str(digit) for digit in digits_list) or "0"
    if exponent >= 0:
        integer = digit_text + ("0" * exponent)
        result = integer.lstrip("0") or "0"
    else:
        split = len(digit_text) + exponent
        if split > 0:
            integer = digit_text[:split]
            fraction = digit_text[split:]
        else:
            integer = "0"
            fraction = ("0" * (-split)) + digit_text
        integer = integer.lstrip("0") or "0"
        fraction = fraction.rstrip("0")
        result = integer if not fraction else f"{integer}.{fraction}"
    return f"-{result}" if sign else result


def _normalize_sequence(
    value: tuple[object, ...] | list[object],
    *,
    field_name: str,
    require_items: bool = False,
) -> tuple[object, ...]:
    if not isinstance(value, (tuple, list)):
        raise TypeError(f"{field_name} must be a tuple or list")
    normalized = tuple(value)
    if require_items and not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _normalize_optional_identity_component(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _canonical_upper_text(value, field_name=field_name)


def _canonicalize_json_value(value: object, *, for_hash: bool) -> object:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _normalize_scalar_text(value, field_name="JSON string")
    if isinstance(value, Decimal):
        return _canonical_decimal_string(value)
    if isinstance(value, StrEnum):
        return _normalize_scalar_text(value.value, field_name="enum value")
    if isinstance(value, int):
        return value
    if isinstance(value, tuple):
        return [_canonicalize_json_value(item, for_hash=for_hash) for item in value]
    if isinstance(value, list):
        return [_canonicalize_json_value(item, for_hash=for_hash) for item in value]
    if hasattr(value, "artifact_payload") and callable(value.artifact_payload):
        return _canonicalize_json_value(value.artifact_payload(for_hash=for_hash), for_hash=for_hash)
    if hasattr(value, "__dataclass_fields__"):
        payload: dict[str, object] = {}
        for field_name in value.__dataclass_fields__:  # type: ignore[attr-defined]
            if for_hash and field_name in _HASH_EXCLUDED_FIELDS:
                continue
            normalized_name = _normalize_scalar_text(field_name, field_name="JSON object key")
            payload[normalized_name] = _canonicalize_json_value(getattr(value, field_name), for_hash=for_hash)
        return dict(sorted(payload.items(), key=lambda item: item[0]))
    if isinstance(value, dict):
        normalized_items: list[tuple[str, object]] = []
        for key, nested_value in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            normalized_key = _normalize_scalar_text(key, field_name="JSON object key")
            normalized_items.append((normalized_key, _canonicalize_json_value(nested_value, for_hash=for_hash)))
        normalized_items.sort(key=lambda item: item[0])
        return dict(normalized_items)
    raise TypeError(f"unsupported canonical JSON value type: {type(value)!r}")


def canonical_policy_json_bytes(value: object, *, for_hash: bool = False) -> bytes:
    """Return canonical UTF-8 JSON bytes for one typed policy payload."""
    normalized = _canonicalize_json_value(value, for_hash=for_hash)
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def stable_policy_hash(value: object) -> str:
    """Return the lowercase SHA-256 hex digest for a canonical policy payload."""
    return hashlib.sha256(canonical_policy_json_bytes(value, for_hash=True)).hexdigest()


def _current_weight_for_security(valuation: PortfolioValuation, security: SecurityIdentity) -> Decimal:
    if valuation.total_value.is_zero():
        return Decimal("0")
    for position in valuation.position_valuations:
        if position.security == security:
            return _calculate_informational_decimal(lambda: position.market_value / valuation.total_value)
    return Decimal("0")


def _current_position_value_for_security(valuation: PortfolioValuation, security: SecurityIdentity) -> Decimal:
    for position in valuation.position_valuations:
        if position.security == security:
            return position.market_value
    return Decimal("0")


def _position_exists(portfolio: Portfolio, security: SecurityIdentity) -> bool:
    return any(position.security == security and position.quantity > 0 for position in portfolio.positions)


@dataclass(frozen=True, slots=True)
class RiskConstitutionVersion:
    value: str

    def __post_init__(self) -> None:
        value = _require_non_empty_text(self.value, field_name="risk_constitution_version").strip()
        if not _SEMANTIC_VERSION_PATTERN.fullmatch(value):
            raise ValueError("risk_constitution_version must use the form '<namespace>-v<major>.<minor>.<patch>'")
        object.__setattr__(self, "value", value)


@dataclass(frozen=True, slots=True)
class SystemSafetyEnvelopeVersion:
    value: str

    def __post_init__(self) -> None:
        value = _require_non_empty_text(self.value, field_name="system_safety_envelope_version").strip()
        if not _SEMANTIC_VERSION_PATTERN.fullmatch(value):
            raise ValueError("system_safety_envelope_version must use the form '<namespace>-v<major>.<minor>.<patch>'")
        if value.rsplit("-v", maxsplit=1)[0] != _SYSTEM_SAFETY_NAMESPACE:
            raise ValueError("system_safety_envelope_version must use the system-safety namespace")
        object.__setattr__(self, "value", value)


class EvidenceBand(StrEnum):
    BASELINE_RESEARCH_V2 = "BASELINE_RESEARCH_V2"
    ENHANCED_RESEARCH_UNDEFINED = "ENHANCED_RESEARCH_UNDEFINED"


class PositionSizingCase(StrEnum):
    INITIAL_POSITION = "INITIAL_POSITION"
    ADD_TO_POSITION = "ADD_TO_POSITION"


class PolicyReferenceKind(StrEnum):
    CURRENT = _CURRENT_POLICY_KIND
    LEGACY_MECHANICAL = _LEGACY_POLICY_KIND


@dataclass(frozen=True, slots=True)
class InvestmentConstitutionCompatibility:
    constitution_version: ConstitutionVersion
    content_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.constitution_version, ConstitutionVersion):
            raise TypeError("constitution_version must be a ConstitutionVersion")
        object.__setattr__(self, "content_hash", _require_sha256_hex(self.content_hash, field_name="content_hash"))


@dataclass(frozen=True, slots=True)
class InvestmentConstitutionArtifact:
    schema_version: str
    constitution_version: str
    manager_type: str
    name: str
    description: str
    content: str
    loading_source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_non_empty_text(self.schema_version, field_name="schema_version").strip())
        version = ConstitutionVersion(self.constitution_version)
        manager_type = _canonical_upper_text(self.manager_type, field_name="manager_type")
        if version.value.rsplit("-v", maxsplit=1)[0] != manager_type.lower():
            raise ValueError("constitution_version namespace must match manager_type")
        object.__setattr__(self, "constitution_version", version.value)
        object.__setattr__(self, "manager_type", manager_type)
        object.__setattr__(self, "name", _require_non_empty_text(self.name, field_name="name").strip())
        object.__setattr__(self, "description", _require_non_empty_text(self.description, field_name="description").strip())
        object.__setattr__(self, "content", _require_non_empty_text(self.content, field_name="content"))
        object.__setattr__(self, "loading_source", _require_non_empty_text(self.loading_source, field_name="loading_source").strip())

    def artifact_payload(self, *, for_hash: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "constitution_version": self.constitution_version,
            "manager_type": self.manager_type,
            "name": self.name,
            "description": self.description,
            "content": self.content,
        }
        if not for_hash:
            payload["loading_source"] = self.loading_source
        return payload

    @classmethod
    def from_value_manager_constitution(cls, constitution: ValueManagerConstitution) -> "InvestmentConstitutionArtifact":
        if not isinstance(constitution, ValueManagerConstitution):
            raise TypeError("constitution must be a ValueManagerConstitution")
        return cls(
            schema_version=_POLICY_SCHEMA_VERSION,
            constitution_version=constitution.constitution_version,
            manager_type=constitution.manager_type,
            name=constitution.name,
            description=constitution.description,
            content=constitution.content,
            loading_source=constitution.loading_source,
        )


@dataclass(frozen=True, slots=True)
class InvestmentConstitutionReference:
    constitution_version: str
    manager_type: str
    artifact: InvestmentConstitutionArtifact
    loading_source: str
    content_hash: str

    def __post_init__(self) -> None:
        version = ConstitutionVersion(self.constitution_version)
        if not isinstance(self.artifact, InvestmentConstitutionArtifact):
            raise TypeError("artifact must be an InvestmentConstitutionArtifact")
        if self.artifact.constitution_version != version.value:
            raise ValueError("artifact constitution_version must match constitution_version")
        manager_type = _canonical_upper_text(self.manager_type, field_name="manager_type")
        if self.artifact.manager_type != manager_type:
            raise ValueError("artifact manager_type must match manager_type")
        loading_source = _require_non_empty_text(self.loading_source, field_name="loading_source").strip()
        if self.artifact.loading_source != loading_source:
            raise ValueError("artifact loading_source must match loading_source")
        object.__setattr__(self, "constitution_version", version.value)
        object.__setattr__(self, "manager_type", manager_type)
        object.__setattr__(self, "loading_source", loading_source)
        object.__setattr__(self, "content_hash", _require_sha256_hex(self.content_hash, field_name="content_hash"))
        if self.content_hash != stable_policy_hash(self.artifact_payload(for_hash=True)):
            raise ValueError("content_hash must match the canonical investment constitution artifact hash")

    def artifact_payload(self, *, for_hash: bool = False) -> dict[str, object]:
        payload = self.artifact.artifact_payload(for_hash=for_hash)
        if not for_hash:
            payload["content_hash"] = self.content_hash
        return payload

    @classmethod
    def from_constitution(cls, constitution: ValueManagerConstitution) -> "InvestmentConstitutionReference":
        artifact = InvestmentConstitutionArtifact.from_value_manager_constitution(constitution)
        hash_value = stable_policy_hash(artifact.artifact_payload(for_hash=True))
        return cls(
            constitution_version=artifact.constitution_version,
            manager_type=artifact.manager_type,
            artifact=artifact,
            loading_source=artifact.loading_source,
            content_hash=hash_value,
        )


@dataclass(frozen=True, slots=True)
class SizingGuidance:
    typical_starter_weight_min: Decimal
    typical_starter_weight_max: Decimal
    minimum_cash_reserve: Decimal | None = None
    confidence_has_sizing_authority: bool = False

    def __post_init__(self) -> None:
        minimum = _require_fractional_weight(self.typical_starter_weight_min, field_name="typical_starter_weight_min")
        maximum = _require_fractional_weight(self.typical_starter_weight_max, field_name="typical_starter_weight_max")
        if maximum < minimum:
            raise ValueError("typical_starter_weight_max must be greater than or equal to typical_starter_weight_min")
        if not isinstance(self.confidence_has_sizing_authority, bool):
            raise TypeError("confidence_has_sizing_authority must be a bool")
        if self.minimum_cash_reserve is not None:
            object.__setattr__(
                self,
                "minimum_cash_reserve",
                _require_fractional_weight(self.minimum_cash_reserve, field_name="minimum_cash_reserve"),
            )


@dataclass(frozen=True, slots=True)
class SizingLimits:
    maximum_total_single_name_target_weight: Decimal
    maximum_one_cycle_add_weight: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "maximum_total_single_name_target_weight",
            _require_fractional_weight(
                self.maximum_total_single_name_target_weight,
                field_name="maximum_total_single_name_target_weight",
                allow_zero=False,
            ),
        )
        object.__setattr__(
            self,
            "maximum_one_cycle_add_weight",
            _require_fractional_weight(
                self.maximum_one_cycle_add_weight,
                field_name="maximum_one_cycle_add_weight",
                allow_zero=False,
            ),
        )


@dataclass(frozen=True, slots=True)
class EndpointCoverageRequirement:
    endpoint: ProviderEndpoint
    required_reliability: ReliabilityClass
    required_freshness: FreshnessClass

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint, ProviderEndpoint):
            raise TypeError("endpoint must be a ProviderEndpoint")
        if not isinstance(self.required_reliability, ReliabilityClass):
            raise TypeError("required_reliability must be a ReliabilityClass")
        if not isinstance(self.required_freshness, FreshnessClass):
            raise TypeError("required_freshness must be a FreshnessClass")


@dataclass(frozen=True, slots=True)
class EvidenceBandDefinition:
    band: EvidenceBand
    description: str
    reachable: bool
    maximum_initial_target_weight: Decimal
    required_endpoints: tuple[ProviderEndpoint, ...] | list[ProviderEndpoint]
    endpoint_requirements: tuple[EndpointCoverageRequirement, ...] | list[EndpointCoverageRequirement]
    required_metric_ids: tuple[str, ...] | list[str]
    allowed_reuse_statuses: tuple[ReuseStatus, ...] | list[ReuseStatus]
    exact_security_identity_required: bool = True
    required_metric_reliability: ReliabilityClass = ReliabilityClass.DERIVED_DETERMINISTIC
    required_metric_freshness: FreshnessClass = FreshnessClass.FRESH
    require_formula_id_match_metric_id: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.band, EvidenceBand):
            raise TypeError("band must be an EvidenceBand")
        object.__setattr__(self, "description", _require_non_empty_text(self.description, field_name="description").strip())
        if not isinstance(self.reachable, bool):
            raise TypeError("reachable must be a bool")
        if not isinstance(self.exact_security_identity_required, bool):
            raise TypeError("exact_security_identity_required must be a bool")
        if not isinstance(self.require_formula_id_match_metric_id, bool):
            raise TypeError("require_formula_id_match_metric_id must be a bool")
        object.__setattr__(
            self,
            "maximum_initial_target_weight",
            _require_fractional_weight(
                self.maximum_initial_target_weight,
                field_name="maximum_initial_target_weight",
                allow_zero=False,
            ),
        )
        endpoints = tuple(sorted(_normalize_sequence(self.required_endpoints, field_name="required_endpoints"), key=lambda item: item.value))
        if len(set(endpoints)) != len(endpoints):
            raise ValueError("required_endpoints must not contain duplicates")
        if not all(isinstance(endpoint, ProviderEndpoint) for endpoint in endpoints):
            raise TypeError("required_endpoints must contain ProviderEndpoint values")
        object.__setattr__(self, "required_endpoints", endpoints)
        requirements = tuple(
            sorted(
                _normalize_sequence(self.endpoint_requirements, field_name="endpoint_requirements"),
                key=lambda item: item.endpoint.value,
            )
        )
        if len(set(item.endpoint for item in requirements)) != len(requirements):
            raise ValueError("endpoint_requirements must not contain duplicate endpoints")
        if not all(isinstance(item, EndpointCoverageRequirement) for item in requirements):
            raise TypeError("endpoint_requirements must contain EndpointCoverageRequirement values")
        if tuple(item.endpoint for item in requirements) != endpoints:
            raise ValueError("endpoint_requirements must match required_endpoints exactly")
        object.__setattr__(self, "endpoint_requirements", requirements)
        metric_ids = tuple(
            sorted(
                _require_non_empty_text(metric_id, field_name="required_metric_ids item").strip()
                for metric_id in _normalize_sequence(self.required_metric_ids, field_name="required_metric_ids")
            )
        )
        if len(set(metric_ids)) != len(metric_ids):
            raise ValueError("required_metric_ids must not contain duplicates")
        object.__setattr__(self, "required_metric_ids", metric_ids)
        statuses = tuple(
            sorted(
                _normalize_sequence(self.allowed_reuse_statuses, field_name="allowed_reuse_statuses", require_items=True),
                key=lambda item: item.value,
            )
        )
        if len(set(statuses)) != len(statuses):
            raise ValueError("allowed_reuse_statuses must not contain duplicates")
        if not all(isinstance(status, ReuseStatus) for status in statuses):
            raise TypeError("allowed_reuse_statuses must contain ReuseStatus values")
        object.__setattr__(self, "allowed_reuse_statuses", statuses)
        if not isinstance(self.required_metric_reliability, ReliabilityClass):
            raise TypeError("required_metric_reliability must be a ReliabilityClass")
        if not isinstance(self.required_metric_freshness, FreshnessClass):
            raise TypeError("required_metric_freshness must be a FreshnessClass")


@dataclass(frozen=True, slots=True)
class CashDeploymentPolicy:
    minimum_cash_reserve: Decimal | None = None

    def __post_init__(self) -> None:
        if self.minimum_cash_reserve is not None:
            object.__setattr__(
                self,
                "minimum_cash_reserve",
                _require_fractional_weight(self.minimum_cash_reserve, field_name="minimum_cash_reserve"),
            )


@dataclass(frozen=True, slots=True)
class BalanceSheetPolicy:
    deterministic_leverage_threshold_enabled: bool = False
    deterministic_current_ratio_threshold_enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.deterministic_leverage_threshold_enabled, bool):
            raise TypeError("deterministic_leverage_threshold_enabled must be a bool")
        if not isinstance(self.deterministic_current_ratio_threshold_enabled, bool):
            raise TypeError("deterministic_current_ratio_threshold_enabled must be a bool")


@dataclass(frozen=True, slots=True)
class LiquidityPolicy:
    deterministic_threshold_enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.deterministic_threshold_enabled, bool):
            raise TypeError("deterministic_threshold_enabled must be a bool")


@dataclass(frozen=True, slots=True)
class DiversificationPolicy:
    universal_concentration_cap_below_full_weight: Decimal | None = None

    def __post_init__(self) -> None:
        if self.universal_concentration_cap_below_full_weight is not None:
            object.__setattr__(
                self,
                "universal_concentration_cap_below_full_weight",
                _require_fractional_weight(
                    self.universal_concentration_cap_below_full_weight,
                    field_name="universal_concentration_cap_below_full_weight",
                    allow_zero=False,
                ),
            )


@dataclass(frozen=True, slots=True)
class MissingDataPolicy:
    explicit_missing_data_required: bool = True
    interpret_missing_as_zero: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.explicit_missing_data_required, bool):
            raise TypeError("explicit_missing_data_required must be a bool")
        if not isinstance(self.interpret_missing_as_zero, bool):
            raise TypeError("interpret_missing_as_zero must be a bool")
        if self.explicit_missing_data_required and self.interpret_missing_as_zero:
            raise ValueError("MissingData must remain explicit and may not be interpreted as zero")


@dataclass(frozen=True, slots=True)
class ManagerRiskConstitution:
    schema_version: str
    risk_constitution_version: RiskConstitutionVersion
    manager_type: str
    compatible_investment_constitutions: tuple[InvestmentConstitutionCompatibility, ...] | list[InvestmentConstitutionCompatibility]
    sizing_guidance: SizingGuidance
    sizing_limits: SizingLimits
    evidence_bands: tuple[EvidenceBandDefinition, ...] | list[EvidenceBandDefinition]
    cash_deployment_policy: CashDeploymentPolicy
    balance_sheet_policy: BalanceSheetPolicy
    liquidity_policy: LiquidityPolicy
    diversification_policy: DiversificationPolicy
    missing_data_policy: MissingDataPolicy
    loading_source: str
    content_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_non_empty_text(self.schema_version, field_name="schema_version").strip())
        if not isinstance(self.risk_constitution_version, RiskConstitutionVersion):
            raise TypeError("risk_constitution_version must be a RiskConstitutionVersion")
        manager_type = _canonical_upper_text(self.manager_type, field_name="manager_type")
        if self.risk_constitution_version.value.rsplit("-v", maxsplit=1)[0] != f"{manager_type.lower()}-risk":
            raise ValueError("risk_constitution_version namespace must match manager_type")
        compatible = tuple(
            sorted(
                _normalize_sequence(
                    self.compatible_investment_constitutions,
                    field_name="compatible_investment_constitutions",
                    require_items=True,
                ),
                key=lambda item: (item.constitution_version.value, item.content_hash),
            )
        )
        if not all(isinstance(item, InvestmentConstitutionCompatibility) for item in compatible):
            raise TypeError("compatible_investment_constitutions must contain InvestmentConstitutionCompatibility values")
        seen_compatibility = {(item.constitution_version.value, item.content_hash) for item in compatible}
        if len(seen_compatibility) != len(compatible):
            raise ValueError("compatible_investment_constitutions must not contain duplicates")
        object.__setattr__(self, "compatible_investment_constitutions", compatible)
        if not isinstance(self.sizing_guidance, SizingGuidance):
            raise TypeError("sizing_guidance must be a SizingGuidance")
        if not isinstance(self.sizing_limits, SizingLimits):
            raise TypeError("sizing_limits must be a SizingLimits")
        bands = tuple(
            sorted(
                _normalize_sequence(self.evidence_bands, field_name="evidence_bands", require_items=True),
                key=lambda item: item.band.value,
            )
        )
        if not all(isinstance(item, EvidenceBandDefinition) for item in bands):
            raise TypeError("evidence_bands must contain EvidenceBandDefinition values")
        band_ids = tuple(item.band for item in bands)
        if len(set(band_ids)) != len(bands):
            raise ValueError("evidence_bands must not contain duplicate bands")
        object.__setattr__(self, "evidence_bands", bands)
        for field_name, field_type in (
            ("cash_deployment_policy", CashDeploymentPolicy),
            ("balance_sheet_policy", BalanceSheetPolicy),
            ("liquidity_policy", LiquidityPolicy),
            ("diversification_policy", DiversificationPolicy),
            ("missing_data_policy", MissingDataPolicy),
        ):
            if not isinstance(getattr(self, field_name), field_type):
                raise TypeError(f"{field_name} must be a {field_type.__name__}")
        object.__setattr__(self, "manager_type", manager_type)
        object.__setattr__(self, "loading_source", _require_non_empty_text(self.loading_source, field_name="loading_source").strip())
        computed_hash = stable_policy_hash(self.artifact_payload(for_hash=True))
        if self.content_hash is None:
            object.__setattr__(self, "content_hash", computed_hash)
        else:
            object.__setattr__(self, "content_hash", _require_sha256_hex(self.content_hash, field_name="content_hash"))
            if self.content_hash != computed_hash:
                raise ValueError("content_hash must match the canonical ManagerRiskConstitution artifact hash")

    def artifact_payload(self, *, for_hash: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "risk_constitution_version": self.risk_constitution_version.value,
            "manager_type": self.manager_type,
            "compatible_investment_constitutions": tuple(
                {
                    "constitution_version": item.constitution_version.value,
                    "content_hash": item.content_hash,
                }
                for item in self.compatible_investment_constitutions
            ),
            "sizing_guidance": self.sizing_guidance,
            "sizing_limits": self.sizing_limits,
            "evidence_bands": self.evidence_bands,
            "cash_deployment_policy": self.cash_deployment_policy,
            "balance_sheet_policy": self.balance_sheet_policy,
            "liquidity_policy": self.liquidity_policy,
            "diversification_policy": self.diversification_policy,
            "missing_data_policy": self.missing_data_policy,
        }
        if not for_hash:
            payload["loading_source"] = self.loading_source
            payload["content_hash"] = self.content_hash
        return payload

    def compatible_with(self, constitution: InvestmentConstitutionReference) -> bool:
        if not isinstance(constitution, InvestmentConstitutionReference):
            raise TypeError("constitution must be an InvestmentConstitutionReference")
        if constitution.manager_type != self.manager_type:
            return False
        return any(
            item.constitution_version.value == constitution.constitution_version and item.content_hash == constitution.content_hash
            for item in self.compatible_investment_constitutions
        )

    def require_compatible(self, constitution: InvestmentConstitutionReference) -> None:
        if not self.compatible_with(constitution):
            raise ValueError("investment constitution is not compatible with this manager risk constitution")


@dataclass(frozen=True, slots=True)
class IdentityAndCurrencyPolicy:
    require_exact_security_identity: bool = True
    require_currency_match: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.require_exact_security_identity, bool):
            raise TypeError("require_exact_security_identity must be a bool")
        if not isinstance(self.require_currency_match, bool):
            raise TypeError("require_currency_match must be a bool")


@dataclass(frozen=True, slots=True)
class ChronologyAndProvenancePolicy:
    require_attributable_prices: bool = True
    forbid_future_dated_inputs: bool = True
    require_timezone_aware_timestamps: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "require_attributable_prices",
            "forbid_future_dated_inputs",
            "require_timezone_aware_timestamps",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")


@dataclass(frozen=True, slots=True)
class CashAndArithmeticPolicy:
    require_cash_feasibility: bool = True
    require_non_negative_state: bool = True
    require_positive_executable_quantity: bool = True
    decimal_safe_arithmetic: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "require_cash_feasibility",
            "require_non_negative_state",
            "require_positive_executable_quantity",
            "decimal_safe_arithmetic",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")


@dataclass(frozen=True, slots=True)
class ApprovalAndExecutionPolicy:
    human_approval_required: bool = True
    hold_never_executes: bool = True
    failed_validation_never_executes: bool = True
    rejected_or_expired_never_execute: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "human_approval_required",
            "hold_never_executes",
            "failed_validation_never_executes",
            "rejected_or_expired_never_execute",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")


@dataclass(frozen=True, slots=True)
class LineagePolicy:
    preserve_immutable_lineage: bool = True
    separate_managed_and_benchmark: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.preserve_immutable_lineage, bool):
            raise TypeError("preserve_immutable_lineage must be a bool")
        if not isinstance(self.separate_managed_and_benchmark, bool):
            raise TypeError("separate_managed_and_benchmark must be a bool")


@dataclass(frozen=True, slots=True)
class SystemSafetyEnvelope:
    schema_version: str
    system_safety_envelope_version: SystemSafetyEnvelopeVersion
    supported_actions: tuple[str, ...] | list[str]
    supported_security_types: tuple[str, ...] | list[str]
    prohibited_mechanics: tuple[str, ...] | list[str]
    identity_and_currency_policy: IdentityAndCurrencyPolicy
    chronology_and_provenance_policy: ChronologyAndProvenancePolicy
    cash_and_arithmetic_policy: CashAndArithmeticPolicy
    approval_and_execution_policy: ApprovalAndExecutionPolicy
    lineage_policy: LineagePolicy
    loading_source: str
    content_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_non_empty_text(self.schema_version, field_name="schema_version").strip())
        if not isinstance(self.system_safety_envelope_version, SystemSafetyEnvelopeVersion):
            raise TypeError("system_safety_envelope_version must be a SystemSafetyEnvelopeVersion")
        object.__setattr__(self, "supported_actions", self._normalize_text_items(self.supported_actions, field_name="supported_actions"))
        object.__setattr__(
            self,
            "supported_security_types",
            self._normalize_text_items(self.supported_security_types, field_name="supported_security_types"),
        )
        object.__setattr__(
            self,
            "prohibited_mechanics",
            self._normalize_text_items(self.prohibited_mechanics, field_name="prohibited_mechanics"),
        )
        for field_name, field_type in (
            ("identity_and_currency_policy", IdentityAndCurrencyPolicy),
            ("chronology_and_provenance_policy", ChronologyAndProvenancePolicy),
            ("cash_and_arithmetic_policy", CashAndArithmeticPolicy),
            ("approval_and_execution_policy", ApprovalAndExecutionPolicy),
            ("lineage_policy", LineagePolicy),
        ):
            if not isinstance(getattr(self, field_name), field_type):
                raise TypeError(f"{field_name} must be a {field_type.__name__}")
        object.__setattr__(self, "loading_source", _require_non_empty_text(self.loading_source, field_name="loading_source").strip())
        computed_hash = stable_policy_hash(self.artifact_payload(for_hash=True))
        if self.content_hash is None:
            object.__setattr__(self, "content_hash", computed_hash)
        else:
            object.__setattr__(self, "content_hash", _require_sha256_hex(self.content_hash, field_name="content_hash"))
            if self.content_hash != computed_hash:
                raise ValueError("content_hash must match the canonical SystemSafetyEnvelope artifact hash")

    @staticmethod
    def _normalize_text_items(value: tuple[str, ...] | list[str], *, field_name: str) -> tuple[str, ...]:
        items = tuple(
            sorted(
                _require_non_empty_text(item, field_name=f"{field_name} item").strip()
                for item in _normalize_sequence(value, field_name=field_name, require_items=True)
            )
        )
        if len(set(items)) != len(items):
            raise ValueError(f"{field_name} must not contain duplicates")
        return items

    def artifact_payload(self, *, for_hash: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "system_safety_envelope_version": self.system_safety_envelope_version.value,
            "supported_actions": self.supported_actions,
            "supported_security_types": self.supported_security_types,
            "prohibited_mechanics": self.prohibited_mechanics,
            "identity_and_currency_policy": self.identity_and_currency_policy,
            "chronology_and_provenance_policy": self.chronology_and_provenance_policy,
            "cash_and_arithmetic_policy": self.cash_and_arithmetic_policy,
            "approval_and_execution_policy": self.approval_and_execution_policy,
            "lineage_policy": self.lineage_policy,
        }
        if not for_hash:
            payload["loading_source"] = self.loading_source
            payload["content_hash"] = self.content_hash
        return payload


@dataclass(frozen=True, slots=True)
class AssessedEvidenceBand:
    band: EvidenceBand
    reachable: bool
    maximum_initial_target_weight: Decimal
    eligible: bool
    disqualifications: tuple[str, ...] | list[str] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.band, EvidenceBand):
            raise TypeError("band must be an EvidenceBand")
        if not isinstance(self.reachable, bool):
            raise TypeError("reachable must be a bool")
        if not isinstance(self.eligible, bool):
            raise TypeError("eligible must be a bool")
        object.__setattr__(
            self,
            "maximum_initial_target_weight",
            _require_fractional_weight(
                self.maximum_initial_target_weight,
                field_name="maximum_initial_target_weight",
                allow_zero=False,
            ),
        )
        disqualifications = tuple(
            _require_non_empty_text(item, field_name="disqualifications item").strip()
            for item in _normalize_sequence(self.disqualifications, field_name="disqualifications")
        )
        object.__setattr__(self, "disqualifications", disqualifications)
        if self.eligible and disqualifications:
            raise ValueError("eligible evidence bands must not contain disqualifications")


def _assess_evidence_bands(
    *,
    security: SecurityIdentity,
    packet_ticker: str,
    packet_security_type: str,
    packet_exchange: str | None,
    packet_currency: str | None,
    endpoint_coverage: tuple[PacketComponentCoverage, ...],
    derived_metrics: tuple[DerivedMetric, ...],
    band_definitions: tuple[EvidenceBandDefinition, ...],
) -> tuple[bool, tuple[AssessedEvidenceBand, ...]]:
    exact_identity_match = (
        packet_ticker == security.ticker
        and packet_security_type == security.security_type
        and packet_exchange == security.exchange
        and packet_currency == security.currency
    )
    coverage_by_endpoint = {item.endpoint: item for item in endpoint_coverage}
    metrics_by_id = {metric.metric_id: metric for metric in derived_metrics}
    metric_id_set = set(metrics_by_id)
    assessed_bands: list[AssessedEvidenceBand] = []
    for definition in band_definitions:
        reasons: list[str] = []
        if definition.exact_security_identity_required and not exact_identity_match:
            reasons.append("exact SecurityIdentity match is required")
        endpoint_requirements = {item.endpoint: item for item in definition.endpoint_requirements}
        for endpoint in definition.required_endpoints:
            record = coverage_by_endpoint.get(endpoint)
            if record is None:
                reasons.append(f"missing {endpoint.value} coverage")
                continue
            if record.reuse_status not in definition.allowed_reuse_statuses:
                reasons.append(f"{endpoint.value} coverage is not current")
            requirement = endpoint_requirements[endpoint]
            if record.freshness is not requirement.required_freshness:
                reasons.append(f"{endpoint.value} freshness does not match the baseline contract")
            if record.reliability is not requirement.required_reliability:
                reasons.append(f"{endpoint.value} reliability does not match the baseline contract")
        expected_metric_ids = set(definition.required_metric_ids)
        if metric_id_set != expected_metric_ids:
            missing_metric_ids = expected_metric_ids - metric_id_set
            extra_metric_ids = metric_id_set - expected_metric_ids
            if missing_metric_ids:
                reasons.append("required derived metrics are missing")
            if extra_metric_ids:
                reasons.append("derived metrics include an unknown metric set")
        for metric_id in definition.required_metric_ids:
            metric = metrics_by_id.get(metric_id)
            if metric is None:
                continue
            if metric.reliability is not definition.required_metric_reliability:
                reasons.append(f"{metric_id} reliability does not match the baseline contract")
            if metric.freshness is not definition.required_metric_freshness:
                reasons.append(f"{metric_id} freshness does not match the baseline contract")
            if definition.require_formula_id_match_metric_id and metric.formula_id != metric.metric_id:
                reasons.append(f"{metric_id} formula identity does not match the baseline contract")
            if not metric.input_keys:
                reasons.append(f"{metric_id} lost input attribution")
            if isinstance(metric.value, MissingData):
                continue
            if not isinstance(metric.value, Decimal):
                reasons.append(f"{metric_id} must be Decimal or MissingData")
        assessed_bands.append(
            AssessedEvidenceBand(
                band=definition.band,
                reachable=definition.reachable,
                maximum_initial_target_weight=definition.maximum_initial_target_weight,
                eligible=definition.reachable and not reasons,
                disqualifications=tuple() if definition.reachable and not reasons else tuple(reasons),
            )
        )
    return exact_identity_match, tuple(assessed_bands)


@dataclass(frozen=True, slots=True)
class EvidenceCoverageAssessment:
    security: SecurityIdentity
    packet_id: str
    research_as_of_timestamp: datetime
    packet_ticker: str
    packet_security_type: str
    packet_exchange: str | None
    packet_currency: str | None
    exact_security_identity_match: bool
    evidence_items: tuple[EvidenceItem, ...] | list[EvidenceItem]
    endpoint_coverage: tuple[PacketComponentCoverage, ...] | list[PacketComponentCoverage]
    derived_metrics: tuple[DerivedMetric, ...] | list[DerivedMetric]
    band_definitions: tuple[EvidenceBandDefinition, ...] | list[EvidenceBandDefinition]
    assessed_bands: tuple[AssessedEvidenceBand, ...] | list[AssessedEvidenceBand]

    def __post_init__(self) -> None:
        if not isinstance(self.security, SecurityIdentity):
            raise TypeError("security must be a SecurityIdentity")
        object.__setattr__(self, "packet_id", _require_non_empty_text(self.packet_id, field_name="packet_id").strip())
        _require_aware_datetime(self.research_as_of_timestamp, field_name="research_as_of_timestamp")
        if not isinstance(self.exact_security_identity_match, bool):
            raise TypeError("exact_security_identity_match must be a bool")
        object.__setattr__(self, "packet_ticker", _canonical_upper_text(self.packet_ticker, field_name="packet_ticker"))
        object.__setattr__(
            self,
            "packet_security_type",
            _canonical_upper_text(self.packet_security_type, field_name="packet_security_type"),
        )
        object.__setattr__(
            self,
            "packet_exchange",
            _normalize_optional_identity_component(self.packet_exchange, field_name="packet_exchange"),
        )
        object.__setattr__(
            self,
            "packet_currency",
            _normalize_optional_identity_component(self.packet_currency, field_name="packet_currency"),
        )
        evidence_items = _normalize_sequence(self.evidence_items, field_name="evidence_items", require_items=True)
        if not all(isinstance(item, EvidenceItem) for item in evidence_items):
            raise TypeError("evidence_items must contain EvidenceItem values")
        evidence_ids = tuple(item.evidence_id for item in evidence_items)
        if len(set(evidence_ids)) != len(evidence_items):
            raise ValueError("evidence_items must not contain duplicate evidence_id values")
        object.__setattr__(self, "evidence_items", evidence_items)
        endpoints = _normalize_sequence(self.endpoint_coverage, field_name="endpoint_coverage")
        if not all(isinstance(item, PacketComponentCoverage) for item in endpoints):
            raise TypeError("endpoint_coverage must contain PacketComponentCoverage values")
        endpoint_ids = tuple(item.endpoint for item in endpoints)
        if len(set(endpoint_ids)) != len(endpoints):
            raise ValueError("endpoint_coverage must not contain duplicate endpoints")
        object.__setattr__(self, "endpoint_coverage", endpoints)
        metrics = _normalize_sequence(self.derived_metrics, field_name="derived_metrics")
        if not all(isinstance(item, DerivedMetric) for item in metrics):
            raise TypeError("derived_metrics must contain DerivedMetric values")
        metric_ids = tuple(item.metric_id for item in metrics)
        if len(set(metric_ids)) != len(metrics):
            raise ValueError("derived_metrics must not contain duplicate metric_id values")
        object.__setattr__(self, "derived_metrics", metrics)
        definitions = tuple(
            sorted(
                _normalize_sequence(self.band_definitions, field_name="band_definitions", require_items=True),
                key=lambda item: item.band.value,
            )
        )
        if not all(isinstance(item, EvidenceBandDefinition) for item in definitions):
            raise TypeError("band_definitions must contain EvidenceBandDefinition values")
        if len(set(item.band for item in definitions)) != len(definitions):
            raise ValueError("band_definitions must not contain duplicate bands")
        object.__setattr__(self, "band_definitions", definitions)
        bands = _normalize_sequence(self.assessed_bands, field_name="assessed_bands", require_items=True)
        if not all(isinstance(item, AssessedEvidenceBand) for item in bands):
            raise TypeError("assessed_bands must contain AssessedEvidenceBand values")
        band_ids = tuple(item.band for item in bands)
        if len(set(band_ids)) != len(bands):
            raise ValueError("assessed_bands must not contain duplicate bands")
        expected_identity, expected_bands = _assess_evidence_bands(
            security=self.security,
            packet_ticker=self.packet_ticker,
            packet_security_type=self.packet_security_type,
            packet_exchange=self.packet_exchange,
            packet_currency=self.packet_currency,
            endpoint_coverage=endpoints,
            derived_metrics=metrics,
            band_definitions=definitions,
        )
        if self.exact_security_identity_match != expected_identity:
            raise ValueError("exact_security_identity_match must be derived from the retained packet identity")
        if tuple(bands) != expected_bands:
            raise ValueError("assessed_bands must match the retained packet evidence and band definitions")
        object.__setattr__(self, "assessed_bands", tuple(bands))

    @property
    def eligible_band(self) -> EvidenceBand | None:
        eligible = tuple(item.band for item in self.assessed_bands if item.eligible)
        if not eligible:
            return None
        if len(eligible) > 1:
            raise ValueError("exactly one eligible evidence band is expected in Lane 1")
        return eligible[0]

    @property
    def baseline_qualified(self) -> bool:
        return any(item.band is EvidenceBand.BASELINE_RESEARCH_V2 and item.eligible for item in self.assessed_bands)

    @classmethod
    def evaluate(
        cls,
        packet: ResearchPacket,
        *,
        security: SecurityIdentity,
        band_definitions: tuple[EvidenceBandDefinition, ...] | list[EvidenceBandDefinition],
    ) -> "EvidenceCoverageAssessment":
        if not isinstance(packet, ResearchPacket):
            raise TypeError("packet must be a ResearchPacket")
        if not isinstance(security, SecurityIdentity):
            raise TypeError("security must be a SecurityIdentity")
        definitions = tuple(
            sorted(
                _normalize_sequence(band_definitions, field_name="band_definitions", require_items=True),
                key=lambda item: item.band.value,
            )
        )
        if not all(isinstance(item, EvidenceBandDefinition) for item in definitions):
            raise TypeError("band_definitions must contain EvidenceBandDefinition values")
        if packet.fundamentals is None:
            coverage: tuple[PacketComponentCoverage, ...] = ()
            metrics: tuple[DerivedMetric, ...] = ()
        else:
            coverage = packet.fundamentals.coverage
            metrics = packet.fundamentals.derived
        packet_exchange = None if isinstance(packet.exchange, MissingData) else packet.exchange
        packet_currency = None if isinstance(packet.currency, MissingData) else packet.currency
        exact_identity_match, assessed_bands = _assess_evidence_bands(
            security=security,
            packet_ticker=packet.ticker,
            packet_security_type=packet.security_type,
            packet_exchange=packet_exchange,
            packet_currency=packet_currency,
            endpoint_coverage=coverage,
            derived_metrics=metrics,
            band_definitions=definitions,
        )
        return cls(
            security=security,
            packet_id=packet.packet_id,
            research_as_of_timestamp=packet.as_of_timestamp,
            packet_ticker=packet.ticker,
            packet_security_type=packet.security_type,
            packet_exchange=packet_exchange,
            packet_currency=packet_currency,
            exact_security_identity_match=exact_identity_match,
            evidence_items=packet.evidence_items,
            endpoint_coverage=coverage,
            derived_metrics=metrics,
            band_definitions=definitions,
            assessed_bands=assessed_bands,
        )


@dataclass(frozen=True, slots=True)
class RiskEvaluationSnapshot:
    portfolio: Portfolio
    valuation: PortfolioValuation
    security: SecurityIdentity
    price_observation: PriceObservation
    evidence_coverage: EvidenceCoverageAssessment
    current_position_weight: Decimal
    current_cash_weight: Decimal
    proposed_target_weight: Decimal
    proposed_post_trade_weight: Decimal
    proposed_weight_delta: Decimal
    proposed_post_trade_position_value: Decimal
    proposed_post_trade_cash_weight: Decimal
    proposed_post_trade_cash_value: Decimal
    position_sizing_case: PositionSizingCase

    def __post_init__(self) -> None:
        if not isinstance(self.portfolio, Portfolio):
            raise TypeError("portfolio must be a Portfolio")
        if not isinstance(self.valuation, PortfolioValuation):
            raise TypeError("valuation must be a PortfolioValuation")
        if self.valuation.subject_id != self.portfolio.portfolio_id:
            raise ValueError("valuation subject_id must match portfolio_id")
        if self.valuation.currency != self.portfolio.base_currency:
            raise ValueError("valuation currency must match portfolio base_currency")
        if not isinstance(self.security, SecurityIdentity):
            raise TypeError("security must be a SecurityIdentity")
        if self.security.currency != self.portfolio.base_currency:
            raise ValueError("security currency must match portfolio base_currency")
        if not isinstance(self.price_observation, PriceObservation):
            raise TypeError("price_observation must be a PriceObservation")
        if self.price_observation.security != self.security:
            raise ValueError("price_observation security must match security")
        if self.price_observation.currency != self.valuation.currency:
            raise ValueError("price_observation currency must match valuation currency")
        if self.price_observation.source_provider_identity != self.valuation.source_provider_identity:
            raise ValueError("price_observation provider must match valuation provider")
        if self.price_observation.market_date != self.valuation.market_date:
            raise ValueError("price_observation market_date must match valuation market_date")
        if self.price_observation.observed_at != self.valuation.source_price_timestamp:
            raise ValueError("price_observation observed_at must match valuation source_price_timestamp")
        if self.price_observation.price_convention != self.valuation.price_convention:
            raise ValueError("price_observation price_convention must match valuation price_convention")
        if not isinstance(self.evidence_coverage, EvidenceCoverageAssessment):
            raise TypeError("evidence_coverage must be an EvidenceCoverageAssessment")
        if self.evidence_coverage.security != self.security:
            raise ValueError("evidence_coverage security must match security")
        if self.evidence_coverage.research_as_of_timestamp > self.valuation.as_of_timestamp:
            raise ValueError("evidence_coverage research_as_of_timestamp must not be after valuation as_of_timestamp")
        portfolio_positions = {position.security: position for position in self.portfolio.positions}
        valuation_positions = {position.security: position for position in self.valuation.position_valuations}
        if set(portfolio_positions) != set(valuation_positions):
            raise ValueError("valuation positions must match portfolio positions exactly")
        for security_identity, position in portfolio_positions.items():
            valuation_position = valuation_positions[security_identity]
            if valuation_position.quantity != position.quantity:
                raise ValueError("valuation position quantities must match portfolio positions")
            if valuation_position.total_cost_basis != position.total_cost_basis:
                raise ValueError("valuation total_cost_basis must match portfolio positions")
        if self.valuation.cash_value != self.portfolio.cash_balance.amount:
            raise ValueError("valuation cash_value must match portfolio cash_balance")
        valuation_position = valuation_positions.get(self.security)
        if valuation_position is not None and valuation_position.observed_price != self.price_observation.observed_price:
            raise ValueError("price_observation observed_price must match the synchronized valuation price")
        current_weight = _require_fractional_weight(self.current_position_weight, field_name="current_position_weight")
        expected_current_weight = _current_weight_for_security(self.valuation, self.security)
        if current_weight != expected_current_weight:
            raise ValueError("current_position_weight must match the synchronized valuation weight")
        current_cash_weight = _require_fractional_weight(self.current_cash_weight, field_name="current_cash_weight")
        expected_cash_weight = (
            Decimal("0")
            if self.valuation.total_value.is_zero()
            else _calculate_informational_decimal(lambda: self.valuation.cash_value / self.valuation.total_value)
        )
        if current_cash_weight != expected_cash_weight:
            raise ValueError("current_cash_weight must match the synchronized valuation cash weight")
        proposed_target_weight = _require_fractional_weight(
            self.proposed_target_weight,
            field_name="proposed_target_weight",
            allow_zero=False,
        )
        proposed_post_trade_weight = _require_fractional_weight(
            self.proposed_post_trade_weight,
            field_name="proposed_post_trade_weight",
            allow_zero=False,
        )
        if proposed_post_trade_weight != proposed_target_weight:
            raise ValueError("proposed_post_trade_weight must equal proposed_target_weight in Lane 1")
        proposed_weight_delta = _require_finite_decimal(self.proposed_weight_delta, field_name="proposed_weight_delta")
        expected_delta = _calculate_decimal(lambda: proposed_target_weight - current_weight)
        if proposed_weight_delta != expected_delta:
            raise ValueError("proposed_weight_delta must equal proposed_target_weight minus current_position_weight")
        proposed_position_value = _require_finite_decimal(
            self.proposed_post_trade_position_value,
            field_name="proposed_post_trade_position_value",
        )
        expected_position_value = _calculate_decimal(lambda: self.valuation.total_value * proposed_target_weight)
        if proposed_position_value != expected_position_value:
            raise ValueError("proposed_post_trade_position_value must equal total_value multiplied by target weight")
        proposed_cash_value = _require_finite_decimal(self.proposed_post_trade_cash_value, field_name="proposed_post_trade_cash_value")
        current_position_value = _current_position_value_for_security(self.valuation, self.security)
        expected_cash_value = _calculate_decimal(
            lambda: self.valuation.cash_value - (proposed_position_value - current_position_value)
        )
        if proposed_cash_value != expected_cash_value:
            raise ValueError("proposed_post_trade_cash_value must reflect the target-weight delta against current cash")
        proposed_cash_weight = _require_finite_decimal(
            self.proposed_post_trade_cash_weight,
            field_name="proposed_post_trade_cash_weight",
        )
        expected_cash_weight_after = (
            Decimal("0")
            if self.valuation.total_value.is_zero()
            else _calculate_informational_decimal(lambda: proposed_cash_value / self.valuation.total_value)
        )
        if proposed_cash_weight != expected_cash_weight_after:
            raise ValueError("proposed_post_trade_cash_weight must equal proposed cash divided by total value")
        if not isinstance(self.position_sizing_case, PositionSizingCase):
            raise TypeError("position_sizing_case must be a PositionSizingCase")
        expected_case = (
            PositionSizingCase.ADD_TO_POSITION
            if _position_exists(self.portfolio, self.security)
            else PositionSizingCase.INITIAL_POSITION
        )
        if self.position_sizing_case is not expected_case:
            raise ValueError("position_sizing_case must match the synchronized portfolio state")

    @classmethod
    def from_state(
        cls,
        *,
        portfolio: Portfolio,
        valuation: PortfolioValuation,
        security: SecurityIdentity,
        price_observation: PriceObservation,
        evidence_coverage: EvidenceCoverageAssessment,
        proposed_target_weight: Decimal,
    ) -> "RiskEvaluationSnapshot":
        if not isinstance(portfolio, Portfolio):
            raise TypeError("portfolio must be a Portfolio")
        if not isinstance(valuation, PortfolioValuation):
            raise TypeError("valuation must be a PortfolioValuation")
        if not isinstance(security, SecurityIdentity):
            raise TypeError("security must be a SecurityIdentity")
        current_weight = _current_weight_for_security(valuation, security)
        current_cash_weight = (
            Decimal("0")
            if valuation.total_value.is_zero()
            else _calculate_informational_decimal(lambda: valuation.cash_value / valuation.total_value)
        )
        proposed_target_weight = _require_fractional_weight(
            proposed_target_weight,
            field_name="proposed_target_weight",
            allow_zero=False,
        )
        proposed_delta = _calculate_decimal(lambda: proposed_target_weight - current_weight)
        proposed_position_value = _calculate_decimal(lambda: valuation.total_value * proposed_target_weight)
        current_position_value = _current_position_value_for_security(valuation, security)
        proposed_cash_value = _calculate_decimal(lambda: valuation.cash_value - (proposed_position_value - current_position_value))
        proposed_cash_weight = (
            Decimal("0")
            if valuation.total_value.is_zero()
            else _calculate_informational_decimal(lambda: proposed_cash_value / valuation.total_value)
        )
        return cls(
            portfolio=portfolio,
            valuation=valuation,
            security=security,
            price_observation=price_observation,
            evidence_coverage=evidence_coverage,
            current_position_weight=current_weight,
            current_cash_weight=current_cash_weight,
            proposed_target_weight=proposed_target_weight,
            proposed_post_trade_weight=proposed_target_weight,
            proposed_weight_delta=proposed_delta,
            proposed_post_trade_position_value=proposed_position_value,
            proposed_post_trade_cash_weight=proposed_cash_weight,
            proposed_post_trade_cash_value=proposed_cash_value,
            position_sizing_case=(
                PositionSizingCase.ADD_TO_POSITION
                if _position_exists(portfolio, security)
                else PositionSizingCase.INITIAL_POSITION
            ),
        )


@dataclass(frozen=True, slots=True)
class LegacyPolicyReference:
    kind: PolicyReferenceKind = PolicyReferenceKind.LEGACY_MECHANICAL
    presentation_identity: str = _LEGACY_PRESENTATION_IDENTITY

    def __post_init__(self) -> None:
        if self.kind is not PolicyReferenceKind.LEGACY_MECHANICAL:
            raise ValueError("LegacyPolicyReference kind must be LEGACY_MECHANICAL")
        if self.presentation_identity != _LEGACY_PRESENTATION_IDENTITY:
            raise ValueError("LegacyPolicyReference presentation_identity must remain legacy-mechanical-v0.1.0")


@dataclass(frozen=True, slots=True)
class CurrentPolicyReference:
    investment_constitution: InvestmentConstitutionReference
    system_safety_envelope: SystemSafetyEnvelope
    manager_risk_constitution: ManagerRiskConstitution
    kind: PolicyReferenceKind = PolicyReferenceKind.CURRENT

    def __post_init__(self) -> None:
        if self.kind is not PolicyReferenceKind.CURRENT:
            raise ValueError("CurrentPolicyReference kind must be CURRENT")
        if not isinstance(self.investment_constitution, InvestmentConstitutionReference):
            raise TypeError("investment_constitution must be an InvestmentConstitutionReference")
        if not isinstance(self.system_safety_envelope, SystemSafetyEnvelope):
            raise TypeError("system_safety_envelope must be a SystemSafetyEnvelope")
        if not isinstance(self.manager_risk_constitution, ManagerRiskConstitution):
            raise TypeError("manager_risk_constitution must be a ManagerRiskConstitution")
        self.manager_risk_constitution.require_compatible(self.investment_constitution)
        if self.investment_constitution.manager_type != self.manager_risk_constitution.manager_type:
            raise ValueError("investment and manager risk constitutions must share the same manager_type")


class PolicyLoader:
    """Load the approved Lane 1 typed policy artifacts without activating them."""

    _SOURCE = "src/agentic_portfolio_lab/domain/policy.py"
    _VALUE_RISK_VERSION = RiskConstitutionVersion("value-risk-v1.0.0")
    _SYSTEM_SAFETY_VERSION = SystemSafetyEnvelopeVersion("system-safety-v1.0.0")

    @classmethod
    def load_value_manager_risk_constitution_v1(
        cls,
        *,
        compatible_investment_constitution: InvestmentConstitutionReference,
    ) -> ManagerRiskConstitution:
        if compatible_investment_constitution.manager_type != _VALUE_MANAGER_TYPE:
            raise ValueError("compatible investment constitution must belong to the VALUE manager")
        approved_investment_constitution = InvestmentConstitutionReference.from_constitution(
            ConstitutionLoader.load_value_manager_constitution()
        )
        if compatible_investment_constitution != approved_investment_constitution:
            raise ValueError("compatible investment constitution must match the single approved VALUE constitution artifact")
        return ManagerRiskConstitution(
            schema_version=_POLICY_SCHEMA_VERSION,
            risk_constitution_version=cls._VALUE_RISK_VERSION,
            manager_type=_VALUE_MANAGER_TYPE,
            compatible_investment_constitutions=(
                InvestmentConstitutionCompatibility(
                    constitution_version=ConstitutionVersion(approved_investment_constitution.constitution_version),
                    content_hash=approved_investment_constitution.content_hash,
                ),
            ),
            sizing_guidance=SizingGuidance(
                typical_starter_weight_min=Decimal("0.05"),
                typical_starter_weight_max=Decimal("0.10"),
                minimum_cash_reserve=None,
                confidence_has_sizing_authority=False,
            ),
            sizing_limits=SizingLimits(
                maximum_total_single_name_target_weight=Decimal("0.25"),
                maximum_one_cycle_add_weight=Decimal("0.05"),
            ),
            evidence_bands=(
                EvidenceBandDefinition(
                    band=EvidenceBand.BASELINE_RESEARCH_V2,
                    description="Current Research v2 baseline coverage.",
                    reachable=True,
                    maximum_initial_target_weight=Decimal("0.10"),
                    required_endpoints=(
                        ProviderEndpoint.OVERVIEW,
                        ProviderEndpoint.INCOME_STATEMENT,
                        ProviderEndpoint.BALANCE_SHEET,
                        ProviderEndpoint.CASH_FLOW,
                        ProviderEndpoint.EARNINGS,
                    ),
                    endpoint_requirements=(
                        EndpointCoverageRequirement(
                            endpoint=ProviderEndpoint.OVERVIEW,
                            required_reliability=ReliabilityClass.PROVIDER_COMPUTED,
                            required_freshness=FreshnessClass.FRESH,
                        ),
                        EndpointCoverageRequirement(
                            endpoint=ProviderEndpoint.INCOME_STATEMENT,
                            required_reliability=ReliabilityClass.PRIMARY_STATEMENT,
                            required_freshness=FreshnessClass.FRESH,
                        ),
                        EndpointCoverageRequirement(
                            endpoint=ProviderEndpoint.BALANCE_SHEET,
                            required_reliability=ReliabilityClass.PRIMARY_STATEMENT,
                            required_freshness=FreshnessClass.FRESH,
                        ),
                        EndpointCoverageRequirement(
                            endpoint=ProviderEndpoint.CASH_FLOW,
                            required_reliability=ReliabilityClass.PRIMARY_STATEMENT,
                            required_freshness=FreshnessClass.FRESH,
                        ),
                        EndpointCoverageRequirement(
                            endpoint=ProviderEndpoint.EARNINGS,
                            required_reliability=ReliabilityClass.PRIMARY_STATEMENT,
                            required_freshness=FreshnessClass.FRESH,
                        ),
                    ),
                    required_metric_ids=_BASELINE_DERIVED_METRIC_IDS,
                    allowed_reuse_statuses=_BASELINE_ALLOWED_REUSE,
                    exact_security_identity_required=True,
                    required_metric_reliability=ReliabilityClass.DERIVED_DETERMINISTIC,
                    required_metric_freshness=FreshnessClass.FRESH,
                    require_formula_id_match_metric_id=True,
                ),
                EvidenceBandDefinition(
                    band=EvidenceBand.ENHANCED_RESEARCH_UNDEFINED,
                    description="Reserved enhanced-evidence lane; unreachable until a later contract defines it.",
                    reachable=False,
                    maximum_initial_target_weight=Decimal("0.15"),
                    required_endpoints=(),
                    endpoint_requirements=(),
                    required_metric_ids=(),
                    allowed_reuse_statuses=_BASELINE_ALLOWED_REUSE,
                    exact_security_identity_required=True,
                    required_metric_reliability=ReliabilityClass.DERIVED_DETERMINISTIC,
                    required_metric_freshness=FreshnessClass.FRESH,
                    require_formula_id_match_metric_id=True,
                ),
            ),
            cash_deployment_policy=CashDeploymentPolicy(minimum_cash_reserve=None),
            balance_sheet_policy=BalanceSheetPolicy(
                deterministic_leverage_threshold_enabled=False,
                deterministic_current_ratio_threshold_enabled=False,
            ),
            liquidity_policy=LiquidityPolicy(deterministic_threshold_enabled=False),
            diversification_policy=DiversificationPolicy(universal_concentration_cap_below_full_weight=None),
            missing_data_policy=MissingDataPolicy(
                explicit_missing_data_required=True,
                interpret_missing_as_zero=False,
            ),
            loading_source=cls._SOURCE,
        )

    @classmethod
    def load_system_safety_envelope_v1(cls) -> SystemSafetyEnvelope:
        return SystemSafetyEnvelope(
            schema_version=_POLICY_SCHEMA_VERSION,
            system_safety_envelope_version=cls._SYSTEM_SAFETY_VERSION,
            supported_actions=("BUY", "HOLD"),
            supported_security_types=("EQUITY", "ETF"),
            prohibited_mechanics=("SHORTING", "MARGIN", "LEVERAGE", "OPTIONS"),
            identity_and_currency_policy=IdentityAndCurrencyPolicy(
                require_exact_security_identity=True,
                require_currency_match=True,
            ),
            chronology_and_provenance_policy=ChronologyAndProvenancePolicy(
                require_attributable_prices=True,
                forbid_future_dated_inputs=True,
                require_timezone_aware_timestamps=True,
            ),
            cash_and_arithmetic_policy=CashAndArithmeticPolicy(
                require_cash_feasibility=True,
                require_non_negative_state=True,
                require_positive_executable_quantity=True,
                decimal_safe_arithmetic=True,
            ),
            approval_and_execution_policy=ApprovalAndExecutionPolicy(
                human_approval_required=True,
                hold_never_executes=True,
                failed_validation_never_executes=True,
                rejected_or_expired_never_execute=True,
            ),
            lineage_policy=LineagePolicy(
                preserve_immutable_lineage=True,
                separate_managed_and_benchmark=True,
            ),
            loading_source=cls._SOURCE,
        )
