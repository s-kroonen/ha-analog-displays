"""Config flow for the Analog Displays integration.

The flow is deliberately shaped so the hardware wizard is a detour, never a
prerequisite: :meth:`async_step_hardware` offers "I already have my hardware
set up" and that branch goes straight to binding entities.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector
from homeassistant.helpers.selector import NumberSelectorMode
import voluptuous as vol

from .const import (
    CONF_ADD_ANOTHER,
    CONF_FADE,
    CONF_LABEL,
    CONF_LIGHT_ENTITY_ID,
    CONF_MAX_VALUE,
    CONF_MIN_UPDATE_INTERVAL,
    CONF_MIN_VALUE,
    CONF_MODE,
    CONF_NAME,
    CONF_OUTPUT_ENTITY_ID,
    CONF_SOURCE_ENTITY_ID,
    CONF_SOURCE_MODE,
    CONF_STATISTIC_ENTITY_ID,
    CONF_STATISTIC_PERIOD,
    CONF_STATISTIC_TYPE,
    DEFAULT_MIN_UPDATE_INTERVAL,
    DOMAIN,
    LED_MODE_GRADIENT,
    LED_MODE_OFF,
    LED_MODE_PRESET,
    MAX_PRESETS,
    SOURCE_MODE_ENTITY,
    SOURCE_MODE_STATISTIC,
    SOURCE_MODES,
    STATISTIC_PERIODS,
    STATISTIC_TYPES,
)
from .models import (
    AnalogDisplaysConfigError,
    ColourStop,
    Device,
    Display,
    LedConfig,
    Preset,
    PresetAssignment,
)

CONF_COLOUR_FIELD = "colour"

STEP_USER_SCHEMA = vol.Schema({vol.Required(CONF_NAME): str})


def _display_schema() -> vol.Schema:
    """Build the schema for binding one display to its output and LED."""
    return vol.Schema(
        {
            vol.Required(CONF_NAME): str,
            vol.Required(CONF_OUTPUT_ENTITY_ID): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="number")
            ),
            vol.Optional(CONF_LIGHT_ENTITY_ID): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="light")
            ),
            vol.Required(CONF_MODE, default=LED_MODE_PRESET): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[LED_MODE_PRESET, LED_MODE_GRADIENT, LED_MODE_OFF],
                    translation_key="led_mode",
                )
            ),
            vol.Required(CONF_FADE, default=False): selector.BooleanSelector(),
            vol.Required(
                CONF_MIN_UPDATE_INTERVAL, default=DEFAULT_MIN_UPDATE_INTERVAL
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=3600,
                    step=0.5,
                    unit_of_measurement="s",
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(CONF_ADD_ANOTHER, default=False): selector.BooleanSelector(),
        }
    )


def _preset_schema() -> vol.Schema:
    """Build the schema for naming a preset."""
    return vol.Schema({vol.Required(CONF_LABEL): str})


def _assignment_schema() -> vol.Schema:
    """Build the schema for what one display shows under this preset."""
    return vol.Schema(
        {
            vol.Required(
                CONF_SOURCE_MODE, default=SOURCE_MODE_ENTITY
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(SOURCE_MODES), translation_key="source_mode"
                )
            ),
            vol.Optional(CONF_SOURCE_ENTITY_ID): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["sensor", "number", "input_number"]
                )
            ),
            vol.Optional(CONF_STATISTIC_ENTITY_ID): selector.StatisticSelector(),
            vol.Optional(CONF_STATISTIC_TYPE, default="mean"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(STATISTIC_TYPES), translation_key="statistic_type"
                )
            ),
            vol.Optional(CONF_STATISTIC_PERIOD, default="24h"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(STATISTIC_PERIODS),
                    translation_key="statistic_period",
                )
            ),
            vol.Required(CONF_MIN_VALUE, default=0.0): selector.NumberSelector(
                selector.NumberSelectorConfig(mode=NumberSelectorMode.BOX, step="any")
            ),
            vol.Required(CONF_MAX_VALUE, default=100.0): selector.NumberSelector(
                selector.NumberSelectorConfig(mode=NumberSelectorMode.BOX, step="any")
            ),
            vol.Optional(CONF_COLOUR_FIELD): selector.ColorRGBSelector(),
        }
    )


def validate_output_entity(hass: HomeAssistant, entity_id: str) -> str | None:
    """Return an error key if ``entity_id`` cannot be driven as an output.

    A ``number`` entity that does not advertise ``min``/``max`` gives the
    backend nothing to scale into, so reject it at config time rather than
    failing on every write.
    """
    state = hass.states.get(entity_id)
    if state is None:
        return "output_unavailable"
    attributes = state.attributes
    try:
        minimum = float(attributes["min"])
        maximum = float(attributes["max"])
    except (KeyError, TypeError, ValueError):
        return "output_no_range"
    if minimum == maximum:
        return "output_no_range"
    return None


def _led_from_input(user_input: dict[str, Any]) -> LedConfig | None:
    """Build the LED configuration for a display, if one was bound."""
    light_entity_id = user_input.get(CONF_LIGHT_ENTITY_ID)
    if not light_entity_id:
        return None

    mode = user_input.get(CONF_MODE, LED_MODE_PRESET)
    stops: list[ColourStop] = []
    if mode == LED_MODE_GRADIENT:
        # Gradient stops are edited in the options flow; seed a single stop so
        # the configuration is valid the moment the entry is created.
        stops = [ColourStop(at=0.0, colour=(0, 255, 0))]

    return LedConfig(
        light_entity_id=light_entity_id,
        mode=mode,
        stops=stops,
        fade=bool(user_input.get(CONF_FADE, False)),
    )


class AnalogDisplaysConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Analog Displays config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Start with an empty device to fill in step by step."""
        self._name: str = ""
        self._displays: list[Display] = []
        self._presets: list[Preset] = []
        self._preset_label: str = ""
        self._assignments: dict[int, PresetAssignment] = {}
        self._assign_index: int = 0

    # --- naming and the hardware branch ------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name the device. One config entry is one physical board."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA)

        self._name = user_input[CONF_NAME]
        return await self.async_step_hardware()

    async def async_step_hardware(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer the YAML wizard, or skip straight to binding entities."""
        return self.async_show_menu(
            step_id="hardware",
            menu_options=["wizard", "bind_displays"],
        )

    async def async_step_wizard(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Enter the ESPHome YAML wizard.

        The wizard is a convenience only and is never a prerequisite for
        binding, so it hands over to the same binding steps when it finishes.
        """
        return await self.async_step_bind_displays()

    # --- binding -----------------------------------------------------------

    async def async_step_bind_displays(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Bind one display at a time to its output entity and LED."""
        errors: dict[str, str] = {}

        if user_input is not None:
            error = validate_output_entity(self.hass, user_input[CONF_OUTPUT_ENTITY_ID])
            if error:
                errors[CONF_OUTPUT_ENTITY_ID] = error
            elif any(
                display.output_entity_id == user_input[CONF_OUTPUT_ENTITY_ID]
                for display in self._displays
            ):
                errors[CONF_OUTPUT_ENTITY_ID] = "output_already_used"
            else:
                self._displays.append(
                    Display(
                        name=user_input[CONF_NAME],
                        output_entity_id=user_input[CONF_OUTPUT_ENTITY_ID],
                        led=_led_from_input(user_input),
                        min_update_interval=_interval(user_input),
                    )
                )
                if user_input[CONF_ADD_ANOTHER]:
                    return await self.async_step_bind_displays()
                return await self.async_step_preset()

        return self.async_show_form(
            step_id="bind_displays",
            data_schema=_display_schema(),
            errors=errors,
            description_placeholders={"index": str(len(self._displays) + 1)},
        )

    # --- presets -----------------------------------------------------------

    async def async_step_preset(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name a preset, then collect what each display shows under it."""
        if user_input is None:
            return self.async_show_form(
                step_id="preset",
                data_schema=_preset_schema(),
                description_placeholders={"index": str(len(self._presets) + 1)},
            )

        self._preset_label = user_input[CONF_LABEL]
        self._assignments = {}
        self._assign_index = 0
        return await self.async_step_preset_assign()

    async def async_step_preset_assign(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask what one display shows under the preset being built.

        Leaving the source blank marks the display unused under this preset:
        at runtime its needle goes to zero and its LED goes dark.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            assignment = _assignment_from_input(user_input)
            if assignment is not None:
                try:
                    assignment.validate("preset")
                except AnalogDisplaysConfigError:
                    errors[_error_field(assignment)] = _error_key(assignment)
                else:
                    self._assignments[self._assign_index] = assignment

            if not errors:
                self._assign_index += 1
                if self._assign_index < len(self._displays):
                    return await self.async_step_preset_assign()
                return await self.async_step_preset_done()

        return self.async_show_form(
            step_id="preset_assign",
            data_schema=_assignment_schema(),
            errors=errors,
            description_placeholders={
                "preset": self._preset_label,
                "display": self._displays[self._assign_index].name,
            },
        )

    async def async_step_preset_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the finished preset and offer to add another."""
        if not self._assignments:
            return self.async_show_form(
                step_id="preset_assign",
                data_schema=_assignment_schema(),
                errors={"base": "preset_drives_nothing"},
                description_placeholders={
                    "preset": self._preset_label,
                    "display": self._displays[0].name,
                },
            )

        self._presets.append(
            Preset(label=self._preset_label, assignments=dict(self._assignments))
        )

        if user_input is None and len(self._presets) < MAX_PRESETS:
            return self.async_show_menu(
                step_id="preset_done",
                menu_options=["preset", "finish"],
            )
        return await self.async_step_finish()

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate the assembled device and create the entry."""
        device = Device(
            name=self._name,
            displays=self._displays,
            presets=self._presets,
        )
        try:
            device.validate()
        except AnalogDisplaysConfigError:
            return self.async_abort(reason="invalid_configuration")

        return self.async_create_entry(
            title=self._name, data={}, options=device.to_dict()
        )


def _interval(user_input: dict[str, Any]) -> timedelta:
    """Read the per-display debounce interval out of a submitted form."""
    seconds = float(
        user_input.get(CONF_MIN_UPDATE_INTERVAL, DEFAULT_MIN_UPDATE_INTERVAL)
    )
    return timedelta(seconds=seconds)


def _assignment_from_input(user_input: dict[str, Any]) -> PresetAssignment | None:
    """Build an assignment from a submitted form, or ``None`` if left blank.

    A blank source is how the user says "this display is not used under this
    preset", so it is not an error.
    """
    mode = user_input.get(CONF_SOURCE_MODE, SOURCE_MODE_ENTITY)
    source_entity_id = user_input.get(CONF_SOURCE_ENTITY_ID)
    statistic_entity_id = user_input.get(CONF_STATISTIC_ENTITY_ID)

    if mode == SOURCE_MODE_ENTITY and not source_entity_id:
        return None
    if mode == SOURCE_MODE_STATISTIC and not statistic_entity_id:
        return None

    return PresetAssignment(
        source_mode=mode,
        source_entity_id=source_entity_id,
        statistic_entity_id=statistic_entity_id,
        statistic_type=user_input.get(CONF_STATISTIC_TYPE),
        statistic_period=user_input.get(CONF_STATISTIC_PERIOD),
        min_value=float(user_input[CONF_MIN_VALUE]),
        max_value=float(user_input[CONF_MAX_VALUE]),
        colour=_colour_from_input(user_input),
    )


def _error_field(assignment: PresetAssignment) -> str:
    """Which form field an invalid assignment should be flagged against."""
    if assignment.min_value == assignment.max_value:
        return CONF_MAX_VALUE
    return "base"


def _error_key(assignment: PresetAssignment) -> str:
    """Which translated error an invalid assignment should report."""
    if assignment.min_value == assignment.max_value:
        return "same_min_max"
    return "invalid_source"


def _colour_from_input(user_input: dict[str, Any]) -> tuple[int, int, int] | None:
    """Read an optional RGB colour out of a submitted form."""
    colour = user_input.get(CONF_COLOUR_FIELD)
    if not colour:
        return None
    red, green, blue = colour
    return (int(red), int(green), int(blue))
