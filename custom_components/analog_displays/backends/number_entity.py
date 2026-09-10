"""Backend that drives a display through a Home Assistant ``number`` entity.

This is the only hardware-facing path in the integration, and it is not
hardware-facing at all: it calls ``number.set_value``. Any firmware, board or
protocol that exposes a ``number`` entity works, which is the whole point of
keeping ESPHome behind an entity boundary.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.number.const import (
    ATTR_MAX,
    ATTR_MIN,
    ATTR_STEP,
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant

from ..normalization import to_target
from . import (
    BackendCapabilities,
    NormalizedValue,
    OutputBackend,
    register_backend,
)

if TYPE_CHECKING:
    from homeassistant.core import State

_LOGGER = logging.getLogger(__name__)

BACKEND_NUMBER_ENTITY = "number_entity"

_CAPABILITIES = BackendCapabilities(analog=True, text=False)


class UnknownOutputRangeError(RuntimeError):
    """Raised when the target entity does not advertise a usable range."""


@register_backend(BACKEND_NUMBER_ENTITY)
class NumberEntityBackend(OutputBackend):
    """Write a normalized value into a ``number`` entity's own range."""

    def __init__(
        self,
        hass: HomeAssistant,
        entity_id: str,
        low: float = 0.0,
        high: float = 1.0,
    ) -> None:
        """Bind the backend to a target ``number`` entity.

        ``low``/``high`` trim for the meter itself, as fractions of the target's
        range: the drive at which this movement rests and the drive at which it
        reads full scale. They belong to the hardware, so they apply under every
        preset, unlike the preset's own range which is in real units.
        """
        self._hass = hass
        self._entity_id = entity_id
        self._low = low
        self._high = high

    @property
    def entity_id(self) -> str:
        """The ``number`` entity this backend writes to."""
        return self._entity_id

    @property
    def capabilities(self) -> BackendCapabilities:
        """A moving-coil meter renders position, not text."""
        return _CAPABILITIES

    def _target_range(self) -> tuple[float, float, float | None]:
        """Read the target's range at write time, not at config time.

        Reading it live is what lets a 0.0-1.0 ESPHome template number,
        someone else's 0-100 and a 0-255 dimmer all work unconfigured, and
        keeps working if the target's range changes after a reflash.
        """
        state: State | None = self._hass.states.get(self._entity_id)
        if state is None:
            raise UnknownOutputRangeError(f"{self._entity_id} has no state")

        try:
            out_min = float(state.attributes[ATTR_MIN])
            out_max = float(state.attributes[ATTR_MAX])
        except (KeyError, TypeError, ValueError) as err:
            raise UnknownOutputRangeError(
                f"{self._entity_id} does not expose numeric min/max attributes"
            ) from err

        if out_min == out_max:
            raise UnknownOutputRangeError(
                f"{self._entity_id} has an empty range ({out_min})"
            )

        step = state.attributes.get(ATTR_STEP)
        try:
            return out_min, out_max, None if step is None else float(step)
        except (TypeError, ValueError):
            return out_min, out_max, None

    async def write(self, value: NormalizedValue) -> None:
        """Scale into the target's range and call ``number.set_value``."""
        out_min, out_max, step = self._target_range()
        drive = self._low + value.normalized * (self._high - self._low)
        target = to_target(drive, out_min, out_max, step)

        _LOGGER.debug(
            "Writing %s to %s (normalized %.3f)",
            target,
            self._entity_id,
            value.normalized,
        )
        await self._hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: self._entity_id, ATTR_VALUE: target},
            blocking=True,
        )

    async def clear(self) -> None:
        """Drive the output to the bottom of its range."""
        await self.write(NormalizedValue(normalized=0.0))
