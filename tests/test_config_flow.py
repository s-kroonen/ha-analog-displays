"""Config flow tests: the happy path, the wizard bypass, and rejections."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.analog_displays.const import DOMAIN


@pytest.fixture(autouse=True)
def _entities(hass: HomeAssistant) -> None:
    """Publish the entities the flow's selectors and validation expect."""
    hass.states.async_set(
        "number.meter_left", "0", {"min": 0.0, "max": 1.0, "step": 0.001}
    )
    hass.states.async_set(
        "number.meter_right", "0", {"min": 0.0, "max": 1.0, "step": 0.001}
    )
    hass.states.async_set("number.no_range", "0", {})
    hass.states.async_set("sensor.solar", "1500", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.grid", "-200", {"unit_of_measurement": "W"})
    hass.states.async_set("light.led_left", "off", {})


async def _start(hass: HomeAssistant) -> str:
    """Run the user step and stop on the hardware branch."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Meter Panel"}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "hardware"
    assert set(result["menu_options"]) == {"wizard", "bind_displays"}
    return str(result["flow_id"])


async def _configure(
    hass: HomeAssistant, flow_id: str, user_input: dict[str, Any] | None
) -> Any:
    return await hass.config_entries.flow.async_configure(flow_id, user_input)


def _display(
    name: str, entity_id: str, *, add_another: bool = False, **extra: Any
) -> dict[str, Any]:
    return {
        "name": name,
        "output_entity_id": entity_id,
        "mode": "preset",
        "fade": False,
        "min_update_interval": 5.0,
        "add_another": add_another,
        **extra,
    }


def _assignment(source: str | None, low: float = 0.0, high: float = 3000.0) -> dict:
    data: dict[str, Any] = {"min_value": low, "max_value": high}
    if source is not None:
        data["source_entity_id"] = source
    return data


# --- the bypass path --------------------------------------------------------


async def test_bypass_path_binds_existing_hardware(hass: HomeAssistant) -> None:
    """The wizard must never be a prerequisite for binding entities."""
    flow_id = await _start(hass)

    result = await _configure(hass, flow_id, {"next_step_id": "bind_displays"})
    assert result["step_id"] == "bind_displays"

    result = await _configure(hass, flow_id, _display("Left", "number.meter_left"))
    assert result["step_id"] == "preset"

    result = await _configure(hass, flow_id, {"label": "Power"})
    assert result["step_id"] == "preset_assign"

    result = await _configure(hass, flow_id, _assignment("sensor.solar"))
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "preset_done"

    result = await _configure(hass, flow_id, {"next_step_id": "finish"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Meter Panel"

    options = result["options"]
    assert options["name"] == "Meter Panel"
    assert len(options["displays"]) == 1
    assert options["displays"][0]["output_entity_id"] == "number.meter_left"
    assert options["presets"][0]["label"] == "Power"
    assert options["presets"][0]["assignments"]["0"]["source_entity_id"] == (
        "sensor.solar"
    )
    # No wizard was run, so no hardware profile is stored.
    assert options["hardware_profile"] is None


async def test_wizard_branch_reaches_the_same_binding_steps(
    hass: HomeAssistant,
) -> None:
    """The wizard is a detour; it hands over to the same binding steps."""
    flow_id = await _start(hass)

    result = await _configure(hass, flow_id, {"next_step_id": "wizard"})
    assert result["step_id"] == "bind_displays"


# --- multiple displays and presets -----------------------------------------


async def test_two_displays_and_a_sparse_preset(hass: HomeAssistant) -> None:
    """A preset need not drive every display."""
    flow_id = await _start(hass)
    await _configure(hass, flow_id, {"next_step_id": "bind_displays"})

    await _configure(
        hass, flow_id, _display("Left", "number.meter_left", add_another=True)
    )
    result = await _configure(hass, flow_id, _display("Right", "number.meter_right"))
    assert result["step_id"] == "preset"

    await _configure(hass, flow_id, {"label": "Power"})
    # Display 0 gets a source; display 1 is deliberately left unused.
    result = await _configure(hass, flow_id, _assignment("sensor.solar"))
    assert result["step_id"] == "preset_assign"
    result = await _configure(hass, flow_id, _assignment(None))
    assert result["step_id"] == "preset_done"

    result = await _configure(hass, flow_id, {"next_step_id": "finish"})
    assert result["type"] is FlowResultType.CREATE_ENTRY

    assignments = result["options"]["presets"][0]["assignments"]
    assert set(assignments) == {"0"}


async def test_adding_a_second_preset(hass: HomeAssistant) -> None:
    flow_id = await _start(hass)
    await _configure(hass, flow_id, {"next_step_id": "bind_displays"})
    await _configure(hass, flow_id, _display("Left", "number.meter_left"))

    await _configure(hass, flow_id, {"label": "Power"})
    await _configure(hass, flow_id, _assignment("sensor.solar"))

    result = await _configure(hass, flow_id, {"next_step_id": "preset"})
    assert result["step_id"] == "preset"

    await _configure(hass, flow_id, {"label": "Grid"})
    await _configure(hass, flow_id, _assignment("sensor.grid", -3000.0, 3000.0))
    result = await _configure(hass, flow_id, {"next_step_id": "finish"})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    labels = [preset["label"] for preset in result["options"]["presets"]]
    assert labels == ["Power", "Grid"]


# --- rejections -------------------------------------------------------------


async def test_rejects_output_without_a_range(hass: HomeAssistant) -> None:
    """A number entity with no min/max gives the backend nothing to scale into."""
    flow_id = await _start(hass)
    await _configure(hass, flow_id, {"next_step_id": "bind_displays"})

    result = await _configure(hass, flow_id, _display("Left", "number.no_range"))
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"output_entity_id": "output_no_range"}


async def test_rejects_missing_output_entity(hass: HomeAssistant) -> None:
    flow_id = await _start(hass)
    await _configure(hass, flow_id, {"next_step_id": "bind_displays"})

    result = await _configure(hass, flow_id, _display("Left", "number.gone"))
    assert result["errors"] == {"output_entity_id": "output_unavailable"}


async def test_rejects_two_displays_sharing_an_output(hass: HomeAssistant) -> None:
    flow_id = await _start(hass)
    await _configure(hass, flow_id, {"next_step_id": "bind_displays"})
    await _configure(
        hass, flow_id, _display("Left", "number.meter_left", add_another=True)
    )

    result = await _configure(hass, flow_id, _display("Also Left", "number.meter_left"))
    assert result["errors"] == {"output_entity_id": "output_already_used"}


async def test_rejects_min_equal_to_max(hass: HomeAssistant) -> None:
    """An empty calibration range has no mapping onto the needle."""
    flow_id = await _start(hass)
    await _configure(hass, flow_id, {"next_step_id": "bind_displays"})
    await _configure(hass, flow_id, _display("Left", "number.meter_left"))
    await _configure(hass, flow_id, {"label": "Broken"})

    result = await _configure(hass, flow_id, _assignment("sensor.solar", 50.0, 50.0))
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"max_value": "same_min_max"}


async def test_rejects_a_preset_that_drives_nothing(hass: HomeAssistant) -> None:
    flow_id = await _start(hass)
    await _configure(hass, flow_id, {"next_step_id": "bind_displays"})
    await _configure(hass, flow_id, _display("Left", "number.meter_left"))
    await _configure(hass, flow_id, {"label": "Empty"})

    result = await _configure(hass, flow_id, _assignment(None))
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "preset_drives_nothing"}


async def test_led_binding_is_stored(hass: HomeAssistant) -> None:
    flow_id = await _start(hass)
    await _configure(hass, flow_id, {"next_step_id": "bind_displays"})
    await _configure(
        hass,
        flow_id,
        _display(
            "Left",
            "number.meter_left",
            light_entity_id="light.led_left",
            mode="gradient",
            fade=True,
        ),
    )
    await _configure(hass, flow_id, {"label": "Power"})
    await _configure(hass, flow_id, _assignment("sensor.solar"))
    result = await _configure(hass, flow_id, {"next_step_id": "finish"})

    led = result["options"]["displays"][0]["led"]
    assert led["light_entity_id"] == "light.led_left"
    assert led["mode"] == "gradient"
    assert led["fade"] is True
    # Gradient mode is only valid with a stop, so one is seeded.
    assert len(led["stops"]) == 1
