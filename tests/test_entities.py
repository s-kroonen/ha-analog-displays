"""Select, sensor and binary_sensor entities, plus LED driving."""

from __future__ import annotations

from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, ServiceCall, State
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
    mock_restore_cache,
)

from custom_components.analog_displays.const import CONFIG_VERSION, DOMAIN
from tests.helpers import settle
from tests.test_init import device_options

SELECT = "select.meter_panel_preset"
VALUE = "sensor.meter_panel_left_value"
NEEDLE = "sensor.meter_panel_left_needle_position"
STALE = "binary_sensor.meter_panel_left_source_stale"


@pytest.fixture(autouse=True)
def _services(hass: HomeAssistant) -> None:
    """Register the services the controller calls."""
    async_mock_service(hass, "number", "set_value")


@pytest.fixture
def light_on(hass: HomeAssistant) -> list[ServiceCall]:
    """Capture light.turn_on calls."""
    return async_mock_service(hass, "light", "turn_on")


@pytest.fixture
def light_off(hass: HomeAssistant) -> list[ServiceCall]:
    """Capture light.turn_off calls."""
    return async_mock_service(hass, "light", "turn_off")


@pytest.fixture(autouse=True)
def _output(hass: HomeAssistant) -> None:
    """Publish the display output and its source."""
    hass.states.async_set(
        "number.meter_left", "0", {"min": 0.0, "max": 1.0, "step": 0.001}
    )
    hass.states.async_set("light.led_left", "off")


def _two_presets() -> list[dict[str, Any]]:
    """Build a Power preset and a Grid preset over the same display."""
    return [
        {
            "label": "Power",
            "assignments": {
                "0": {
                    "source_mode": "entity",
                    "source_entity_id": "sensor.solar",
                    "min_value": 0.0,
                    "max_value": 3000.0,
                    "colour": [0, 255, 0],
                }
            },
        },
        {
            "label": "Grid",
            "assignments": {
                "0": {
                    "source_mode": "entity",
                    "source_entity_id": "sensor.grid",
                    "min_value": -3000.0,
                    "max_value": 3000.0,
                    "colour": [0, 0, 255],
                }
            },
        },
    ]


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


# --- device grouping --------------------------------------------------------


async def test_all_entities_hang_off_one_device(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """The integrations page shows one device, with displays as entities."""
    hass.states.async_set("sensor.solar", "1500")
    entry = await _setup(hass)

    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    assert len(devices) == 1
    assert devices[0].name == "Meter Panel"

    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    assert {entity.entity_id for entity in entities} == {SELECT, VALUE, NEEDLE, STALE}
    assert all(entity.device_id == devices[0].id for entity in entities)


# --- sensors ----------------------------------------------------------------


async def test_sensors_report_the_reading_and_the_needle(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    hass.states.async_set("sensor.solar", "750", {"unit_of_measurement": "W"})
    await _setup(hass)

    value = hass.states.get(VALUE)
    assert value is not None
    assert float(value.state) == 750.0
    assert value.attributes["unit_of_measurement"] == "W"

    needle = hass.states.get(NEEDLE)
    assert needle is not None
    assert float(needle.state) == 25.0
    assert needle.attributes["unit_of_measurement"] == "%"


async def test_sensors_follow_source_updates(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    hass.states.async_set("sensor.solar", "750", {"unit_of_measurement": "W"})
    await _setup(hass)

    hass.states.async_set("sensor.solar", "1500", {"unit_of_measurement": "W"})
    await settle(hass, freezer)

    assert float(hass.states.get(VALUE).state) == 1500.0
    assert float(hass.states.get(NEEDLE).state) == 50.0


async def test_sensors_are_unknown_before_the_first_reading(
    hass: HomeAssistant,
) -> None:
    await _setup(hass)
    assert hass.states.get(VALUE).state == STATE_UNKNOWN
    assert hass.states.get(NEEDLE).state == STATE_UNKNOWN


async def test_the_needle_sensor_is_diagnostic(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    hass.states.async_set("sensor.solar", "750")
    await _setup(hass)

    assert (
        entity_registry.async_get(NEEDLE).entity_category
        == er.EntityCategory.DIAGNOSTIC
    )
    assert entity_registry.async_get(VALUE).entity_category is None


# --- staleness --------------------------------------------------------------


async def test_the_stale_sensor_tracks_the_source(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    hass.states.async_set("sensor.solar", "1500")
    await _setup(hass)
    assert hass.states.get(STALE).state == STATE_OFF

    hass.states.async_set("sensor.solar", "unavailable")
    await settle(hass, freezer)
    assert hass.states.get(STALE).state == STATE_ON

    hass.states.async_set("sensor.solar", "2000")
    await settle(hass, freezer)
    assert hass.states.get(STALE).state == STATE_OFF


async def test_the_value_sensor_holds_over_an_outage(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The sensor shows the held reading, and the stale flag explains why."""
    hass.states.async_set("sensor.solar", "1500")
    await _setup(hass)

    hass.states.async_set("sensor.solar", "unavailable")
    await settle(hass, freezer)

    assert float(hass.states.get(VALUE).state) == 1500.0
    assert hass.states.get(STALE).state == STATE_ON


# --- the preset selector ----------------------------------------------------


async def test_the_select_lists_every_preset(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.solar", "1500")
    hass.states.async_set("sensor.grid", "0")
    await _setup(hass, presets=_two_presets())

    state = hass.states.get(SELECT)
    assert state is not None
    assert state.state == "Power"
    assert state.attributes["options"] == ["Power", "Grid"]


async def test_selecting_a_preset_repoints_the_display(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    hass.states.async_set("sensor.solar", "1500")
    hass.states.async_set("sensor.grid", "3000")
    await _setup(hass, presets=_two_presets())

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": SELECT, "option": "Grid"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert hass.states.get(SELECT).state == "Grid"
    assert float(hass.states.get(VALUE).state) == 3000.0
    assert float(hass.states.get(NEEDLE).state) == 100.0


async def test_the_active_preset_survives_a_restart(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The board must come back showing whatever it was showing before."""
    mock_restore_cache(hass, (State(SELECT, "Grid"),))
    hass.states.async_set("sensor.solar", "1500")
    hass.states.async_set("sensor.grid", "3000")

    entry = await _setup(hass, presets=_two_presets())

    assert hass.states.get(SELECT).state == "Grid"
    assert entry.runtime_data.active_preset_index == 1
    assert float(hass.states.get(VALUE).state) == 3000.0


async def test_a_stale_restored_preset_is_ignored(hass: HomeAssistant) -> None:
    """A preset that was renamed or removed must not break startup."""
    mock_restore_cache(hass, (State(SELECT, "Deleted Preset"),))
    hass.states.async_set("sensor.solar", "1500")

    entry = await _setup(hass)

    assert entry.runtime_data.active_preset_index == 0
    assert hass.states.get(SELECT).state == "Power"


# --- LEDs -------------------------------------------------------------------


def _with_led(mode: str = "preset", **led: Any) -> list[dict[str, Any]]:
    """Bind a light to display 0. How it behaves lives on the assignment."""
    displays = device_options()["displays"]
    displays[0]["light_entity_id"] = "light.led_left"
    return displays


def _led_behaviour(
    presets: list[dict[str, Any]], mode: str, **led: Any
) -> list[dict[str, Any]]:
    """Set LED mode, fade and zones on display 0 of every preset."""
    for preset in presets:
        assignment = preset["assignments"].get("0")
        if assignment is not None:
            assignment.update({"mode": mode, "fade": False, "stops": [], **led})
    return presets


async def test_preset_mode_shows_the_presets_colour(
    hass: HomeAssistant, light_on: list[ServiceCall]
) -> None:
    hass.states.async_set("sensor.solar", "1500")
    hass.states.async_set("sensor.grid", "0")
    await _setup(
        hass,
        displays=_with_led(),
        presets=_led_behaviour(_two_presets(), "preset"),
    )

    assert light_on[-1].data["rgb_color"] == [0, 255, 0]

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": SELECT, "option": "Grid"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert light_on[-1].data["rgb_color"] == [0, 0, 255]


async def test_gradient_mode_colours_by_value(
    hass: HomeAssistant, light_on: list[ServiceCall], freezer: FrozenDateTimeFactory
) -> None:
    """Stops are on the normalized scale, so they survive a preset change."""
    hass.states.async_set("sensor.solar", "2700")  # 0.9 of 0-3000
    presets = _led_behaviour(
        [device_options()["presets"][0]],
        "gradient",
        stops=[
            {"at": 600.0, "colour": [255, 0, 0], "end": None},
            {"at": 2400.0, "colour": [0, 255, 0], "end": None},
        ],
    )
    await _setup(hass, displays=_with_led(), presets=presets)

    assert light_on[-1].data["rgb_color"] == [0, 255, 0]

    hass.states.async_set("sensor.solar", "1200")  # below the 2400 W stop
    await settle(hass, freezer)
    assert light_on[-1].data["rgb_color"] == [255, 0, 0]


async def test_gradient_mode_blends_when_fading(
    hass: HomeAssistant, light_on: list[ServiceCall]
) -> None:
    hass.states.async_set("sensor.solar", "1500")  # 0.5, halfway between stops
    presets = _led_behaviour(
        [device_options()["presets"][0]],
        "gradient",
        stops=[
            {"at": 0.0, "colour": [0, 0, 0], "end": None},
            {"at": 3000.0, "colour": [100, 200, 50], "end": None},
        ],
        fade=True,
    )
    await _setup(hass, displays=_with_led(), presets=presets)

    assert light_on[-1].data["rgb_color"] == [50, 100, 25]


async def test_below_the_first_stop_the_led_is_turned_off(
    hass: HomeAssistant, light_off: list[ServiceCall]
) -> None:
    hass.states.async_set("sensor.solar", "150")  # 0.05, below the first stop
    presets = _led_behaviour(
        [device_options()["presets"][0]],
        "gradient",
        stops=[{"at": 600.0, "colour": [255, 0, 0], "end": None}],
    )
    await _setup(hass, displays=_with_led(), presets=presets)

    assert len(light_off) == 1


async def test_led_mode_off_darkens_the_light_and_leaves_it_alone(
    hass: HomeAssistant,
    light_on: list[ServiceCall],
    light_off: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Mode "off" promises a dark LED, so it is darkened once and then left."""
    hass.states.async_set("sensor.solar", "1500")
    await _setup(
        hass,
        displays=_with_led(),
        presets=_led_behaviour([device_options()["presets"][0]], "off"),
    )

    assert light_on == []
    assert len(light_off) == 1

    hass.states.async_set("sensor.solar", "3000")
    await settle(hass, freezer)

    assert light_on == []
    assert len(light_off) == 1


async def test_redundant_colour_writes_are_skipped(
    hass: HomeAssistant, light_on: list[ServiceCall], freezer: FrozenDateTimeFactory
) -> None:
    """Two readings in the same colour band must not re-send the colour."""
    hass.states.async_set("sensor.solar", "2700")
    presets = _led_behaviour(
        [device_options()["presets"][0]],
        "gradient",
        stops=[
            {"at": 600.0, "colour": [255, 0, 0], "end": None},
            {"at": 2400.0, "colour": [0, 255, 0], "end": None},
        ],
    )
    await _setup(hass, displays=_with_led(), presets=presets)
    assert len(light_on) == 1

    hass.states.async_set("sensor.solar", "2900")
    await settle(hass, freezer)

    assert len(light_on) == 1


# --- real-unit scales and conversion ----------------------------------------


def _power_preset(unit: str | None, low: float, high: float) -> list[dict[str, Any]]:
    """Build a preset reading a watt sensor against a range in `unit`."""
    return [
        {
            "label": "Power",
            "assignments": {
                "0": {
                    "source_mode": "entity",
                    "source_entity_id": "sensor.solar",
                    "unit": unit,
                    "min_value": low,
                    "max_value": high,
                    "colour": None,
                }
            },
        }
    ]


async def test_a_watt_sensor_on_a_kilowatt_scale(hass: HomeAssistant) -> None:
    """The whole point: 1500 W on a 0-10 kW meter is 15 %, not full scale."""
    calls = async_mock_service(hass, "number", "set_value")
    hass.states.async_set(
        "sensor.solar", "1500", {"unit_of_measurement": "W", "device_class": "power"}
    )

    await _setup(hass, presets=_power_preset("kW", 0.0, 10.0))

    assert calls[-1].data["value"] == pytest.approx(0.15)


async def test_without_a_unit_the_reading_is_taken_as_is(hass: HomeAssistant) -> None:
    """Leaving the unit blank keeps the pre-conversion behaviour."""
    calls = async_mock_service(hass, "number", "set_value")
    hass.states.async_set("sensor.solar", "1500", {"unit_of_measurement": "W"})

    await _setup(hass, presets=_power_preset(None, 0.0, 3000.0))

    assert calls[-1].data["value"] == pytest.approx(0.5)


async def test_an_impossible_conversion_holds_the_needle(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Better a held needle than a confidently wrong one."""
    calls = async_mock_service(hass, "number", "set_value")
    hass.states.async_set(
        "sensor.solar", "1500", {"unit_of_measurement": "W", "device_class": "power"}
    )
    entry = await _setup(hass, presets=_power_preset("°C", -10.0, 40.0))

    assert calls == []
    assert entry.runtime_data.controllers[0].stale is True


async def test_thresholds_are_read_in_the_displays_own_unit(
    hass: HomeAssistant, light_on: list[ServiceCall], freezer: FrozenDateTimeFactory
) -> None:
    """Red below 2 kW, green above 8 kW, on a 0-10 kW meter fed in watts."""
    hass.states.async_set(
        "sensor.solar", "9000", {"unit_of_measurement": "W", "device_class": "power"}
    )
    presets = _power_preset("kW", 0.0, 10.0)
    presets[0]["assignments"]["0"] |= {
        "mode": "gradient",
        "fade": False,
        "stops": [
            {"at": 2.0, "colour": [255, 0, 0], "end": None},
            {"at": 8.0, "colour": [0, 255, 0], "end": None},
        ],
    }
    await _setup(hass, displays=_with_led(), presets=presets)

    # 9 kW is above the 8 kW stop.
    assert light_on[-1].data["rgb_color"] == [0, 255, 0]

    hass.states.async_set(
        "sensor.solar", "4000", {"unit_of_measurement": "W", "device_class": "power"}
    )
    await settle(hass, freezer)

    # 4 kW is above 2 but below 8.
    assert light_on[-1].data["rgb_color"] == [255, 0, 0]


# --- preset change blink ----------------------------------------------------


async def test_switching_preset_blinks_the_feedback_colour(
    hass: HomeAssistant, light_on: list[ServiceCall], light_off: list[ServiceCall]
) -> None:
    """Confirms a preset change on a board with no screen."""
    hass.states.async_set("sensor.solar", "1500")
    hass.states.async_set("sensor.grid", "3000")
    presets = _two_presets()
    presets[1]["feedback_colour"] = [255, 255, 0]

    await _setup(hass, displays=_with_led(), presets=_led_behaviour(presets, "preset"))
    light_on.clear()
    light_off.clear()

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": SELECT, "option": "Grid"},
        blocking=True,
    )
    await hass.async_block_till_done()

    blinks = [call for call in light_on if call.data["rgb_color"] == [255, 255, 0]]
    assert len(blinks) == 2, "two flashes reads as deliberate, one reads as a glitch"
    # It settles on the new preset's own colour, not the feedback colour.
    assert light_on[-1].data["rgb_color"] == [0, 0, 255]


async def test_a_preset_without_a_feedback_colour_does_not_blink(
    hass: HomeAssistant, light_on: list[ServiceCall]
) -> None:
    hass.states.async_set("sensor.solar", "1500")
    hass.states.async_set("sensor.grid", "3000")

    await _setup(
        hass, displays=_with_led(), presets=_led_behaviour(_two_presets(), "preset")
    )
    light_on.clear()

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": SELECT, "option": "Grid"},
        blocking=True,
    )
    await hass.async_block_till_done()

    # Exactly one write: the new preset's colour, no flashes.
    assert [call.data["rgb_color"] for call in light_on] == [[0, 0, 255]]
