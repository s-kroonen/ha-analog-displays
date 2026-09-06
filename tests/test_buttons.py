"""Button dispatch, device triggers and the integration's services."""

from __future__ import annotations

from typing import Any

from homeassistant.components import automation
from homeassistant.components.device_automation import DeviceAutomationType
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_get_device_automations,
    async_mock_service,
)

from custom_components.analog_displays.const import DOMAIN, EVENT_BUTTON_PRESSED
from tests.test_init import device_options


@pytest.fixture(autouse=True)
def _services(hass: HomeAssistant) -> None:
    async_mock_service(hass, "number", "set_value")


@pytest.fixture(autouse=True)
def _states(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "number.meter_left", "0", {"min": 0.0, "max": 1.0, "step": 0.001}
    )
    hass.states.async_set("sensor.solar", "1500")
    hass.states.async_set("sensor.grid", "0")
    hass.states.async_set("binary_sensor.button_1", STATE_OFF)


def _presets() -> list[dict[str, Any]]:
    return [
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
        },
        {
            "label": "Grid",
            "assignments": {
                "0": {
                    "source_mode": "entity",
                    "source_entity_id": "sensor.grid",
                    "min_value": -3000.0,
                    "max_value": 3000.0,
                    "colour": None,
                }
            },
        },
    ]


def _button(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "Cycle",
        "trigger_entity_id": "binary_sensor.button_1",
        "action": "cycle_presets",
        "event_filter": None,
        "target_preset_index": None,
        "service": None,
        "service_data": None,
        "service_target": None,
    }
    return base | overrides


async def _setup(hass: HomeAssistant, **overrides: Any) -> MockConfigEntry:
    options = device_options(**({"presets": _presets()} | overrides))
    entry = MockConfigEntry(
        domain=DOMAIN, title="Meter Panel", data={}, options=options
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _press(
    hass: HomeAssistant, entity_id: str = "binary_sensor.button_1"
) -> None:
    hass.states.async_set(entity_id, STATE_ON)
    await hass.async_block_till_done()
    hass.states.async_set(entity_id, STATE_OFF)
    await hass.async_block_till_done()


# --- the four actions -------------------------------------------------------


async def test_cycle_presets_advances_and_wraps(hass: HomeAssistant) -> None:
    entry = await _setup(hass, buttons=[_button()])
    assert entry.runtime_data.active_preset_index == 0

    await _press(hass)
    assert entry.runtime_data.active_preset_index == 1

    # Two presets, so the next press wraps back to the first.
    await _press(hass)
    assert entry.runtime_data.active_preset_index == 0


async def test_set_preset_jumps_to_a_fixed_preset(hass: HomeAssistant) -> None:
    entry = await _setup(
        hass,
        buttons=[_button(action="set_preset", target_preset_index=1)],
    )

    await _press(hass)
    assert entry.runtime_data.active_preset_index == 1

    # Pressing again is idempotent, unlike cycling.
    await _press(hass)
    assert entry.runtime_data.active_preset_index == 1


async def test_fire_event_only_fires(hass: HomeAssistant) -> None:
    events: list[Event] = []
    hass.bus.async_listen(EVENT_BUTTON_PRESSED, events.append)

    entry = await _setup(hass, buttons=[_button(name="Ping", action="fire_event")])

    await _press(hass)

    assert len(events) == 1
    assert events[0].data["button"] == "Ping"
    assert events[0].data["device_name"] == "Meter Panel"
    assert events[0].data["config_entry_id"] == entry.entry_id
    # The preset is untouched.
    assert entry.runtime_data.active_preset_index == 0


async def test_call_service_runs_the_bound_service(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "light", "toggle")
    await _setup(
        hass,
        buttons=[
            _button(
                action="call_service",
                service="light.toggle",
                service_data={"transition": 2},
                service_target={"entity_id": "light.hall"},
            )
        ],
    )

    await _press(hass)

    assert len(calls) == 1
    assert calls[0].data["transition"] == 2
    assert calls[0].data["entity_id"] == "light.hall"


async def test_every_action_also_fires_the_event(hass: HomeAssistant) -> None:
    """Device triggers work for any button, whatever it is bound to."""
    events: list[Event] = []
    hass.bus.async_listen(EVENT_BUTTON_PRESSED, events.append)

    await _setup(hass, buttons=[_button()])
    await _press(hass)

    assert len(events) == 1
    assert events[0].data["button"] == "Cycle"


# --- what counts as a press -------------------------------------------------


async def test_only_the_off_to_on_edge_counts(hass: HomeAssistant) -> None:
    entry = await _setup(hass, buttons=[_button()])

    hass.states.async_set("binary_sensor.button_1", STATE_ON)
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.button_1", STATE_ON, {"noise": 1})
    await hass.async_block_till_done()

    assert entry.runtime_data.active_preset_index == 1


async def test_release_is_not_a_press(hass: HomeAssistant) -> None:
    entry = await _setup(hass, buttons=[_button()])

    hass.states.async_set("binary_sensor.button_1", STATE_OFF, {"noise": 1})
    await hass.async_block_till_done()

    assert entry.runtime_data.active_preset_index == 0


async def test_an_unavailable_trigger_is_not_a_press(hass: HomeAssistant) -> None:
    entry = await _setup(hass, buttons=[_button()])

    hass.states.async_set("binary_sensor.button_1", "unavailable")
    await hass.async_block_till_done()

    assert entry.runtime_data.active_preset_index == 0


async def test_an_event_entity_matches_its_filter(hass: HomeAssistant) -> None:
    """One physical button distinguishes single from double via the filter."""
    entry = await _setup(
        hass,
        buttons=[
            _button(
                name="Double",
                trigger_entity_id="event.button_1_clicks",
                event_filter="double",
            )
        ],
    )

    hass.states.async_set(
        "event.button_1_clicks",
        "2024-01-01T00:00:00.000+00:00",
        {"event_type": "single"},
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.active_preset_index == 0

    hass.states.async_set(
        "event.button_1_clicks",
        "2024-01-01T00:00:01.000+00:00",
        {"event_type": "double"},
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.active_preset_index == 1


async def test_an_event_entity_without_a_filter_matches_anything(
    hass: HomeAssistant,
) -> None:
    entry = await _setup(
        hass,
        buttons=[_button(trigger_entity_id="event.button_1_clicks")],
    )

    hass.states.async_set(
        "event.button_1_clicks",
        "2024-01-01T00:00:00.000+00:00",
        {"event_type": "long"},
    )
    await hass.async_block_till_done()

    assert entry.runtime_data.active_preset_index == 1


async def test_buttons_stop_on_unload(hass: HomeAssistant) -> None:
    entry = await _setup(hass, buttons=[_button()])

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    events: list[Event] = []
    hass.bus.async_listen(EVENT_BUTTON_PRESSED, events.append)
    await _press(hass)

    assert events == []


# --- device triggers --------------------------------------------------------


async def test_buttons_appear_as_device_triggers(hass: HomeAssistant) -> None:
    """A user should find their button in the automation UI, not an event name."""
    entry = await _setup(
        hass,
        buttons=[
            _button(name="Cycle"),
            _button(
                name="Long press",
                trigger_entity_id="event.button_1_clicks",
                event_filter="long",
                action="fire_event",
            ),
        ],
    )
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None

    triggers = await async_get_device_automations(
        hass, DeviceAutomationType.TRIGGER, device.id
    )
    ours = [item for item in triggers if item["domain"] == DOMAIN]

    assert {item["subtype"] for item in ours} == {"Cycle", "Long press"}
    assert all(item["type"] == "button_pressed" for item in ours)
    long_press = next(item for item in ours if item["subtype"] == "Long press")
    assert long_press["event_filter"] == "long"


async def test_a_device_trigger_fires_an_automation(hass: HomeAssistant) -> None:
    entry = await _setup(hass, buttons=[_button()])
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None

    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: [
                {
                    "trigger": {
                        "platform": "device",
                        "domain": DOMAIN,
                        "device_id": device.id,
                        "type": "button_pressed",
                        "subtype": "Cycle",
                    },
                    "action": {
                        "service": "test.automation",
                        "data": {"pressed": "yes"},
                    },
                }
            ]
        },
    )
    calls = async_mock_service(hass, "test", "automation")

    await _press(hass)

    assert len(calls) == 1
    assert calls[0].data["pressed"] == "yes"


async def test_no_triggers_for_a_device_without_buttons(hass: HomeAssistant) -> None:
    """A board with no buttons bound offers nothing to the automation UI."""
    entry = await _setup(hass, buttons=[])
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None

    triggers = await async_get_device_automations(
        hass, DeviceAutomationType.TRIGGER, device.id
    )
    assert [item for item in triggers if item["domain"] == DOMAIN] == []
