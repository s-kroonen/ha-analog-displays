"""Polling for statistic-backed presets.

Entity sources push, so they need no coordinator. Recorder statistics do not,
so one coordinator per device polls whichever displays the active preset
points at a statistic — and only those, because a preset that reads no
statistics should cost nothing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, SOURCE_MODE_STATISTIC
from .statistics import async_fetch_statistic

if TYPE_CHECKING:
    from .controller import DeviceRuntime

_LOGGER = logging.getLogger(__name__)


class StatisticsCoordinator(DataUpdateCoordinator[dict[int, float | None]]):
    """Polls the recorder for every statistic the active preset needs."""

    def __init__(self, hass: HomeAssistant, runtime: DeviceRuntime) -> None:
        """Poll at the device's configured statistics interval."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} statistics",
            update_interval=runtime.device.statistics_interval,
        )
        self.runtime = runtime

    async def _async_update_data(self) -> dict[int, float | None]:
        """Read one statistic per display the active preset points at."""
        preset = self.runtime.active_preset
        if preset is None:
            return {}

        results: dict[int, float | None] = {}
        for index, assignment in preset.assignments.items():
            if assignment.source_mode != SOURCE_MODE_STATISTIC:
                continue
            statistic_id = assignment.statistic_entity_id
            if not statistic_id or not assignment.statistic_type:
                continue
            results[index] = await async_fetch_statistic(
                self.hass,
                statistic_id,
                assignment.statistic_type,
                assignment.statistic_period or "24h",
            )
        return results
