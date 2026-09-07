"""The Analog Displays integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONFIG_VERSION
from .controller import DeviceRuntime
from .models import AnalogDisplaysConfigError, Device
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

type AnalogDisplaysConfigEntry = ConfigEntry[DeviceRuntime]

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SENSOR,
]


async def async_setup_entry(
    hass: HomeAssistant, entry: AnalogDisplaysConfigEntry
) -> bool:
    """Set up Analog Displays from a config entry."""
    try:
        device = Device.from_dict(dict(entry.options))
        device.validate()
    except (AnalogDisplaysConfigError, KeyError, TypeError, ValueError) as err:
        raise ConfigEntryNotReady(f"Stored configuration is invalid: {err}") from err

    runtime = DeviceRuntime(hass, entry.entry_id, device)
    entry.runtime_data = runtime

    async_register_services(hass)

    await runtime.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Buttons are started after the platforms so a press has somewhere to land.
    runtime.buttons.async_start()
    return True


async def async_migrate_entry(
    hass: HomeAssistant, entry: AnalogDisplaysConfigEntry
) -> bool:
    """Bring a stored configuration up to the current shape.

    Version 1 kept LED behaviour on the display, with threshold positions as a
    fraction of full scale. Version 2 moves that behaviour onto each preset
    assignment, where the range and unit live, so thresholds can be written in
    real units. A migrated entry must behave exactly as it did before, so the
    old normalized positions are converted back into value-space against the
    assignment they now belong to, and no unit conversion is introduced.
    """
    if entry.version >= CONFIG_VERSION:
        return True

    _LOGGER.debug("Migrating %s from version %s", entry.title, entry.version)
    hass.config_entries.async_update_entry(
        entry,
        options=_migrate_v1_to_v2(dict(entry.options)),
        version=CONFIG_VERSION,
    )
    return True


def _migrate_v1_to_v2(options: dict[str, Any]) -> dict[str, Any]:
    """Move LED behaviour off the display and onto each preset assignment."""
    displays = [dict(display) for display in options.get("displays", [])]

    # Remember each display's old LED settings before flattening it.
    led_by_display: dict[int, dict[str, Any]] = {}
    for index, display in enumerate(displays):
        led = display.pop("led", None)
        if led:
            led_by_display[index] = led
            display["light_entity_id"] = led.get("light_entity_id")
        else:
            display["light_entity_id"] = None

    presets = []
    for preset in options.get("presets", []):
        assignments = {}
        for key, assignment in preset.get("assignments", {}).items():
            moved = dict(assignment)
            led = led_by_display.get(int(key))
            if led:
                moved["mode"] = led.get("mode", "preset")
                moved["fade"] = led.get("fade", False)
                moved["stops"] = [
                    _denormalize_stop(stop, moved) for stop in led.get("stops", [])
                ]
            # The old behaviour read the source in its own unit; keep that.
            moved.setdefault("unit", None)
            assignments[key] = moved
        presets.append({**preset, "assignments": assignments, "feedback_colour": None})

    return {**options, "displays": displays, "presets": presets}


def _denormalize_stop(
    stop: dict[str, Any], assignment: dict[str, Any]
) -> dict[str, Any]:
    """Turn a 0.0-1.0 threshold position back into the assignment's units."""
    low = float(assignment.get("min_value", 0.0))
    high = float(assignment.get("max_value", 100.0))
    span = high - low

    def to_value(position: Any) -> Any:
        if position is None:
            return None
        return low + float(position) * span

    return {
        "at": to_value(stop.get("at", 0.0)),
        "colour": stop.get("colour"),
        "end": to_value(stop.get("end")),
    }


async def async_unload_entry(
    hass: HomeAssistant, entry: AnalogDisplaysConfigEntry
) -> bool:
    """Unload a config entry."""
    entry.runtime_data.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
