"""Per-display staleness reporting."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import AnalogDisplaysDisplayEntity

if TYPE_CHECKING:
    from . import AnalogDisplaysConfigEntry
    from .controller import DeviceRuntime, DisplayController


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AnalogDisplaysConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a staleness sensor for every display."""
    runtime = entry.runtime_data
    async_add_entities(
        DisplayStaleBinarySensor(entry.entry_id, runtime, controller)
        for controller in runtime.controllers
    )


class DisplayStaleBinarySensor(AnalogDisplaysDisplayEntity, BinarySensorEntity):
    """On when a display is holding a value over a dead source.

    This is how staleness is surfaced. The indicator LED is deliberately not
    used for it — LEDs show the preset or the value, never an error.
    """

    _attr_translation_key = "display_stale"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, entry_id: str, runtime: DeviceRuntime, controller: DisplayController
    ) -> None:
        """Name the sensor after its display."""
        super().__init__(entry_id, runtime, controller)
        self._attr_unique_id = f"{entry_id}_display_{controller.index}_stale"
        self._attr_translation_placeholders = {"display": controller.display.name}

    @property
    def is_on(self) -> bool:
        """Whether the displayed value is being held over a dead source."""
        return self.controller.stale
