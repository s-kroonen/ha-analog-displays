"""Migrating a 0.1.0 configuration to the reshaped model.

There are real installs on 0.1.0, so a migrated entry has to keep behaving the
way it did: same needle position, same LED colour, no unit conversion silently
introduced.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.analog_displays.const import CONFIG_VERSION, DOMAIN


def v1_options() -> dict[str, Any]:
    """Options exactly as 0.1.0 wrote them: LED behaviour on the display."""
    return {
        "name": "Meter Panel",
        "displays": [
            {
                "name": "Left",
                "output_entity_id": "number.meter_left",
                "led": {
                    "light_entity_id": "light.led_left",
                    "mode": "gradient",
                    # 0.1.0 stored thresholds as a fraction of full scale.
                    "stops": [
                        {"at": 0.2, "colour": [255, 0, 0], "end": None},
                        {"at": 0.8, "colour": [0, 255, 0], "end": None},
                    ],
                    "fade": False,
                },
                "min_update_interval": 5.0,
            }
        ],
        "presets": [
            {
                "label": "Power",
                "assignments": {
                    "0": {
                        "source_mode": "entity",
                        "source_entity_id": "sensor.solar",
                        "statistic_entity_id": None,
                        "statistic_type": None,
                        "statistic_period": None,
                        "min_value": 0.0,
                        "max_value": 3000.0,
                        "colour": None,
                    }
                },
            }
        ],
        "active_preset_index": 0,
        "buttons": [],
        "hardware_profile": None,
        "statistics_interval": 300.0,
    }


@pytest.fixture(autouse=True)
def set_value_calls(hass: HomeAssistant) -> list[ServiceCall]:
    return async_mock_service(hass, "number", "set_value")


@pytest.fixture
def light_on(hass: HomeAssistant) -> list[ServiceCall]:
    return async_mock_service(hass, "light", "turn_on")


@pytest.fixture(autouse=True)
def _states(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "number.meter_left", "0", {"min": 0.0, "max": 1.0, "step": 0.001}
    )
    hass.states.async_set("light.led_left", "off")
    # 2700 W of 0-3000 is 0.9 normalised, above the old 0.8 green threshold.
    hass.states.async_set("sensor.solar", "2700", {"unit_of_measurement": "W"})


async def _setup_v1(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Meter Panel", data={}, options=v1_options(), version=1
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_a_v1_entry_loads_and_is_migrated(hass: HomeAssistant) -> None:
    entry = await _setup_v1(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == CONFIG_VERSION


async def test_led_behaviour_moves_onto_the_assignment(hass: HomeAssistant) -> None:
    entry = await _setup_v1(hass)
    device = entry.runtime_data.device

    # The display keeps only the binding.
    assert device.displays[0].light_entity_id == "light.led_left"

    assignment = device.presets[0].assignments[0]
    assert assignment.led_mode == "gradient"
    assert assignment.fade is False


async def test_thresholds_become_real_units_meaning_the_same_thing(
    hass: HomeAssistant,
) -> None:
    """0.2 of a 0-3000 W range is 600 W; the boundary must not move."""
    entry = await _setup_v1(hass)

    stops = entry.runtime_data.device.presets[0].assignments[0].stops

    assert [stop.at for stop in stops] == [600.0, 2400.0]


async def test_no_unit_conversion_is_introduced(hass: HomeAssistant) -> None:
    """A migrated assignment reads its source exactly as 0.1.0 did."""
    entry = await _setup_v1(hass)

    assert entry.runtime_data.device.presets[0].assignments[0].unit is None


async def test_the_needle_lands_where_it_did_before(
    hass: HomeAssistant, set_value_calls: list[ServiceCall]
) -> None:
    await _setup_v1(hass)

    # 2700 of 0-3000 on a 0.0-1.0 output.
    assert set_value_calls[-1].data["value"] == pytest.approx(0.9)


async def test_the_led_shows_the_same_colour_as_before(
    hass: HomeAssistant, light_on: list[ServiceCall]
) -> None:
    """0.9 was above the old 0.8 stop, so the LED was green; it still is."""
    await _setup_v1(hass)

    assert light_on[-1].data["rgb_color"] == [0, 255, 0]


async def test_presets_gain_no_blink_by_default(hass: HomeAssistant) -> None:
    entry = await _setup_v1(hass)

    assert entry.runtime_data.device.presets[0].feedback_colour is None


async def test_migration_is_idempotent(hass: HomeAssistant) -> None:
    """Reloading an already-migrated entry must not mangle it a second time."""
    entry = await _setup_v1(hass)
    first = dict(entry.options)

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert dict(entry.options) == first
    assert entry.state is ConfigEntryState.LOADED
