"""Diagnostics output."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.analog_displays.const import DOMAIN
from custom_components.analog_displays.diagnostics import (
    async_get_config_entry_diagnostics,
)
from tests.test_buttons import _presets
from tests.test_init import device_options


@pytest.fixture(autouse=True)
def set_value_calls(hass: HomeAssistant) -> list[ServiceCall]:
    return async_mock_service(hass, "number", "set_value")


@pytest.fixture(autouse=True)
def _states(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "number.meter_left", "0", {"min": 0.0, "max": 1.0, "step": 0.001}
    )
    hass.states.async_set("sensor.solar", "1500", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.grid", "0")


async def _setup(hass: HomeAssistant, **overrides: Any) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Meter Panel",
        data={},
        options=device_options(**({"presets": _presets()} | overrides)),
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_diagnostics_describe_the_live_state(hass: HomeAssistant) -> None:
    entry = await _setup(hass)

    report = await async_get_config_entry_diagnostics(hass, entry)

    assert report["state"]["active_preset_label"] == "Power"
    assert report["state"]["uses_statistics"] is False
    assert report["state"]["polling"] is False

    display = report["state"]["displays"][0]
    assert display["name"] == "Left"
    assert display["assigned"] is True
    assert display["stale"] is False
    assert display["raw"] == 1500.0
    assert display["unit"] == "W"
    assert display["normalized"] == pytest.approx(0.5)


async def test_entity_ids_are_redacted(hass: HomeAssistant) -> None:
    """Entity ids carry room and household names; a bug report needs none."""
    entry = await _setup(hass)

    report = await async_get_config_entry_diagnostics(hass, entry)
    dumped = str(report["options"])

    assert "number.meter_left" not in dumped
    assert "sensor.solar" not in dumped
    assert "REDACTED" in dumped
    # Everything else survives, so the report is still useful.
    assert report["options"]["presets"][0]["label"] == "Power"
    assert report["options"]["presets"][0]["assignments"]["0"]["max_value"] == 3000.0


async def test_diagnostics_report_a_stale_display(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.solar", "unavailable")
    entry = await _setup(hass)

    report = await async_get_config_entry_diagnostics(hass, entry)

    assert report["state"]["displays"][0]["stale"] is True
    assert report["state"]["displays"][0]["raw"] is None
