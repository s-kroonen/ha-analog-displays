"""Sensors describing what each display is currently showing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory
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
    """Set up a value and a normalized sensor for every display."""
    runtime = entry.runtime_data
    entities: list[SensorEntity] = []
    for controller in runtime.controllers:
        entities.append(DisplayValueSensor(entry.entry_id, runtime, controller))
        entities.append(DisplayNormalizedSensor(entry.entry_id, runtime, controller))
    async_add_entities(entities)


class DisplayValueSensor(AnalogDisplaysDisplayEntity, SensorEntity):
    """The raw source reading behind a display, in the source's own unit."""

    _attr_translation_key = "display_value"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, entry_id: str, runtime: DeviceRuntime, controller: DisplayController
    ) -> None:
        """Name the sensor after its display."""
        super().__init__(entry_id, runtime, controller)
        self._attr_unique_id = f"{entry_id}_display_{controller.index}_value"
        self._attr_translation_placeholders = {"display": controller.display.name}

    @property
    def native_value(self) -> float | None:
        """The last raw reading written to this display."""
        value = self.controller.last_value
        return None if value is None else value.raw

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Follow the source's unit, which changes with the preset."""
        value = self.controller.last_value
        return None if value is None else value.unit


class DisplayNormalizedSensor(AnalogDisplaysDisplayEntity, SensorEntity):
    """Where the needle actually sits, as a percentage of full scale."""

    _attr_translation_key = "display_normalized"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 1

    def __init__(
        self, entry_id: str, runtime: DeviceRuntime, controller: DisplayController
    ) -> None:
        """Name the sensor after its display."""
        super().__init__(entry_id, runtime, controller)
        self._attr_unique_id = f"{entry_id}_display_{controller.index}_normalized"
        self._attr_translation_placeholders = {"display": controller.display.name}

    @property
    def native_value(self) -> float | None:
        """The needle position, 0-100 %."""
        value = self.controller.last_value
        return None if value is None else round(value.normalized * 100, 2)
