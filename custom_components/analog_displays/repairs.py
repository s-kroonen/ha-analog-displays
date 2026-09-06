"""Repair issues raised when a display's source stops producing values.

A source going away is a configuration problem the user has to fix — the
sensor was renamed, the integration behind it was removed, the device is off —
so it surfaces in Home Assistant's repairs panel naming exactly which device,
display and preset are affected. It clears itself the moment the source
recovers, so there is nothing for the user to dismiss.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

ISSUE_SOURCE_UNAVAILABLE = "source_unavailable"


def source_issue_id(entry_id: str, display_index: int) -> str:
    """Build the repair issue id for one display of one config entry."""
    return f"{ISSUE_SOURCE_UNAVAILABLE}_{entry_id}_{display_index}"


@callback
def async_raise_source_issue(
    hass: HomeAssistant,
    entry_id: str,
    display_index: int,
    *,
    device_name: str,
    display_name: str,
    preset_label: str,
    source_entity_id: str,
) -> None:
    """Report that a display's active source has stopped producing values."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        source_issue_id(entry_id, display_index),
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_SOURCE_UNAVAILABLE,
        translation_placeholders={
            "device": device_name,
            "display": display_name,
            "preset": preset_label,
            "entity_id": source_entity_id,
        },
    )


@callback
def async_clear_source_issue(
    hass: HomeAssistant, entry_id: str, display_index: int
) -> None:
    """Clear a display's source issue once it produces values again."""
    ir.async_delete_issue(hass, DOMAIN, source_issue_id(entry_id, display_index))
