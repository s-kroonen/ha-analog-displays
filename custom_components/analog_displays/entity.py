"""Shared entity plumbing.

Every entity this integration creates belongs to the one Home Assistant device
that represents the physical board, so the integrations page shows a single
device with its displays as entities beneath it — not one device per display.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN

if TYPE_CHECKING:
    from .controller import DeviceRuntime, DisplayController


def device_info(entry_id: str, runtime: DeviceRuntime) -> DeviceInfo:
    """Describe the physical board every entity of this entry hangs off."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name=runtime.device.name,
        manufacturer="Analog Displays",
        model=(
            "Custom hardware"
            if runtime.device.hardware_profile is None
            else runtime.device.hardware_profile.board
        ),
    )


class AnalogDisplaysEntity(Entity):
    """Base for entities that belong to the device as a whole."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry_id: str, runtime: DeviceRuntime) -> None:
        """Attach the entity to the device this config entry represents."""
        self.runtime = runtime
        self._entry_id = entry_id
        self._attr_device_info = device_info(entry_id, runtime)


class AnalogDisplaysDisplayEntity(AnalogDisplaysEntity):
    """Base for entities that describe one display of the device."""

    def __init__(
        self, entry_id: str, runtime: DeviceRuntime, controller: DisplayController
    ) -> None:
        """Attach the entity to one display's controller."""
        super().__init__(entry_id, runtime)
        self.controller = controller

    async def async_added_to_hass(self) -> None:
        """Follow the controller so the entity updates when the display does."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.controller.async_add_listener(self.async_write_ha_state)
        )
