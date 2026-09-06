"""The Analog Displays integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .controller import DeviceRuntime
from .models import AnalogDisplaysConfigError, Device
from .services import async_register_services

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


async def async_unload_entry(
    hass: HomeAssistant, entry: AnalogDisplaysConfigEntry
) -> bool:
    """Unload a config entry."""
    entry.runtime_data.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
