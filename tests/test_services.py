"""The integration's services."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.analog_displays.const import DOMAIN
from tests.helpers import device_for
from tests.test_buttons import _presets
from tests.test_init import device_options

PROFILE = {
    "board": "esp32-devkit-v1",
    "displays": [{"pin": 25, "led": None}],
    "buttons": [{"pin": 4, "multi_click": True}],
}


@pytest.fixture(autouse=True)
def set_value_calls(hass: HomeAssistant) -> list[ServiceCall]:
    return async_mock_service(hass, "number", "set_value")


@pytest.fixture(autouse=True)
def _states(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "number.meter_left", "0", {"min": 0.0, "max": 1.0, "step": 0.001}
    )
    hass.states.async_set("sensor.solar", "1500")
    hass.states.async_set("sensor.grid", "0")


async def _setup(hass: HomeAssistant, **overrides: Any) -> tuple[MockConfigEntry, str]:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Meter Panel",
        data={},
        options=device_options(**({"presets": _presets()} | overrides)),
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    device = device_for(hass, entry)
    return entry, device.id


async def _call(hass: HomeAssistant, service: str, **data: Any) -> Any:
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=service == "export_yaml"
    )


async def test_set_preset_by_label(hass: HomeAssistant) -> None:
    entry, device_id = await _setup(hass)

    await _call(hass, "set_preset", device_id=device_id, preset="Grid")

    assert entry.runtime_data.active_preset_index == 1


async def test_set_preset_by_index(hass: HomeAssistant) -> None:
    entry, device_id = await _setup(hass)

    await _call(hass, "set_preset", device_id=device_id, preset=1)

    assert entry.runtime_data.active_preset_index == 1


async def test_set_preset_by_numeric_string(hass: HomeAssistant) -> None:
    """The service schema accepts text, so "1" must mean index 1."""
    entry, device_id = await _setup(hass)

    await _call(hass, "set_preset", device_id=device_id, preset="1")

    assert entry.runtime_data.active_preset_index == 1


async def test_next_and_previous_wrap_around(hass: HomeAssistant) -> None:
    entry, device_id = await _setup(hass)

    await _call(hass, "next_preset", device_id=device_id)
    assert entry.runtime_data.active_preset_index == 1

    await _call(hass, "next_preset", device_id=device_id)
    assert entry.runtime_data.active_preset_index == 0

    await _call(hass, "previous_preset", device_id=device_id)
    assert entry.runtime_data.active_preset_index == 1


async def test_refresh_rewrites_the_displays(
    hass: HomeAssistant, set_value_calls: list[ServiceCall]
) -> None:
    _, device_id = await _setup(hass)
    set_value_calls.clear()

    await _call(hass, "refresh", device_id=device_id)

    assert len(set_value_calls) == 1
    assert set_value_calls[0].data["value"] == pytest.approx(0.5)


async def test_export_yaml_returns_the_configuration(hass: HomeAssistant) -> None:
    """A response service, so it can be run straight from Developer Tools."""
    _, device_id = await _setup(hass, hardware_profile=PROFILE)

    response = await _call(hass, "export_yaml", device_id=device_id)

    assert response is not None
    yaml_text = response["yaml"]
    assert "GPIO25" in yaml_text
    assert "number.set" not in yaml_text
    # Display and button names come from the live configuration.
    assert 'name: "Left"' in yaml_text


async def test_export_yaml_refuses_without_a_wizard_profile(
    hass: HomeAssistant,
) -> None:
    _, device_id = await _setup(hass)

    with pytest.raises(ServiceValidationError, match="wizard"):
        await _call(hass, "export_yaml", device_id=device_id)


@pytest.mark.parametrize(
    "service", ["set_preset", "next_preset", "previous_preset", "refresh"]
)
async def test_an_unknown_device_is_rejected(hass: HomeAssistant, service: str) -> None:
    await _setup(hass)
    data: dict[str, Any] = {"device_id": "not-a-device"}
    if service == "set_preset":
        data["preset"] = "Power"

    with pytest.raises(ServiceValidationError, match="No Analog Displays device"):
        await hass.services.async_call(DOMAIN, service, data, blocking=True)


async def test_an_unknown_preset_is_rejected(hass: HomeAssistant) -> None:
    _, device_id = await _setup(hass)

    with pytest.raises(ServiceValidationError, match="No preset"):
        await _call(hass, "set_preset", device_id=device_id, preset="Nonexistent")


async def test_an_out_of_range_preset_index_is_rejected(hass: HomeAssistant) -> None:
    _, device_id = await _setup(hass)

    with pytest.raises(ServiceValidationError, match="No preset"):
        await _call(hass, "set_preset", device_id=device_id, preset=9)


async def test_services_are_registered_once(hass: HomeAssistant) -> None:
    await _setup(hass)

    for service in (
        "set_preset",
        "next_preset",
        "previous_preset",
        "refresh",
        "export_yaml",
    ):
        assert hass.services.has_service(DOMAIN, service)
