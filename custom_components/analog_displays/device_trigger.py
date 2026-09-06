"""Device triggers for button presses.

These exist so a user can pick "Button 1 was pressed" out of the automation UI
without ever learning that ``analog_displays_button_pressed`` is the event
behind it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_DOMAIN,
    CONF_EVENT_DATA,
    CONF_PLATFORM,
    CONF_TYPE,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
import voluptuous as vol

from .buttons import ATTR_BUTTON, ATTR_EVENT_FILTER
from .const import DOMAIN, EVENT_BUTTON_PRESSED

if TYPE_CHECKING:
    from homeassistant.helpers.typing import ConfigType

#: The event trigger platform names this key itself; it is not in const.
CONF_EVENT_TYPE = "event_type"

CONF_SUBTYPE = "subtype"
TRIGGER_PRESSED = "button_pressed"

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): TRIGGER_PRESSED,
        vol.Required(CONF_SUBTYPE): cv.string,
        vol.Optional(ATTR_EVENT_FILTER): vol.Any(cv.string, None),
    }
)


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, Any]]:
    """Offer one trigger per button bound to this device."""
    registry = dr.async_get(hass)
    device = registry.async_get(device_id)
    if device is None:
        return []

    triggers: list[dict[str, Any]] = []
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            continue

        runtime = getattr(entry, "runtime_data", None)
        if runtime is None:
            continue

        for button in runtime.device.buttons:
            trigger: dict[str, Any] = {
                CONF_PLATFORM: "device",
                CONF_DOMAIN: DOMAIN,
                CONF_DEVICE_ID: device_id,
                CONF_TYPE: TRIGGER_PRESSED,
                CONF_SUBTYPE: button.name,
            }
            if button.event_filter:
                trigger[ATTR_EVENT_FILTER] = button.event_filter
            triggers.append(trigger)

    return triggers


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Listen for the button press this trigger describes."""
    event_data: dict[str, Any] = {
        CONF_DEVICE_ID: config[CONF_DEVICE_ID],
        ATTR_BUTTON: config[CONF_SUBTYPE],
    }
    if config.get(ATTR_EVENT_FILTER):
        event_data[ATTR_EVENT_FILTER] = config[ATTR_EVENT_FILTER]

    return await event_trigger.async_attach_trigger(
        hass,
        event_trigger.TRIGGER_SCHEMA(
            {
                CONF_PLATFORM: "event",
                CONF_EVENT_TYPE: EVENT_BUTTON_PRESSED,
                CONF_EVENT_DATA: event_data,
            }
        ),
        action,
        trigger_info,
        platform_type="device",
    )
