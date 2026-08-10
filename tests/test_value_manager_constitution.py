from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from agentic_portfolio_lab.domain.constitution import (
    ConstitutionLoader,
    ConstitutionVersion,
    ValueManagerConstitution,
)


def _constitution(**overrides: object) -> ValueManagerConstitution:
    arguments: dict[str, object] = {
        "version": ConstitutionVersion("value-v1.0.0"),
        "manager_type": " VALUE ",
        "name": "Value Manager Constitution",
        "description": "Approved methodology for the first Value Manager.",
        "loading_source": "docs/value-manager-constitution.md",
        "content": "# Value Manager Constitution\n",
    }
    arguments.update(overrides)
    return ValueManagerConstitution(**arguments)  # type: ignore[arg-type]


def test_loader_returns_the_approved_versioned_repository_artifact() -> None:
    constitution = ConstitutionLoader.load_value_manager_constitution()

    assert constitution.constitution_version == "value-v1.0.0"
    assert constitution.manager_type == "VALUE"
    assert constitution.name == "Value Manager Constitution"
    assert constitution.loading_source == "docs/value-manager-constitution.md"
    assert constitution.content.startswith("# Value Manager Constitution")


def test_constitution_is_immutable_and_repeated_loading_is_deterministic() -> None:
    first = ConstitutionLoader.load_value_manager_constitution()
    second = ConstitutionLoader.load_value_manager_constitution()

    assert first == second
    with pytest.raises(FrozenInstanceError):
        first.content = "changed"  # type: ignore[misc]


def test_value_manager_constitution_accepts_a_matching_normalized_manager_type_and_version_namespace() -> None:
    constitution = _constitution(manager_type=" value ", version=ConstitutionVersion("value-v1.0.0"))

    assert constitution.manager_type == "VALUE"
    assert constitution.constitution_version == "value-v1.0.0"


def test_value_manager_constitution_rejects_a_conflicting_version_namespace() -> None:
    with pytest.raises(ValueError, match="namespace"):
        _constitution(version=ConstitutionVersion("growth-v1.0.0"))


def test_value_manager_constitution_rejects_a_conflicting_hyphenated_version_namespace() -> None:
    with pytest.raises(ValueError, match="namespace"):
        _constitution(version=ConstitutionVersion("value-vgrowth-v1.0.0"))


def test_constitution_version_preserves_a_valid_hyphenated_namespace() -> None:
    version = ConstitutionVersion("value-manager-v1.0.0")

    assert version.value == "value-manager-v1.0.0"


@pytest.mark.parametrize("value", ["", " ", "value-1.0.0", "value-v1.0", "VALUE-v1.0.0"])
def test_constitution_version_rejects_blank_and_malformed_values(value: str) -> None:
    with pytest.raises(ValueError, match="constitution version"):
        ConstitutionVersion(value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("content", " "),
        ("name", " "),
        ("description", " "),
        ("loading_source", " "),
    ],
)
def test_constitution_rejects_malformed_required_artifact_data(field: str, value: str) -> None:
    with pytest.raises(ValueError, match=field):
        _constitution(**{field: value})


def test_value_manager_constitution_rejects_a_mismatched_manager_type() -> None:
    with pytest.raises(ValueError, match="manager_type"):
        _constitution(manager_type="GROWTH")


def test_loader_fails_clearly_when_the_approved_source_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ConstitutionLoader, "_SOURCE", "docs/missing-value-manager-constitution.md")

    with pytest.raises(ValueError, match="unable to load"):
        ConstitutionLoader.load_value_manager_constitution()


def test_loader_is_independent_of_the_current_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    assert ConstitutionLoader.load_value_manager_constitution().constitution_version == "value-v1.0.0"


def test_constitution_module_has_no_llm_provider_or_framework_dependency() -> None:
    assert ConstitutionLoader.__module__ == "agentic_portfolio_lab.domain.constitution"
    assert _constitution().content == "# Value Manager Constitution\n"
