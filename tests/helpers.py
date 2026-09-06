"""Shared test helpers."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
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
