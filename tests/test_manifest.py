"""Guard the manifest against drift that would break HACS or hassfest."""

from __future__ import annotations

import json
from pathlib import Path

MANIFEST = Path("custom_components/analog_displays/manifest.json")


def test_manifest_matches_architecture() -> None:
    """The manifest must stay dependency-free and GUI-configured."""
    manifest = json.loads(MANIFEST.read_text())

    assert manifest["domain"] == "analog_displays"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "local_push"
    assert manifest["integration_type"] == "hub"
    # Keeping requirements empty is what makes HACS review and CI trivial.
    assert manifest["requirements"] == []


def test_version_is_semver() -> None:
    """release.yml asserts tag == version, so the version must be semver."""
    version = json.loads(MANIFEST.read_text())["version"]
    major, minor, patch = version.split(".")
    assert all(part.isdigit() for part in (major, minor, patch))
