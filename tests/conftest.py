"""Shared fixtures for the Analog Displays test suite."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion
from syrupy.extensions.amber import AmberSnapshotExtension
from syrupy.location import PyTestLocation

pytest_plugins = ["pytest_homeassistant_custom_component"]


class _SnapshotsDirExtension(AmberSnapshotExtension):
    """Keep snapshots in tests/snapshots/ on every supported HA version.

    Which directory the ambient ``snapshot`` fixture uses has changed between
    pytest-homeassistant-custom-component releases, so pin it here rather than
    inherit it — otherwise the same snapshot file is written by one HA version
    and reported missing by another.
    """

    @classmethod
    def dirname(cls, *, test_location: PyTestLocation) -> str:
        """Resolve to a snapshots/ directory beside the test file."""
        return str(Path(test_location.filepath).parent / "snapshots")


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Pin snapshot storage to tests/snapshots/, whatever the plugin default."""
    return snapshot.use_extension(_SnapshotsDirExtension)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Enable loading of custom_components/ in every test."""
    yield
