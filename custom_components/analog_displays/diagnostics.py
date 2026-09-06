"""Diagnostics for a configured device.

The stored configuration is almost entirely entity ids and numbers, so most of
it is safe to share. Entity ids are redacted anyway: they routinely carry room
and household names, and nothing in a bug report needs them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from . import AnalogDisplaysConfigEntry

TO_REDACT = {
    "output_entity_id",
    "light_entity_id",
    "source_entity_id",
    "statistic_entity_id",
    "trigger_entity_id",
    "service_target",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AnalogDisplaysConfigEntry
) -> dict[str, Any]:
    """Describe how this device is configured and what it is doing now."""
    runtime = entry.runtime_data
    active = runtime.active_preset

    return {
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "state": {
            "active_preset_index": runtime.active_preset_index,
            "active_preset_label": None if active is None else active.label,
            "uses_statistics": runtime.device.uses_statistics,
            "polling": runtime.coordinator is not None,
            "displays": [
                {
                    "name": controller.display.name,
                    "assigned": controller.assignment is not None,
                    "stale": controller.stale,
                    "normalized": (
                        None
                        if controller.last_value is None
                        else controller.last_value.normalized
                    ),
                    "raw": (
                        None
                        if controller.last_value is None
                        else controller.last_value.raw
                    ),
                    "unit": (
                        None
                        if controller.last_value is None
                        else controller.last_value.unit
                    ),
                }
                for controller in runtime.controllers
            ],
        },
    }
