"""Config flow tests."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.analog_displays.const import DOMAIN


async def test_user_step_creates_entry(hass: HomeAssistant) -> None:
    """The user step names the device and creates an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Meter Panel"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Meter Panel"
