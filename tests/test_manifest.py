"""Guard the manifest against drift that would break HACS or hassfest."""

from __future__ import annotations

import json
from pathlib import Path
import re

MANIFEST = Path("custom_components/analog_displays/manifest.json")
CHANGELOG = Path("CHANGELOG.md")


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


def test_version_matches_the_changelog() -> None:
    """A release fails in CI if these disagree, so catch it here instead.

    Home Assistant requires custom integrations to declare a version, and
    release.yml refuses to publish a release whose tag does not match it. That
    makes the manifest and the changelog two halves of one fact; keeping them
    in step is what scripts/bump_version.py is for.
    """
    version = json.loads(MANIFEST.read_text())["version"]

    released = re.findall(
        r"^## \[(\d+\.\d+\.\d+)\]", CHANGELOG.read_text(), re.MULTILINE
    )

    assert released, "CHANGELOG.md documents no released version"
    assert released[0] == version, (
        f"manifest.json says {version} but the newest CHANGELOG.md section is "
        f"{released[0]}; run scripts/bump_version.py to move both together"
    )


def test_changelog_links_use_the_published_tag_format() -> None:
    """Tags are published without a prefix, so the links must not say v1.2.3."""
    text = CHANGELOG.read_text()
    version = json.loads(MANIFEST.read_text())["version"]

    assert f"/releases/tag/{version}" in text
    assert f"/releases/tag/v{version}" not in text
