"""Config flow for the Analog Displays integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
import voluptuous as vol

from .const import CONF_NAME, DOMAIN

STEP_USER_SCHEMA = vol.Schema({vol.Required(CONF_NAME): str})


class AnalogDisplaysConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Analog Displays config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step: name the device."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA)

        return self.async_create_entry(title=user_input[CONF_NAME], data={})
