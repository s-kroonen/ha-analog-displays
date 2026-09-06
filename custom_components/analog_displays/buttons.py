"""Binding physical buttons to actions.

Buttons are a device feature, not a per-display one, which matches how they
are wired: a handful of buttons on the front panel driving whatever the whole
board is doing.

Every press fires ``analog_displays_button_pressed`` regardless of the action
configured, which is what lets :mod:`.device_trigger` offer buttons in the
automation UI without the user ever learning an event name. The configured
action then happens on top of that.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.event import ATTR_EVENT_TYPE
from homeassistant.const import (
    ATTR_DEVICE_ID,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    ACTION_CALL_SERVICE,
    ACTION_CYCLE_PRESETS,
    ACTION_SET_PRESET,
    EVENT_BUTTON_PRESSED,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from .controller import DeviceRuntime
    from .models import ButtonBinding

_LOGGER = logging.getLogger(__name__)

ATTR_BUTTON = "button"
ATTR_EVENT_FILTER = "event_filter"

_NOT_A_PRESS = (STATE_UNAVAILABLE, STATE_UNKNOWN, "", None)


class ButtonDispatcher:
    """Watches every bound trigger entity and runs the configured action."""

    def __init__(self, runtime: DeviceRuntime) -> None:
        """Bind the dispatcher to a device's runtime."""
        self.runtime = runtime
        self.hass = runtime.hass
        self._unsubscribes: list[Callable[[], None]] = []

    @callback
    def async_start(self) -> None:
        """Subscribe to every bound trigger entity."""
        for index, button in enumerate(self.runtime.device.buttons):
            if not button.trigger_entity_id:
                continue
            self._unsubscribes.append(
                async_track_state_change_event(
                    self.hass,
                    [button.trigger_entity_id],
                    self._make_handler(index, button),
                )
            )

    @callback
    def async_shutdown(self) -> None:
        """Drop every subscription."""
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    def _make_handler(
        self, index: int, button: ButtonBinding
    ) -> Callable[[Event[EventStateChangedData]], None]:
        """Build the state-change handler for one button binding."""

        @callback
        def handle(event: Event[EventStateChangedData]) -> None:
            if _is_press(event, button):
                self.hass.async_create_task(self.async_press(index))

        return handle

    async def async_press(self, index: int) -> None:
        """Run a button as though it had been pressed."""
        try:
            button = self.runtime.device.buttons[index]
        except IndexError:
            return

        self._async_fire_event(button)

        if button.action == ACTION_CYCLE_PRESETS:
            await self.runtime.async_set_preset(self.runtime.active_preset_index + 1)
        elif button.action == ACTION_SET_PRESET:
            if button.target_preset_index is not None:
                await self.runtime.async_set_preset(button.target_preset_index)
        elif button.action == ACTION_CALL_SERVICE:
            await self._async_call_service(button)

    @callback
    def _async_fire_event(self, button: ButtonBinding) -> None:
        """Announce the press so automations and device triggers can see it."""
        self.hass.bus.async_fire(
            EVENT_BUTTON_PRESSED,
            {
                ATTR_DEVICE_ID: self._device_id(),
                "config_entry_id": self.runtime.entry_id,
                "device_name": self.runtime.device.name,
                ATTR_BUTTON: button.name,
                ATTR_EVENT_FILTER: button.event_filter,
            },
        )

    async def _async_call_service(self, button: ButtonBinding) -> None:
        """Run the arbitrary service a button was bound to."""
        if not button.service or "." not in button.service:
            return

        domain, service = button.service.split(".", 1)
        try:
            await self.hass.services.async_call(
                domain,
                service,
                dict(button.service_data or {}),
                blocking=False,
                target=dict(button.service_target or {}),
            )
        except Exception:
            _LOGGER.exception(
                "Button %s failed to call %s", button.name, button.service
            )

    def _device_id(self) -> str | None:
        """Return this board's Home Assistant device id, if it is registered.

        Looked up by config entry rather than by identifier: identifiers are
        not unique across config entries, and Home Assistant 2026.9 deprecated
        searching by them for exactly that reason.
        """
        registry = dr.async_get(self.hass)
        devices = dr.async_entries_for_config_entry(registry, self.runtime.entry_id)
        return devices[0].id if devices else None


def _is_press(event: Event[EventStateChangedData], button: ButtonBinding) -> bool:
    """Decide whether a state change counts as a press of this button.

    A ``binary_sensor`` presses on the off-to-on edge. An ``event`` entity
    presses whenever it publishes, and its ``event_type`` is matched against
    the binding's filter — that is how one physical button distinguishes a
    single press from a double or a long one.
    """
    new_state = event.data["new_state"]
    if new_state is None or new_state.state in _NOT_A_PRESS:
        return False

    event_type = new_state.attributes.get(ATTR_EVENT_TYPE)
    if event_type is not None:
        return button.event_filter in (None, event_type)

    old_state = event.data["old_state"]
    if new_state.state != STATE_ON:
        return False
    return old_state is None or old_state.state == STATE_OFF


def button_description(button: ButtonBinding) -> dict[str, Any]:
    """Summarize a binding for diagnostics and device triggers."""
    return {"name": button.name, "event_filter": button.event_filter}
