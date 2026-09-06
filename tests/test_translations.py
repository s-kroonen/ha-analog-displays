"""The shipped translations must stay in step with strings.json."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import pytest
import yaml

COMPONENT = Path("custom_components/analog_displays")
STRINGS = COMPONENT / "strings.json"
TRANSLATIONS = COMPONENT / "translations"


def _keys(data: Any, prefix: str = "") -> set[str]:
    """Every leaf path in a translation tree."""
    if not isinstance(data, dict):
        return {prefix}
    return {
        key
        for name, value in data.items()
        for key in _keys(value, f"{prefix}.{name}" if prefix else name)
    }


def _placeholders(data: Any) -> set[str]:
    """Every {placeholder} used anywhere in a translation tree."""
    if isinstance(data, str):
        return set(re.findall(r"\{(\w+)\}", data))
    if isinstance(data, dict):
        return {name for value in data.values() for name in _placeholders(value)}
    return set()


@pytest.mark.parametrize(
    "language", [path.stem for path in sorted(TRANSLATIONS.glob("*.json"))]
)
def test_translation_has_the_same_keys_as_strings(language: str) -> None:
    """A missing key shows the user a raw translation path."""
    expected = _keys(json.loads(STRINGS.read_text()))
    actual = _keys(json.loads((TRANSLATIONS / f"{language}.json").read_text()))

    assert expected - actual == set(), f"{language} is missing keys"
    assert actual - expected == set(), f"{language} has keys strings.json lacks"


@pytest.mark.parametrize(
    "language", [path.stem for path in sorted(TRANSLATIONS.glob("*.json"))]
)
def test_translation_uses_the_same_placeholders(language: str) -> None:
    """A placeholder that only exists in one language renders literally."""
    expected = _placeholders(json.loads(STRINGS.read_text()))
    actual = _placeholders(json.loads((TRANSLATIONS / f"{language}.json").read_text()))

    assert expected == actual


def test_dutch_is_shipped() -> None:
    assert (TRANSLATIONS / "nl.json").exists()
    assert (TRANSLATIONS / "en.json").exists()


def test_every_service_is_documented() -> None:
    """Hassfest checks this too, but it fails fast here."""
    services = yaml.safe_load((COMPONENT / "services.yaml").read_text())
    documented = json.loads(STRINGS.read_text())["services"]

    assert set(services) == set(documented)
    for name, definition in services.items():
        assert set(definition["fields"]) == set(documented[name]["fields"])
