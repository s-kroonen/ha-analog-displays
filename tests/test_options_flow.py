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
    hass.states.async_set(
        "sensor.solar", "1500", {"unit_of_measurement": "W", "device_class": "power"}
    )
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
        "name": "Left",
        "output_entity_id": "number.meter_left",
        "min_update_interval": 5.0,
    }
    return base | overrides


def _suggested(result: Any) -> dict[str, Any]:
    """Return what a form is pre-filled with, as Home Assistant renders it."""
    return {
        str(key.schema): key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description and "suggested_value" in key.description
    }


async def _menu(hass: HomeAssistant, entry: MockConfigEntry, choice: str) -> Any:
    """Open the options flow and pick one menu entry."""
    result = await _open(hass, entry)
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": choice}
    )


def _calibrated_preset() -> dict[str, Any]:
    """Build a preset calibrated in kW, with two LED zones."""
    return {
        "label": "Power",
        "feedback_colour": [0, 0, 255],
        "assignments": {
            "0": {
                "source_mode": "entity",
                "source_entity_id": "sensor.solar",
                "unit": "kW",
                "min_value": 0.0,
                "max_value": 10.0,
                "colour": None,
                "mode": "gradient",
                "fade": True,
                "stops": [
                    {"at": 0.0, "colour": [255, 0, 0], "end": None},
                    {"at": 2.0, "colour": [0, 255, 0], "end": 8.0},
                ],
            }
        },
    }


def _second_display() -> list[dict[str, Any]]:
    """Build a two-display device, so the picker has something to pick."""
    displays = device_options()["displays"]
    displays.append(
        {
            "name": "Right",
            "output_entity_id": "number.meter_right",
            "light_entity_id": None,
            "min_update_interval": 5.0,
        }
    )
    return displays


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
        "edit_preset",
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
    # One display, so the picker is skipped entirely.
    assert result["step_id"] == "edit_display"

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
    result = await _menu(hass, entry, "displays")

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _display_form(output_entity_id="number.no_range")
    )

    assert result["errors"] == {"output_entity_id": "output_no_range"}


async def test_rebinding_rejects_an_output_another_display_uses(
    hass: HomeAssistant,
) -> None:
    entry = await _setup(hass, displays=_second_display())
    result = await _menu(hass, entry, "displays")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"display_index": "0"}
    )

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _display_form(output_entity_id="number.meter_right")
    )

    assert result["errors"] == {"output_entity_id": "output_already_used"}


async def test_editing_a_display_starts_from_its_current_binding(
    hass: HomeAssistant,
) -> None:
    """The whole point: an edit must not begin from an empty form."""
    displays = device_options()["displays"]
    displays[0] = displays[0] | {
        "light_entity_id": "light.led_left",
        "min_update_interval": 12.0,
    }
    entry = await _setup(hass, displays=displays)

    result = await _menu(hass, entry, "displays")

    assert result["step_id"] == "edit_display"
    assert _suggested(result) == {
        "name": "Left",
        "output_entity_id": "number.meter_left",
        "light_entity_id": "light.led_left",
        "min_update_interval": 12.0,
    }
    assert result["description_placeholders"] == {"display": "Left"}


async def test_choosing_which_display_to_edit(hass: HomeAssistant) -> None:
    """With more than one display the picker comes first, then that display."""
    entry = await _setup(hass, displays=_second_display())

    result = await _menu(hass, entry, "displays")
    assert result["step_id"] == "displays"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"display_index": "1"}
    )

    assert result["step_id"] == "edit_display"
    assert _suggested(result)["name"] == "Right"
    assert _suggested(result)["output_entity_id"] == "number.meter_right"


async def test_editing_one_field_leaves_the_rest_of_the_display_alone(
    hass: HomeAssistant,
) -> None:
    """Renaming must not silently drop the LED or the debounce interval."""
    displays = device_options()["displays"]
    displays[0] = displays[0] | {
        "light_entity_id": "light.led_left",
        "min_update_interval": 12.0,
    }
    entry = await _setup(hass, displays=displays)

    result = await _menu(hass, entry, "displays")
    # Home Assistant submits the pre-filled values back for untouched fields.
    await hass.config_entries.options.async_configure(
        result["flow_id"], _suggested(result) | {"name": "Solar"}
    )
    await hass.async_block_till_done()

    display = entry.runtime_data.device.displays[0]
    assert display.name == "Solar"
    assert display.light_entity_id == "light.led_left"
    assert display.min_update_interval.total_seconds() == 12.0


async def test_a_rejected_display_edit_keeps_what_was_typed(
    hass: HomeAssistant,
) -> None:
    """Re-showing the stored values would throw away the user's typing."""
    entry = await _setup(hass, displays=_second_display())
    result = await _menu(hass, entry, "displays")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"display_index": "0"}
    )

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _display_form(name="Solar", output_entity_id="number.meter_right"),
    )

    assert result["errors"] == {"output_entity_id": "output_already_used"}
    assert _suggested(result)["name"] == "Solar"


async def test_binding_an_led_through_the_options_flow(hass: HomeAssistant) -> None:
    """The display owns which light it drives; the preset owns how it behaves."""
    entry = await _setup(hass)
    result = await _menu(hass, entry, "displays")

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

    result = await _menu(hass, entry, "displays")
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


# --- editing a preset -------------------------------------------------------


async def test_editing_a_preset_starts_from_what_it_holds(
    hass: HomeAssistant,
) -> None:
    """Changing one threshold must not mean retyping the whole preset."""
    entry = await _setup(hass, presets=[_calibrated_preset()])

    result = await _menu(hass, entry, "edit_preset")
    assert result["step_id"] == "edit_preset"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"preset_index": "0"}
    )
    assert result["step_id"] == "edit_preset_name"
    assert _suggested(result) == {"label": "Power", "feedback_colour": [0, 0, 255]}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"label": "Power", "feedback_colour": [0, 0, 255]}
    )

    assert result["step_id"] == "edit_assignment"
    assert _suggested(result) == {
        "source_mode": "entity",
        "source_entity_id": "sensor.solar",
        "unit": "kW",
        "min_value": 0.0,
        "max_value": 10.0,
        "mode": "gradient",
        "fade": True,
        "zone_count": 2,
    }


async def test_editing_a_preset_pre_fills_each_led_zone(hass: HomeAssistant) -> None:
    entry = await _setup(hass, presets=[_calibrated_preset()])

    result = await _menu(hass, entry, "edit_preset")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"preset_index": "0"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"label": "Power"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _suggested(result)
    )

    assert result["step_id"] == "edit_zone"
    assert _suggested(result) == {"at": 0.0, "colour": [255, 0, 0]}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _suggested(result)
    )

    # The second zone carries its end value through as well.
    assert _suggested(result) == {"at": 2.0, "colour": [0, 255, 0], "end": 8.0}


async def test_editing_a_preset_keeps_everything_left_untouched(
    hass: HomeAssistant,
) -> None:
    """Raising one zone must leave the range, unit and other zone alone."""
    entry = await _setup(hass, presets=[_calibrated_preset(), _presets()[1]])

    result = await _menu(hass, entry, "edit_preset")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"preset_index": "0"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _suggested(result)
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _suggested(result)
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _suggested(result)
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _suggested(result) | {"at": 3.0}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    presets = entry.runtime_data.device.presets
    # Edited in place: still first, and the other preset is untouched.
    assert [preset.label for preset in presets] == ["Power", "Grid"]
    assignment = presets[0].assignments[0]
    assert assignment.unit == "kW"
    assert assignment.max_value == 10.0
    assert assignment.fade is True
    assert [(stop.at, stop.colour, stop.end) for stop in assignment.stops] == [
        (0.0, (255, 0, 0), None),
        (3.0, (0, 255, 0), 8.0),
    ]
    assert presets[0].feedback_colour == (0, 0, 255)


async def test_editing_a_preset_can_rename_it(hass: HomeAssistant) -> None:
    entry = await _setup(hass)

    result = await _menu(hass, entry, "edit_preset")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"preset_index": "1"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"label": "Import"}
    )
    await hass.config_entries.options.async_configure(
        result["flow_id"], _suggested(result)
    )
    await hass.async_block_till_done()

    labels = [preset.label for preset in entry.runtime_data.device.presets]
    assert labels == ["Power", "Import"]


async def test_emptying_a_preset_while_editing_is_rejected(
    hass: HomeAssistant,
) -> None:
    """Clearing every source would leave a preset that drives nothing."""
    entry = await _setup(hass)

    result = await _menu(hass, entry, "edit_preset")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"preset_index": "0"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"label": "Power"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"source_mode": "entity", "min_value": 0.0, "max_value": 100.0},
    )

    assert result["step_id"] == "edit_assignment"
    assert result["errors"] == {"base": "preset_drives_nothing"}

    # The walk was wound back, so the form can be filled in again.
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
    assert entry.runtime_data.device.presets[0].assignments[0].max_value == 100.0


# --- what adding a preset could not do before --------------------------------


async def test_adding_a_preset_with_led_zones(hass: HomeAssistant) -> None:
    """Zones are collected on their own pages here too, not silently dropped."""
    entry = await _setup(hass)

    result = await _menu(hass, entry, "add_preset")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"label": "Battery", "feedback_colour": [255, 255, 0]}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "source_mode": "entity",
            "source_entity_id": "sensor.solar",
            "min_value": 0.0,
            "max_value": 100.0,
            "mode": "gradient",
            "zone_count": 1,
        },
    )

    assert result["step_id"] == "edit_zone"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"at": 20.0, "colour": [255, 0, 0]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    preset = entry.runtime_data.device.presets[-1]
    assert preset.label == "Battery"
    # The blink colour used to be collected and then thrown away.
    assert preset.feedback_colour == (255, 255, 0)
    assert preset.assignments[0].stops[0].at == 20.0


async def test_a_rejected_assignment_keeps_what_was_typed(
    hass: HomeAssistant,
) -> None:
    """One bad field must not cost the user the rest of the page."""
    entry = await _setup(hass, presets=[_calibrated_preset()])

    result = await _menu(hass, entry, "edit_preset")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"preset_index": "0"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"label": "Power"}
    )

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _suggested(result) | {"unit": "°C", "max_value": 40.0}
    )

    assert result["errors"] == {"unit": "incompatible_unit"}
    assert _suggested(result)["max_value"] == 40.0
    assert _suggested(result)["unit"] == "°C"
