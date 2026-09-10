"""Per-display runtime logic.

A :class:`DeviceRuntime` owns one :class:`DisplayController` per display and
keeps them pointed at the device's active preset. Controllers read a source,
normalize it, and hand the result to an output backend — rate limited, because
a power sensor may update every second and hammering a mechanical movement is
pointless and shortens its life.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.light import ATTR_RGB_COLOR
from homeassistant.components.light.const import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_state_change_event

from .backends import NormalizedValue
from .backends.number_entity import NumberEntityBackend, UnknownOutputRangeError
from .buttons import ButtonDispatcher
from .const import (
    LED_MODE_GRADIENT,
    LED_MODE_PRESET,
    SOURCE_MODE_ENTITY,
    SOURCE_MODE_STATISTIC,
)
from .coordinator import StatisticsCoordinator
from .led import resolve_colour
from .models import (
    ColourStop,
    Device,
    Display,
    Preset,
    PresetAssignment,
    RGBColor,
)
from .normalization import normalize
from .repairs import async_clear_source_issue, async_raise_source_issue
from .units import convert

if TYPE_CHECKING:
    from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)

_NON_NUMERIC = (STATE_UNAVAILABLE, STATE_UNKNOWN, None, "")

#: Two flashes reads as deliberate feedback rather than a glitch.
BLINK_COUNT = 2
BLINK_INTERVAL = 0.2


class DisplayController:
    """Drives one display from whatever the active preset points it at."""

    def __init__(
        self,
        runtime: DeviceRuntime,
        index: int,
        display: Display,
    ) -> None:
        """Bind a controller to one display of a device."""
        self.hass = runtime.hass
        self.entry_id = runtime.entry_id
        self.runtime = runtime
        self.index = index
        self.display = display

        self._backend = NumberEntityBackend(
            self.hass,
            display.output_entity_id,
            display.output_low,
            display.output_high,
        )
        self._unsubscribe: Callable[[], None] | None = None
        self._listeners: list[Callable[[], None]] = []

        self._last_value: NormalizedValue | None = None
        self._last_colour: RGBColor | None = None
        self._colour_written = False
        self._stale = False
        self._output_error_logged = False
        self._light_error_logged = False

        # Trailing edge, not leading: coalesce a burst of source updates and
        # write the newest value once the burst settles, so the needle ends up
        # showing reality rather than whatever arrived first.
        self._debouncer = Debouncer(
            self.hass,
            _LOGGER,
            cooldown=display.min_update_interval.total_seconds(),
            immediate=False,
            function=self.async_refresh,
        )

    # --- state exposed to entities -----------------------------------------

    @property
    def device(self) -> Device:
        """The device configuration this display belongs to."""
        return self.runtime.device

    @property
    def assignment(self) -> PresetAssignment | None:
        """What the active preset points this display at, if anything."""
        preset = self.runtime.active_preset
        if preset is None:
            return None
        return preset.assignment_for(self.index)

    @property
    def last_value(self) -> NormalizedValue | None:
        """The most recent value written, held across source outages."""
        return self._last_value

    @property
    def stale(self) -> bool:
        """Whether the displayed value is being held over a dead source."""
        return self._stale

    @property
    def source_entity_id(self) -> str | None:
        """The entity currently feeding this display, if it reads an entity."""
        assignment = self.assignment
        if assignment is None or assignment.source_mode != SOURCE_MODE_ENTITY:
            return None
        return assignment.source_entity_id

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a callback to run whenever this display's state changes."""
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            self._listeners.remove(listener)

        return remove

    @callback
    def _notify(self) -> None:
        """Tell every registered entity that something changed."""
        for listener in list(self._listeners):
            listener()

    # --- lifecycle ----------------------------------------------------------

    async def async_start(self) -> None:
        """Subscribe to the active source and write its current value."""
        self._async_subscribe()
        await self.async_refresh()

    @callback
    def async_shutdown(self) -> None:
        """Drop the subscription and cancel any pending debounced write."""
        self._async_unsubscribe()
        self._debouncer.async_shutdown()

    @callback
    def _async_subscribe(self) -> None:
        """Watch the active preset's source for push updates."""
        source = self.source_entity_id
        if source:
            self._unsubscribe = async_track_state_change_event(
                self.hass, [source], self._handle_source_change
            )

    @callback
    def _async_unsubscribe(self) -> None:
        """Stop watching the current source."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    async def async_preset_changed(self) -> None:
        """Re-point at the new active preset and write immediately.

        A preset change is a deliberate user action, so it bypasses the
        debounce: the needle must move the moment the preset does.
        """
        self._async_unsubscribe()
        self._async_subscribe()
        await self.async_refresh()

    @callback
    def _handle_source_change(self, event: Event[EventStateChangedData]) -> None:
        """Queue a rate-limited write in response to a push from the source."""
        self._debouncer.async_schedule_call()

    # --- reading and writing ------------------------------------------------

    def _read_source(self) -> tuple[float, str | None] | None:
        """Read the active source, or ``None`` if it has nothing usable."""
        assignment = self.assignment
        if assignment is not None and assignment.source_mode == SOURCE_MODE_STATISTIC:
            return self._read_statistic(assignment)

        source = self.source_entity_id
        if not source:
            return None

        state = self.hass.states.get(source)
        if state is None or state.state in _NON_NUMERIC:
            return None

        try:
            raw = float(state.state)
        except (TypeError, ValueError):
            return None

        return self._to_display_unit(
            raw,
            state.attributes.get("unit_of_measurement"),
            state.attributes.get("device_class"),
        )

    def _read_statistic(
        self, assignment: PresetAssignment
    ) -> tuple[float, str | None] | None:
        """Read this display's statistic out of the device's coordinator."""
        coordinator = self.runtime.coordinator
        if coordinator is None or coordinator.data is None:
            return None

        value = coordinator.data.get(self.index)
        if value is None:
            return None

        # Statistics carry no unit of their own, so borrow the source entity's
        # if it still exists — a text backend will want it.
        unit: str | None = None
        if assignment.statistic_entity_id:
            state = self.hass.states.get(assignment.statistic_entity_id)
            if state is not None:
                unit = state.attributes.get("unit_of_measurement")

        device_class: str | None = None
        if assignment.statistic_entity_id:
            state = self.hass.states.get(assignment.statistic_entity_id)
            if state is not None:
                device_class = state.attributes.get("device_class")

        return self._to_display_unit(value, unit, device_class)

    def _to_display_unit(
        self, raw: float, source_unit: str | None, device_class: str | None
    ) -> tuple[float, str | None] | None:
        """Express a reading in the unit this assignment is calibrated in.

        A sensor publishing watts against a range typed in kilowatts is wrong
        by a factor of a thousand, so a conversion that cannot be done reads as
        no reading at all: the needle holds and the repair issue explains why,
        rather than the display confidently showing nonsense.
        """
        assignment = self.assignment
        if assignment is None:
            return raw, source_unit

        target = assignment.unit
        if target is None or source_unit == target:
            return raw, source_unit

        converted = convert(raw, source_unit, target, device_class)
        if converted is None:
            _LOGGER.error(
                "Display %s is calibrated in %s but %s reports %s, which cannot "
                "be converted",
                self.display.name,
                target,
                self.source_entity_id or assignment.statistic_entity_id,
                source_unit or "no unit",
            )
            return None

        return converted, target

    async def async_refresh(self) -> None:
        """Re-read the source and write the result to the display."""
        assignment = self.assignment
        if assignment is None:
            # No preset points here: this display is simply not in use.
            self._async_clear_stale()
            await self._write(NormalizedValue(normalized=0.0))
            await self._async_update_led()
            self._notify()
            return

        reading = self._read_source()
        if reading is None:
            self._async_mark_stale(assignment)
            return

        self._async_clear_stale()
        raw, unit = reading
        await self._write(
            NormalizedValue(
                normalized=normalize(raw, assignment.min_value, assignment.max_value),
                raw=raw,
                unit=unit,
            )
        )
        await self._async_update_led()
        self._notify()

    @callback
    def _async_mark_stale(self, assignment: PresetAssignment) -> None:
        """Hold the needle where it is and raise a repair issue.

        Never snap to zero: a stale but plausible reading is far better than a
        confidently wrong one. The LED is deliberately left alone — LEDs show
        the preset or the value, never an error.
        """
        if self._stale:
            return

        self._stale = True
        source = assignment.source_entity_id or "(unset)"
        preset = self.runtime.active_preset
        _LOGGER.error(
            "Source %s for display %s is unavailable; holding the last value",
            source,
            self.display.name,
        )
        async_raise_source_issue(
            self.hass,
            self.entry_id,
            self.index,
            device_name=self.device.name,
            display_name=self.display.name,
            preset_label="" if preset is None else preset.label,
            source_entity_id=source,
        )
        self._notify()

    @callback
    def _async_clear_stale(self) -> None:
        """Clear the repair issue once the source produces values again."""
        if not self._stale:
            return

        self._stale = False
        async_clear_source_issue(self.hass, self.entry_id, self.index)
        _LOGGER.info("Source for display %s recovered", self.display.name)

    # --- indicator LED ------------------------------------------------------

    def _normalized_stops(self, assignment: PresetAssignment) -> list[ColourStop]:
        """Convert real-unit zone positions onto the 0.0-1.0 scale.

        Thresholds are configured the way a person describes a meter — "red
        from 2 kW" — while :func:`.led.resolve_colour` works purely in
        normalized space. Converting here keeps that function, and its tests,
        entirely unaware of units.
        """
        low, high = assignment.min_value, assignment.max_value
        return [
            ColourStop(
                at=normalize(stop.at, low, high),
                colour=stop.colour,
                end=None if stop.end is None else normalize(stop.end, low, high),
            )
            for stop in assignment.stops
        ]

    def _resolve_colour(self) -> RGBColor | None:
        """Work out what colour this display's LED should be showing."""
        if self.display.light_entity_id is None:
            return None

        assignment = self.assignment
        if assignment is None:
            # Not in use under this preset: the LED goes dark with the needle.
            return None

        if assignment.led_mode == LED_MODE_PRESET:
            return assignment.colour
        if assignment.led_mode != LED_MODE_GRADIENT:
            return None

        value = self._last_value
        if value is None:
            return None
        return resolve_colour(
            self._normalized_stops(assignment), value.normalized, assignment.fade
        )

    async def _async_set_light(self, colour: RGBColor | None) -> None:
        """Drive the indicator LED to a colour, or turn it off.

        An unreachable LED must not take the config entry down with it, and
        must not stop the needle moving: the meter is the point, the LED is
        decoration.
        """
        light = self.display.light_entity_id
        if light is None:
            return

        service = SERVICE_TURN_OFF if colour is None else SERVICE_TURN_ON
        data: dict[str, Any] = {ATTR_ENTITY_ID: light}
        if colour is not None:
            data[ATTR_RGB_COLOR] = list(colour)

        try:
            await self.hass.services.async_call(
                LIGHT_DOMAIN, service, data, blocking=True
            )
        except HomeAssistantError as err:
            if not self._light_error_logged:
                self._light_error_logged = True
                _LOGGER.error(  # noqa: TRY400 - a traceback per write is noise
                    "Cannot drive the indicator LED %s: %s", light, err
                )
            return

        self._light_error_logged = False

    async def _async_update_led(self) -> None:
        """Push the resolved colour to the LED, skipping redundant calls."""
        if self.display.light_entity_id is None:
            return

        colour = self._resolve_colour()
        if self._colour_written and colour == self._last_colour:
            return

        self._last_colour = colour
        self._colour_written = True
        await self._async_set_light(colour)

    async def async_blink(self, colour: RGBColor) -> None:
        """Blink ``colour`` twice, then settle back to the resolved colour.

        Used to confirm a preset change on a board with no screen. The final
        state is re-resolved rather than restored from a snapshot, so a source
        update landing mid-blink still leaves the LED showing the truth.
        """
        if self.display.light_entity_id is None or self.assignment is None:
            return

        for index in range(BLINK_COUNT):
            if index:
                await asyncio.sleep(BLINK_INTERVAL)
            await self._async_set_light(colour)
            await asyncio.sleep(BLINK_INTERVAL)
            await self._async_set_light(None)

        # Force the next update through: the LED is off, so the cached colour
        # no longer describes reality.
        self._colour_written = False
        await self._async_update_led()

    async def _write(self, value: NormalizedValue) -> None:
        """Hand a value to the output backend, tolerating a bad target.

        A board that is offline, gone, or not exposing a usable range must not
        take the config entry down with it — the rest of the device keeps
        working and the needle simply holds.
        """
        try:
            await self._backend.write(value)
        except (UnknownOutputRangeError, HomeAssistantError) as err:
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
    """Everything one config entry needs while it is loaded.

    The active preset lives here rather than on :class:`Device` because the
    device model is frozen: it is what was persisted, while this is what is
    currently showing.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str, device: Device) -> None:
        """Build a controller for each of the device's displays."""
        self.hass = hass
        self.entry_id = entry_id
        self.device = device
        self.active_preset_index = device.active_preset_index
        self._preset_listeners: list[Callable[[], None]] = []
        self._coordinator_unsubscribe: Callable[[], None] | None = None
        self.controllers = [
            DisplayController(self, index, display)
            for index, display in enumerate(device.displays)
        ]

        # Only pay for polling if a preset actually reads statistics.
        self.coordinator: StatisticsCoordinator | None = (
            StatisticsCoordinator(hass, self) if device.uses_statistics else None
        )
        self.buttons = ButtonDispatcher(self)

    @property
    def active_preset(self) -> Preset | None:
        """The preset currently driving the displays."""
        if not self.device.presets:
            return None
        return self.device.presets[self.active_preset_index % len(self.device.presets)]

    @callback
    def async_add_preset_listener(
        self, listener: Callable[[], None]
    ) -> Callable[[], None]:
        """Register a callback to run whenever the active preset changes."""
        self._preset_listeners.append(listener)

        @callback
        def remove() -> None:
            self._preset_listeners.remove(listener)

        return remove

    async def async_start(self) -> None:
        """Start polling if needed, then start every display controller."""
        if self.coordinator is not None:
            await self.coordinator.async_config_entry_first_refresh()
            self._coordinator_unsubscribe = self.coordinator.async_add_listener(
                self._handle_coordinator_update
            )
        for controller in self.controllers:
            await controller.async_start()

    @callback
    def async_shutdown(self) -> None:
        """Stop polling and stop every display controller."""
        self.buttons.async_shutdown()
        if self._coordinator_unsubscribe is not None:
            self._coordinator_unsubscribe()
            self._coordinator_unsubscribe = None
        for controller in self.controllers:
            controller.async_shutdown()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Write freshly polled statistics to the displays that use them."""
        self.hass.async_create_task(self.async_refresh())

    async def async_refresh(self) -> None:
        """Force every display to re-read and re-write, bypassing debounce."""
        for controller in self.controllers:
            await controller.async_refresh()

    async def async_set_preset(self, index: int) -> None:
        """Switch the whole device to another preset and write immediately."""
        if not self.device.presets:
            return
        self.active_preset_index = index % len(self.device.presets)
        # The coordinator only polls what the active preset needs, so a preset
        # change has to re-poll before the displays can be written.
        if self.coordinator is not None:
            await self.coordinator.async_refresh()
        for controller in self.controllers:
            await controller.async_preset_changed()
        for listener in list(self._preset_listeners):
            listener()

        preset = self.active_preset
        if preset is not None and preset.feedback_colour is not None:
            # After the write, not before: the blink confirms a change that has
            # already happened, and must not delay the needles moving.
            await asyncio.gather(
                *(
                    controller.async_blink(preset.feedback_colour)
                    for controller in self.controllers
                )
            )
