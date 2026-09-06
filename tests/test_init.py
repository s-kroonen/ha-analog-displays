"""Smoke tests for entry setup and unload."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.analog_displays.const import DOMAIN


async def test_setup_and_unload_entry(hass: HomeAssistant) -> None:
    """An entry sets up and unloads cleanly."""
    entry = MockConfigEntry(domain=DOMAIN, title="Meter Panel", data={})
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
