"""Debounce, source-outage handling and repair issues."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.analog_displays.const import DOMAIN
from custom_components.analog_displays.repairs import source_issue_id
from tests.helpers import settle
from tests.test_init import device_options


@pytest.fixture(autouse=True)
def set_value_calls(hass: HomeAssistant) -> list[ServiceCall]:
    """Capture number.set_value calls."""
    return async_mock_service(hass, "number", "set_value")


@pytest.fixture(autouse=True)
def _output(hass: HomeAssistant) -> None:
    """Publish a 0-1 template number as the display output."""
    hass.states.async_set(
        "number.meter_left", "0", {"min": 0.0, "max": 1.0, "step": 0.001}
    )


async def _setup(hass: HomeAssistant, **overrides: Any) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Meter Panel", data={}, options=device_options(**overrides)
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# --- debounce ---------------------------------------------------------------


async def test_rapid_updates_coalesce_into_one_write(
    hass: HomeAssistant,
    set_value_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """A sensor updating every second must not hammer the movement."""
    hass.states.async_set("sensor.solar", "0")
    await _setup(hass)
    set_value_calls.clear()

    for value in ("300", "600", "900", "1200", "1500"):
        hass.states.async_set("sensor.solar", value)
        await hass.async_block_till_done()

    # Still inside the 5 s window: nothing has been written yet.
    assert set_value_calls == []

    await settle(hass, freezer)
    assert len(set_value_calls) == 1


async def test_the_latest_value_wins(
    hass: HomeAssistant,
    set_value_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Trailing edge, not leading: the needle ends up showing reality."""
    hass.states.async_set("sensor.solar", "0")
    await _setup(hass)
    set_value_calls.clear()

    for value in ("3000", "1500", "600"):
        hass.states.async_set("sensor.solar", value)
        await hass.async_block_till_done()

    await settle(hass, freezer)

    assert len(set_value_calls) == 1
    assert set_value_calls[0].data["value"] == pytest.approx(0.2)


async def test_updates_further_apart_than_the_interval_all_write(
    hass: HomeAssistant,
    set_value_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    hass.states.async_set("sensor.solar", "0")
    await _setup(hass)
    set_value_calls.clear()

    for value in ("600", "1200", "1800"):
        hass.states.async_set("sensor.solar", value)
        await settle(hass, freezer)

    assert [call.data["value"] for call in set_value_calls] == [
        pytest.approx(0.2),
        pytest.approx(0.4),
        pytest.approx(0.6),
    ]


async def test_a_custom_interval_is_honoured(
    hass: HomeAssistant,
    set_value_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    hass.states.async_set("sensor.solar", "0")
    displays = device_options()["displays"]
    displays[0]["min_update_interval"] = 60.0
    await _setup(hass, displays=displays)
    set_value_calls.clear()

    hass.states.async_set("sensor.solar", "1500")
    await settle(hass, freezer, timedelta(seconds=5))
    assert set_value_calls == []

    await settle(hass, freezer, timedelta(seconds=60))
    assert len(set_value_calls) == 1


async def test_preset_change_bypasses_the_debounce(
    hass: HomeAssistant, set_value_calls: list[ServiceCall]
) -> None:
    """A preset change is a deliberate action; the needle moves at once."""
    hass.states.async_set("sensor.solar", "1500")
    hass.states.async_set("sensor.grid", "-200")
    entry = await _setup(hass, presets=_two_presets())
    set_value_calls.clear()

    await entry.runtime_data.async_set_preset(1)

    assert len(set_value_calls) == 1
    # -200 on a -3000..3000 scale.
    assert set_value_calls[0].data["value"] == pytest.approx(0.4667, abs=1e-3)


async def test_preset_change_resubscribes_to_the_new_source(
    hass: HomeAssistant,
    set_value_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """After a preset change, the old source must no longer drive the display."""
    hass.states.async_set("sensor.solar", "1500")
    hass.states.async_set("sensor.grid", "0")
    entry = await _setup(hass, presets=_two_presets())

    await entry.runtime_data.async_set_preset(1)
    set_value_calls.clear()

    hass.states.async_set("sensor.solar", "3000")
    await settle(hass, freezer)
    assert set_value_calls == []

    hass.states.async_set("sensor.grid", "3000")
    await settle(hass, freezer)
    assert len(set_value_calls) == 1


def _two_presets() -> list[dict[str, Any]]:
    """Build a Power preset and a Grid preset over the same single display."""
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


# --- source outages and repairs ---------------------------------------------


async def test_outage_holds_the_value_and_raises_a_repair_issue(
    hass: HomeAssistant,
    set_value_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
    issue_registry: ir.IssueRegistry,
) -> None:
    hass.states.async_set("sensor.solar", "1500")
    entry = await _setup(hass)
    controller = entry.runtime_data.controllers[0]
    set_value_calls.clear()

    hass.states.async_set("sensor.solar", "unavailable")
    await settle(hass, freezer)

    # The needle is held, not zeroed.
    assert set_value_calls == []
    assert controller.stale is True
    assert controller.last_value is not None
    assert controller.last_value.normalized == pytest.approx(0.5)

    issue = issue_registry.async_get_issue(DOMAIN, source_issue_id(entry.entry_id, 0))
    assert issue is not None
    assert issue.translation_placeholders == {
        "device": "Meter Panel",
        "display": "Left",
        "preset": "Power",
        "entity_id": "sensor.solar",
    }


async def test_the_repair_issue_clears_when_the_source_recovers(
    hass: HomeAssistant,
    set_value_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
    issue_registry: ir.IssueRegistry,
) -> None:
    hass.states.async_set("sensor.solar", "1500")
    entry = await _setup(hass)
    controller = entry.runtime_data.controllers[0]

    hass.states.async_set("sensor.solar", "unknown")
    await settle(hass, freezer)
    assert issue_registry.async_get_issue(DOMAIN, source_issue_id(entry.entry_id, 0))

    set_value_calls.clear()
    hass.states.async_set("sensor.solar", "2250")
    await settle(hass, freezer)

    assert controller.stale is False
    assert (
        issue_registry.async_get_issue(DOMAIN, source_issue_id(entry.entry_id, 0))
        is None
    )
    assert set_value_calls[-1].data["value"] == pytest.approx(0.75)


async def test_a_source_missing_at_startup_is_reported(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry
) -> None:
    """The source never existing is the same problem as it going away."""
    entry = await _setup(hass)

    assert entry.runtime_data.controllers[0].stale is True
    assert issue_registry.async_get_issue(DOMAIN, source_issue_id(entry.entry_id, 0))


async def test_an_unassigned_display_is_never_stale(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry
) -> None:
    """Not being used by a preset is not an error condition."""
    hass.states.async_set(
        "number.meter_right", "0", {"min": 0.0, "max": 1.0, "step": 0.001}
    )
    hass.states.async_set("sensor.solar", "1500")
    displays = device_options()["displays"]
    displays.append(
        {
            "name": "Right",
            "output_entity_id": "number.meter_right",
            "led": None,
            "min_update_interval": 5.0,
        }
    )
    entry = await _setup(hass, displays=displays)

    assert entry.runtime_data.controllers[1].stale is False
    assert (
        issue_registry.async_get_issue(DOMAIN, source_issue_id(entry.entry_id, 1))
        is None
    )


async def test_the_led_is_not_used_to_signal_staleness(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """LEDs show the preset or the value, never an error."""
    off_calls = async_mock_service(hass, "light", "turn_off")
    on_calls = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set("sensor.solar", "1500")
    hass.states.async_set("light.led_left", "off")

    displays = device_options()["displays"]
    displays[0]["led"] = {
        "light_entity_id": "light.led_left",
        "mode": "preset",
        "stops": [],
        "fade": False,
    }
    presets = device_options()["presets"]
    presets[0]["assignments"]["0"]["colour"] = [0, 255, 0]
    await _setup(hass, displays=displays, presets=presets)

    # The preset colour is showing.
    assert on_calls[-1].data["rgb_color"] == [0, 255, 0]
    off_calls.clear()
    on_calls.clear()

    hass.states.async_set("sensor.solar", "unavailable")
    await settle(hass, freezer)

    assert off_calls == []
    assert on_calls == []


# --- listeners --------------------------------------------------------------


async def test_listeners_are_notified_and_can_unsubscribe(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    hass.states.async_set("sensor.solar", "1500")
    entry = await _setup(hass)
    controller = entry.runtime_data.controllers[0]

    seen: list[int] = []
    remove = controller.async_add_listener(lambda: seen.append(1))

    hass.states.async_set("sensor.solar", "2000")
    await settle(hass, freezer)
    assert len(seen) == 1

    remove()
    hass.states.async_set("sensor.solar", "2500")
    await settle(hass, freezer)
    assert len(seen) == 1


async def test_shutdown_cancels_a_pending_write(
    hass: HomeAssistant,
    set_value_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Unloading must not write after the entry is gone."""
    hass.states.async_set("sensor.solar", "1500")
    entry = await _setup(hass)
    set_value_calls.clear()

    hass.states.async_set("sensor.solar", "3000")
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    freezer.tick(timedelta(seconds=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert set_value_calls == []
