"""Entry setup, teardown, and the end-to-end write path."""

from __future__ import annotations

from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.analog_displays.const import CONFIG_VERSION, DOMAIN
from tests.helpers import settle


def device_options(**overrides: Any) -> dict[str, Any]:
    """Build a one-display, one-preset device as stored in entry options."""
    options: dict[str, Any] = {
        "name": "Meter Panel",
        "displays": [
            {
                "name": "Left",
                "output_entity_id": "number.meter_left",
                "light_entity_id": None,
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
    }
    return options | overrides


@pytest.fixture
def set_value_calls(hass: HomeAssistant) -> list[ServiceCall]:
    """Capture number.set_value calls."""
    return async_mock_service(hass, "number", "set_value")


@pytest.fixture
def output(hass: HomeAssistant) -> None:
    """Publish a 0-1 template number, the reference ESPHome output."""
    hass.states.async_set(
        "number.meter_left", "0", {"min": 0.0, "max": 1.0, "step": 0.001}
    )


async def _setup(hass: HomeAssistant, **overrides: Any) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Meter Panel",
        data={},
        options=device_options(**overrides),
        version=CONFIG_VERSION,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_and_unload(
    hass: HomeAssistant, output: None, set_value_calls: list[ServiceCall]
) -> None:
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.device.name == "Meter Panel"
    assert len(entry.runtime_data.controllers) == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_source_change_writes_the_rescaled_value(
    hass: HomeAssistant,
    output: None,
    set_value_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """A push from the source lands on the output, scaled into its range."""
    hass.states.async_set("sensor.solar", "0", {"unit_of_measurement": "W"})
    await _setup(hass)
    set_value_calls.clear()

    hass.states.async_set("sensor.solar", "1500", {"unit_of_measurement": "W"})
    await settle(hass, freezer)

    assert len(set_value_calls) == 1
    # 1500 of 0-3000 is halfway, and the target's own range is 0.0-1.0.
    assert set_value_calls[0].data["value"] == pytest.approx(0.5)
    assert set_value_calls[0].data["entity_id"] == "number.meter_left"


async def test_write_scales_into_a_0_255_target(
    hass: HomeAssistant, set_value_calls: list[ServiceCall]
) -> None:
    """A dimmer-style output needs no user configuration."""
    hass.states.async_set("number.meter_left", "0", {"min": 0, "max": 255, "step": 1})
    hass.states.async_set("sensor.solar", "1500")
    await _setup(hass)

    assert set_value_calls[-1].data["value"] == pytest.approx(128.0)


async def test_initial_write_happens_on_setup(
    hass: HomeAssistant, output: None, set_value_calls: list[ServiceCall]
) -> None:
    """The needle must reflect reality immediately, not on the next update."""
    hass.states.async_set("sensor.solar", "750")
    await _setup(hass)

    assert set_value_calls
    assert set_value_calls[-1].data["value"] == pytest.approx(0.25)


async def test_out_of_range_source_is_clamped(
    hass: HomeAssistant, output: None, set_value_calls: list[ServiceCall]
) -> None:
    hass.states.async_set("sensor.solar", "9000")
    await _setup(hass)

    assert set_value_calls[-1].data["value"] == pytest.approx(1.0)


async def test_unavailable_source_holds_the_last_value(
    hass: HomeAssistant,
    output: None,
    set_value_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Never snap the needle to zero: a stale reading beats a wrong one."""
    hass.states.async_set("sensor.solar", "1500")
    await _setup(hass)
    set_value_calls.clear()

    hass.states.async_set("sensor.solar", "unavailable")
    await settle(hass, freezer)

    assert set_value_calls == []


async def test_non_numeric_source_holds_the_last_value(
    hass: HomeAssistant,
    output: None,
    set_value_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    hass.states.async_set("sensor.solar", "1500")
    await _setup(hass)
    set_value_calls.clear()

    hass.states.async_set("sensor.solar", "brisk")
    await settle(hass, freezer)

    assert set_value_calls == []


async def test_unassigned_display_is_driven_to_zero(
    hass: HomeAssistant, output: None, set_value_calls: list[ServiceCall]
) -> None:
    """A display no preset points at is not in use; it is not an error."""
    hass.states.async_set("sensor.solar", "1500")
    hass.states.async_set(
        "number.meter_right", "0", {"min": 0.0, "max": 1.0, "step": 0.001}
    )
    options = device_options()
    options["displays"].append(
        {
            "name": "Right",
            "output_entity_id": "number.meter_right",
            "led": None,
            "min_update_interval": 5.0,
        }
    )
    await _setup(hass, displays=options["displays"])

    by_entity = {call.data["entity_id"]: call.data["value"] for call in set_value_calls}
    assert by_entity["number.meter_left"] == pytest.approx(0.5)
    assert by_entity["number.meter_right"] == 0.0


async def test_invalid_stored_options_are_not_ready(hass: HomeAssistant) -> None:
    """Corrupt options must not load a half-configured entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Broken",
        data={},
        options={"name": "Broken"},
        version=CONFIG_VERSION,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_missing_output_entity_does_not_break_setup(
    hass: HomeAssistant, set_value_calls: list[ServiceCall]
) -> None:
    """A board that is offline at startup must still load, just not write."""
    hass.states.async_set("sensor.solar", "1500")
    entry = await _setup(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert set_value_calls == []


async def test_a_failing_write_does_not_take_the_entry_down(
    hass: HomeAssistant, output: None
) -> None:
    """An offline board must not stop the rest of the device working."""
    hass.states.async_set("sensor.solar", "1500")

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Meter Panel",
        data={},
        options=device_options(),
        version=CONFIG_VERSION,
    )
    entry.add_to_hass(hass)

    # number.set_value is deliberately not registered, so every write raises.
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.controllers[0].last_value is None


def _range_preset(low: float, high: float, unit: str | None = None) -> dict[str, Any]:
    """One display reading sensor.solar against an arbitrary real-world range."""
    assignment: dict[str, Any] = {
        "source_mode": "entity",
        "source_entity_id": "sensor.solar",
        "min_value": low,
        "max_value": high,
        "colour": None,
    }
    if unit is not None:
        assignment["unit"] = unit
    return {"label": "Power", "assignments": {"0": assignment}}


@pytest.mark.parametrize(
    ("reading", "expected"),
    [
        ("200", 0.0),  # bottom of the dial
        ("250", 50.0),  # halfway
        ("300", 100.0),  # full scale
        ("350", 100.0),  # past the end stop, which has no give
        ("150", 0.0),
    ],
)
async def test_a_200_to_300_degree_dial_maps_onto_a_0_100_output(
    hass: HomeAssistant,
    set_value_calls: list[ServiceCall],
    reading: str,
    expected: float,
) -> None:
    """The face reads 200-300 °C; the signal is 0-100. The needle is the map."""
    hass.states.async_set("number.meter_left", "0", {"min": 0, "max": 100, "step": 0.1})
    hass.states.async_set(
        "sensor.solar",
        reading,
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )

    await _setup(hass, presets=[_range_preset(200.0, 300.0)])

    assert set_value_calls[-1].data["value"] == pytest.approx(expected)
    assert set_value_calls[-1].data["entity_id"] == "number.meter_left"


async def test_a_negative_to_positive_kw_dial_maps_onto_a_0_100_output(
    hass: HomeAssistant, set_value_calls: list[ServiceCall]
) -> None:
    """-1 kW to 5 kW from a sensor in watts: converted, then mapped."""
    hass.states.async_set("number.meter_left", "0", {"min": 0, "max": 100, "step": 0.1})
    hass.states.async_set(
        "sensor.solar", "2000", {"unit_of_measurement": "W", "device_class": "power"}
    )

    await _setup(hass, presets=[_range_preset(-1.0, 5.0, unit="kW")])

    # 2000 W is 2 kW, which sits halfway between -1 kW and 5 kW.
    assert set_value_calls[-1].data["value"] == pytest.approx(50.0)


async def test_an_export_reading_pins_the_needle_at_the_bottom(
    hass: HomeAssistant, set_value_calls: list[ServiceCall]
) -> None:
    """Below the configured minimum the needle rests, it does not go negative."""
    hass.states.async_set("number.meter_left", "0", {"min": 0, "max": 100, "step": 0.1})
    hass.states.async_set(
        "sensor.solar", "-3000", {"unit_of_measurement": "W", "device_class": "power"}
    )

    await _setup(hass, presets=[_range_preset(-1.0, 5.0, unit="kW")])

    assert set_value_calls[-1].data["value"] == pytest.approx(0.0)
