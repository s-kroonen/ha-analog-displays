"""Per-display runtime logic.

A :class:`DeviceRuntime` owns one :class:`DisplayController` per display and
keeps them pointed at the active preset. Controllers are what actually read a
source, normalize it and hand it to an output backend.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .backends import NormalizedValue
from .backends.number_entity import NumberEntityBackend, UnknownOutputRangeError
from .const import SOURCE_MODE_ENTITY
from .models import Device, Display, PresetAssignment
from .normalization import normalize

if TYPE_CHECKING:
    from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)

_NON_NUMERIC = (STATE_UNAVAILABLE, STATE_UNKNOWN, None, "")


class DisplayController:
    """Drives one display from whatever the active preset points it at."""

    def __init__(
        self, hass: HomeAssistant, device: Device, index: int, display: Display
    ) -> None:
        """Bind a controller to one display of a device."""
        self.hass = hass
        self.index = index
        self.display = display
        self._device = device
        self._backend = NumberEntityBackend(hass, display.output_entity_id)
        self._unsubscribe: Callable[[], None] | None = None
        self._last_value: NormalizedValue | None = None
        self._output_error_logged = False

    @property
    def assignment(self) -> PresetAssignment | None:
        """What the active preset points this display at, if anything."""
        preset = self._device.active_preset
        if preset is None:
            return None
        return preset.assignment_for(self.index)

    @property
    def last_value(self) -> NormalizedValue | None:
        """The most recent value written, held across source outages."""
        return self._last_value

    # --- subscription ------------------------------------------------------

    async def async_start(self) -> None:
        """Subscribe to the active source and write its current value."""
        assignment = self.assignment
        if assignment is not None and assignment.source_mode == SOURCE_MODE_ENTITY:
            source = assignment.source_entity_id
            if source:
                self._unsubscribe = async_track_state_change_event(
                    self.hass, [source], self._handle_source_change
                )
        await self.async_refresh()

    @callback
    def async_stop(self) -> None:
        """Drop the source subscription."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    @callback
    def _handle_source_change(self, event: Event[EventStateChangedData]) -> None:
        """React to a push update from the source entity."""
        self.hass.async_create_task(self.async_refresh())

    # --- reading and writing ------------------------------------------------

    def _read_source(self) -> tuple[float, str | None] | None:
        """Read the active source, or ``None`` if it has nothing usable."""
        assignment = self.assignment
        if assignment is None or assignment.source_mode != SOURCE_MODE_ENTITY:
            return None

        source = assignment.source_entity_id
        if not source:
            return None

        state = self.hass.states.get(source)
        if state is None or state.state in _NON_NUMERIC:
            return None

        try:
            raw = float(state.state)
        except (TypeError, ValueError):
            return None

        return raw, state.attributes.get("unit_of_measurement")

    async def async_refresh(self) -> None:
        """Re-read the source and write the result to the display."""
        assignment = self.assignment
        if assignment is None:
            # This display is not in use under the active preset.
            await self._write(NormalizedValue(normalized=0.0))
            return

        reading = self._read_source()
        if reading is None:
            # Hold the last displayed value: a stale but plausible reading
            # beats a needle confidently pinned to zero.
            return

        raw, unit = reading
        value = NormalizedValue(
            normalized=normalize(raw, assignment.min_value, assignment.max_value),
            raw=raw,
            unit=unit,
        )
        await self._write(value)

    async def _write(self, value: NormalizedValue) -> None:
        """Hand a value to the output backend, tolerating a bad target."""
        try:
            await self._backend.write(value)
        except UnknownOutputRangeError as err:
            # Writes repeat every few seconds, so log the cause once and stay
            # quiet until the target recovers rather than flooding the log.
            if not self._output_error_logged:
                self._output_error_logged = True
                _LOGGER.error(  # noqa: TRY400 - a traceback per write is noise
                    "Cannot write to %s: %s", self.display.output_entity_id, err
                )
            return

        self._output_error_logged = False
        self._last_value = value


class DeviceRuntime:
    """Everything one config entry needs while it is loaded."""

    def __init__(self, hass: HomeAssistant, device: Device) -> None:
        """Build a controller for each of the device's displays."""
        self.hass = hass
        self.device = device
        self.controllers = [
            DisplayController(hass, device, index, display)
            for index, display in enumerate(device.displays)
        ]

    async def async_start(self) -> None:
        """Start every display controller."""
        for controller in self.controllers:
            await controller.async_start()

    @callback
    def async_stop(self) -> None:
        """Stop every display controller."""
        for controller in self.controllers:
            controller.async_stop()
