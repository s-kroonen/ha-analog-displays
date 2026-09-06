"""Shared test helpers."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntry
from pytest_homeassistant_custom_component.common import async_fire_time_changed

DEBOUNCE = timedelta(seconds=5)


async def settle(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    interval: timedelta = DEBOUNCE,
) -> None:
    """Let a debounced write fire, then wait for it to complete."""
    await hass.async_block_till_done()
    freezer.tick(interval + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def device_for(hass: HomeAssistant, entry: ConfigEntry) -> DeviceEntry:
    """Return the single device a config entry registered.

    Looked up by config entry, not by identifier: Home Assistant 2026.9
    deprecated identifier lookup because identifiers are not unique across
    config entries.
    """
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert devices, "the config entry registered no device"
    return devices[0]
