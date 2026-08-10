"""Deterministic loading for the approved Value Manager constitution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .portfolio import _canonical_upper_text, _require_non_empty_text

_VALUE_MANAGER_TYPE = "VALUE"
_SEMANTIC_VERSION_PATTERN = re.compile(r"^[a-z][a-z0-9-]*-v[0-9]+\.[0-9]+\.[0-9]+$")


@dataclass(frozen=True, slots=True)
class ConstitutionVersion:
    """A stable, semantic-style identifier for one approved constitution."""

    value: str

    def __post_init__(self) -> None:
        value = _require_non_empty_text(self.value, field_name="constitution version").strip()
        if not _SEMANTIC_VERSION_PATTERN.fullmatch(value):
            raise ValueError("constitution version must use the form '<manager>-v<major>.<minor>.<patch>'")
        object.__setattr__(self, "value", value)


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
