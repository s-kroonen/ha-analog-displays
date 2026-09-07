"""Editing a device after setup."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.analog_displays.const import CONFIG_VERSION, DOMAIN
from tests.test_buttons import _presets
from tests.test_init import device_options

PROFILE = {
    "board": "esp32-devkit-v1",
    "displays": [{"pin": 25, "led": None}],
    "buttons": [],
}


@pytest.fixture(autouse=True)
def set_value_calls(hass: HomeAssistant) -> list[ServiceCall]:
    return async_mock_service(hass, "number", "set_value")


@pytest.fixture(autouse=True)
def _states(hass: HomeAssistant) -> None:
    for entity_id in ("number.meter_left", "number.meter_right"):
        hass.states.async_set(entity_id, "0", {"min": 0.0, "max": 1.0, "step": 0.001})
    hass.states.async_set("number.no_range", "0", {})
    hass.states.async_set("sensor.solar", "1500")
    hass.states.async_set("sensor.grid", "0")
    hass.states.async_set("light.led_left", "off")


async def _setup(hass: HomeAssistant, **overrides: Any) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Meter Panel",
        data={},
        options=device_options(**({"presets": _presets()} | overrides)),
        version=CONFIG_VERSION,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _open(hass: HomeAssistant, entry: MockConfigEntry) -> Any:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    return result


def _display_form(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "display_index": "0",
        "name": "Left",
        "output_entity_id": "number.meter_left",
        "min_update_interval": 5.0,
    }
    return base | overrides


# --- the menu ---------------------------------------------------------------


async def test_the_menu_hides_export_without_a_wizard_profile(
    hass: HomeAssistant,
) -> None:
    entry = await _setup(hass)
    result = await _open(hass, entry)

    assert "export_yaml" not in result["menu_options"]
    assert set(result["menu_options"]) == {
        "displays",
        "add_preset",
        "remove_preset",
        "intervals",
    }


async def test_the_menu_offers_export_with_a_wizard_profile(
    hass: HomeAssistant,
) -> None:
    entry = await _setup(hass, hardware_profile=PROFILE)
    result = await _open(hass, entry)

    assert "export_yaml" in result["menu_options"]


# --- displays ---------------------------------------------------------------


async def test_rebinding_a_display_reloads_the_entry(
    hass: HomeAssistant, set_value_calls: list[ServiceCall]
) -> None:
    """An edit must reload cleanly, not leave stale bindings behind."""
    entry = await _setup(hass)
    result = await _open(hass, entry)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "displays"}
    )
    assert result["step_id"] == "displays"

    set_value_calls.clear()
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _display_form(name="Solar", output_entity_id="number.meter_right"),
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.device.displays[0].name == "Solar"
    # The new output is being written, which proves the reload took effect.
    assert set_value_calls[-1].data["entity_id"] == "number.meter_right"


async def test_rebinding_rejects_an_output_without_a_range(
    hass: HomeAssistant,
) -> None:
    entry = await _setup(hass)
    result = await _open(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "displays"}
    )

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _display_form(output_entity_id="number.no_range")
    )

    assert result["errors"] == {"output_entity_id": "output_no_range"}


async def test_rebinding_rejects_an_output_another_display_uses(
    hass: HomeAssistant,
) -> None:
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
    result = await _open(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "displays"}
    )

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _display_form(output_entity_id="number.meter_right")
    )

    assert result["errors"] == {"output_entity_id": "output_already_used"}


async def test_binding_an_led_through_the_options_flow(hass: HomeAssistant) -> None:
    """The display owns which light it drives; the preset owns how it behaves."""
    entry = await _setup(hass)
    result = await _open(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "displays"}
    )

    await hass.config_entries.options.async_configure(
        result["flow_id"], _display_form(light_entity_id="light.led_left")
    )
    await hass.async_block_till_done()

    assert entry.runtime_data.device.displays[0].light_entity_id == "light.led_left"


# --- presets ----------------------------------------------------------------


async def test_adding_a_preset(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    result = await _open(hass, entry)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_preset"}
    )
    assert result["step_id"] == "add_preset"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"label": "Battery"}
    )
    assert result["step_id"] == "edit_assignment"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "source_mode": "entity",
            "source_entity_id": "sensor.solar",
            "min_value": 0.0,
            "max_value": 100.0,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    labels = [preset.label for preset in entry.runtime_data.device.presets]
    assert labels == ["Power", "Grid", "Battery"]


async def test_adding_a_preset_that_drives_nothing_is_rejected(
    hass: HomeAssistant,
) -> None:
    entry = await _setup(hass)
    result = await _open(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_preset"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"label": "Empty"}
    )

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"source_mode": "entity", "min_value": 0.0, "max_value": 100.0},
    )

    assert result["errors"] == {"base": "preset_drives_nothing"}


async def test_a_ninth_preset_is_refused(hass: HomeAssistant) -> None:
    presets = [
        {"label": f"Preset {index}", "assignments": _presets()[0]["assignments"]}
        for index in range(8)
    ]
    entry = await _setup(hass, presets=presets)
    result = await _open(hass, entry)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_preset"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "too_many_presets"


async def test_removing_a_preset(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    result = await _open(hass, entry)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_preset"}
    )
    assert result["step_id"] == "remove_preset"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"preset_index": "0"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    labels = [preset.label for preset in entry.runtime_data.device.presets]
    assert labels == ["Grid"]


async def test_removing_the_active_preset_keeps_the_index_valid(
    hass: HomeAssistant,
) -> None:
    entry = await _setup(hass, active_preset_index=1)
    result = await _open(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_preset"}
    )

    await hass.config_entries.options.async_configure(
        result["flow_id"], {"preset_index": "1"}
    )
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.active_preset_index == 0


async def test_removing_the_last_preset_is_refused(hass: HomeAssistant) -> None:
    """A device must always have something to show."""
    entry = await _setup(hass, presets=[_presets()[0]])
    result = await _open(hass, entry)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_preset"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "last_preset"


# --- intervals and export ---------------------------------------------------


async def test_changing_the_statistics_interval(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    result = await _open(hass, entry)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "intervals"}
    )
    assert result["step_id"] == "intervals"

    await hass.config_entries.options.async_configure(
        result["flow_id"], {"statistics_interval": 900.0}
    )
    await hass.async_block_till_done()

    assert entry.runtime_data.device.statistics_interval.total_seconds() == 900.0


async def test_re_exporting_uses_the_current_names(hass: HomeAssistant) -> None:
    """Renaming a display and re-exporting must produce matching YAML."""
    entry = await _setup(hass, hardware_profile=PROFILE)

    result = await _open(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "displays"}
    )
    await hass.config_entries.options.async_configure(
        result["flow_id"], _display_form(name="Solar")
    )
    await hass.async_block_till_done()

    result = await _open(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "export_yaml"}
    )

    yaml_text = result["description_placeholders"]["yaml"]
    assert 'name: "Solar"' in yaml_text
    assert "GPIO25" in yaml_text
