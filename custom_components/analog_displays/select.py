"""The preset selector.

One select per device, not per display: a preset is a scene across the whole
board, so switching it re-points every display at once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .entity import AnalogDisplaysEntity

if TYPE_CHECKING:
    from . import AnalogDisplaysConfigEntry
    from .controller import DeviceRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AnalogDisplaysConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the device's preset selector."""
    async_add_entities([PresetSelect(entry.entry_id, entry.runtime_data)])


class PresetSelect(AnalogDisplaysEntity, SelectEntity, RestoreEntity):
    """Selects which preset the whole device is showing."""

    _attr_translation_key = "preset"

    def __init__(self, entry_id: str, runtime: DeviceRuntime) -> None:
        """Offer every configured preset as an option."""
        super().__init__(entry_id, runtime)
        self._attr_unique_id = f"{entry_id}_preset"
        self._attr_options = [preset.label for preset in runtime.device.presets]

    @property
    def current_option(self) -> str | None:
        """The label of the preset currently driving the displays."""
        preset = self.runtime.active_preset
        return None if preset is None else preset.label

    async def async_added_to_hass(self) -> None:
        """Restore the preset that was active before the restart."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in self._attr_options:
            index = self._attr_options.index(last_state.state)
            if index != self.runtime.active_preset_index:
                await self.runtime.async_set_preset(index)

        self.async_on_remove(
            self.runtime.async_add_preset_listener(self.async_write_ha_state)
        )

    async def async_select_option(self, option: str) -> None:
        """Switch the device to the chosen preset."""
        if option not in self._attr_options:
            return
        await self.runtime.async_set_preset(self._attr_options.index(option))
        self.async_write_ha_state()
