"""Config flow for the Analog Displays integration.

The flow is deliberately shaped so the hardware wizard is a detour, never a
prerequisite: :meth:`async_step_hardware` offers "I already have my hardware
set up" and that branch goes straight to binding entities.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
    OptionsFlowWithReload,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.selector import NumberSelectorMode, SelectSelectorMode
import voluptuous as vol

from .const import (
    CONF_AT,
    CONF_BUTTON_COUNT,
    CONF_DISPLAY_COUNT,
    CONF_END,
    CONF_FADE,
    CONF_FEEDBACK_COLOUR,
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
    CONF_STATISTICS_INTERVAL,
    CONF_UNIT,
    CONFIG_VERSION,
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
    HardwareProfile,
    Preset,
    PresetAssignment,
    RGBColor,
)
from .units import compatible
from .wizard import (
    LED_KIND_ADDRESSABLE,
    LED_KIND_NONE,
    LED_KIND_RAW_RGB,
    led_from_dict,
    request_from_profile,
)
from .yaml_gen import (
    BoardProfile,
    ButtonSpec,
    DisplaySpec,
    YamlRequest,
    generate_yaml,
    get_board,
    list_boards,
    validate_pins,
)

CONF_COLOUR_FIELD = "colour"
DEFAULT_BOARD = "esp32-devkit-v1"
CONF_DISPLAY_INDEX = "display_index"
CONF_PRESET_INDEX = "preset_index"
CONF_ZONE_COUNT = "zone_count"

#: Sources whose state is a plain number. Any of these can drive a meter.
SOURCE_DOMAINS = ["sensor", "number", "input_number", "counter"]

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): str,
        vol.Required(CONF_DISPLAY_COUNT, default=1): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1, max=16, step=1, mode=NumberSelectorMode.BOX
            )
        ),
        vol.Required(CONF_BUTTON_COUNT, default=0): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=16, step=1, mode=NumberSelectorMode.BOX
            )
        ),
    }
)


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
        }
    )


def _preset_schema() -> vol.Schema:
    """Build the schema for naming a preset."""
    return vol.Schema(
        {
            vol.Required(CONF_LABEL): str,
            vol.Optional(CONF_FEEDBACK_COLOUR): selector.ColorRGBSelector(),
        }
    )


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
                selector.EntitySelectorConfig(domain=SOURCE_DOMAINS)
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
            vol.Optional(CONF_UNIT): selector.TextSelector(),
            vol.Required(CONF_MIN_VALUE, default=0.0): selector.NumberSelector(
                selector.NumberSelectorConfig(mode=NumberSelectorMode.BOX, step="any")
            ),
            vol.Required(CONF_MAX_VALUE, default=100.0): selector.NumberSelector(
                selector.NumberSelectorConfig(mode=NumberSelectorMode.BOX, step="any")
            ),
            vol.Optional(CONF_COLOUR_FIELD): selector.ColorRGBSelector(),
            vol.Required(CONF_MODE, default=LED_MODE_PRESET): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[LED_MODE_PRESET, LED_MODE_GRADIENT, LED_MODE_OFF],
                    translation_key="led_mode",
                )
            ),
            vol.Required(CONF_FADE, default=False): selector.BooleanSelector(),
            vol.Required(CONF_ZONE_COUNT, default=0): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=8, step=1, mode=NumberSelectorMode.BOX
                )
            ),
        }
    )


def _zone_schema() -> vol.Schema:
    """Build the schema for one LED zone, in the display's own unit."""
    return vol.Schema(
        {
            vol.Required(CONF_AT): selector.NumberSelector(
                selector.NumberSelectorConfig(mode=NumberSelectorMode.BOX, step="any")
            ),
            vol.Required(CONF_COLOUR_FIELD): selector.ColorRGBSelector(),
            vol.Optional(CONF_END): selector.NumberSelector(
                selector.NumberSelectorConfig(mode=NumberSelectorMode.BOX, step="any")
            ),
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


# --- wizard schemas ---------------------------------------------------------

CONF_BOARD = "board"
CONF_PIN = "pin"
CONF_LED_KIND = "led_kind"
CONF_DATA_PIN = "data_pin"
CONF_LED_INDEX = "led_index"
CONF_RED_PIN = "red_pin"
CONF_GREEN_PIN = "green_pin"
CONF_BLUE_PIN = "blue_pin"
CONF_MULTI_CLICK = "multi_click"


def _pin_selector(pins: list[int], used: set[int]) -> selector.SelectSelector:
    """Offer only pins that are safe and not already taken."""
    options = [str(pin) for pin in pins if pin not in used]
    return selector.SelectSelector(
        selector.SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
    )


def _board_schema() -> vol.Schema:
    """Build the schema for choosing a board profile."""
    return vol.Schema(
        {
            vol.Required(CONF_BOARD, default=DEFAULT_BOARD): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=board.key, label=board.name)
                        for board in list_boards()
                    ]
                )
            )
        }
    )


def _display_hw_schema(board: BoardProfile, used: set[int]) -> vol.Schema:
    """Build the schema for one display's output pin and LED type."""
    return vol.Schema(
        {
            vol.Required(CONF_PIN): _pin_selector(board.output_pins(), used),
            vol.Required(CONF_LED_KIND, default=LED_KIND_NONE): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[LED_KIND_NONE, LED_KIND_ADDRESSABLE, LED_KIND_RAW_RGB],
                    translation_key="led_kind",
                )
            ),
        }
    )


def _led_hw_schema(
    kind: str, board: BoardProfile, used: set[int], data_pins: set[int]
) -> vol.Schema:
    """Build the schema for one display's LED wiring.

    A data pin already carrying a strip stays offered: several meters sharing
    one addressable strip is the normal wiring, not a clash.
    """
    if kind == LED_KIND_ADDRESSABLE:
        return vol.Schema(
            {
                vol.Required(CONF_DATA_PIN): _pin_selector(
                    board.output_pins(), used - data_pins
                ),
                vol.Required(CONF_LED_INDEX, default=0): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=255, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
            }
        )

    return vol.Schema(
        {
            vol.Required(CONF_RED_PIN): _pin_selector(board.output_pins(), used),
            vol.Required(CONF_GREEN_PIN): _pin_selector(board.output_pins(), used),
            vol.Required(CONF_BLUE_PIN): _pin_selector(board.output_pins(), used),
        }
    )


def _button_hw_schema(board: BoardProfile, used: set[int]) -> vol.Schema:
    """Build the schema for one button's pin."""
    return vol.Schema(
        {
            vol.Required(CONF_PIN): _pin_selector(board.input_pins(), used),
            vol.Required(CONF_MULTI_CLICK, default=False): selector.BooleanSelector(),
        }
    )


def _led_wiring(kind: str, user_input: dict[str, Any]) -> dict[str, Any]:
    """Turn a submitted LED form into the stored wiring dict."""
    if kind == LED_KIND_ADDRESSABLE:
        return {
            "kind": LED_KIND_ADDRESSABLE,
            "data_pin": int(user_input[CONF_DATA_PIN]),
            "index": int(user_input[CONF_LED_INDEX]),
        }
    return {
        "kind": LED_KIND_RAW_RGB,
        "red_pin": int(user_input[CONF_RED_PIN]),
        "green_pin": int(user_input[CONF_GREEN_PIN]),
        "blue_pin": int(user_input[CONF_BLUE_PIN]),
    }


def _wizard_request(
    device_name: str,
    board: str,
    displays: list[dict[str, Any]],
    buttons: list[dict[str, Any]],
) -> YamlRequest:
    """Build a generator request straight from the wizard's answers."""
    return YamlRequest(
        device_name=device_name or "Analog Displays",
        board=board,
        displays=[
            DisplaySpec(
                name=f"Display {index + 1}",
                pin=int(wiring["pin"]),
                led=led_from_dict(wiring.get("led")),
            )
            for index, wiring in enumerate(displays)
        ],
        buttons=[
            ButtonSpec(
                name=f"Button {index + 1}",
                pin=int(wiring["pin"]),
                multi_click=bool(wiring.get("multi_click", False)),
            )
            for index, wiring in enumerate(buttons)
        ],
    )


class AnalogDisplaysConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Analog Displays config flow."""

    VERSION = CONFIG_VERSION

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Everything collected during setup stays editable afterwards."""
        return AnalogDisplaysOptionsFlow()

    def __init__(self) -> None:
        """Start with an empty device to fill in step by step."""
        self._name: str = ""
        self._displays: list[Display] = []
        self._presets: list[Preset] = []
        self._preset_label: str = ""
        self._feedback_colour: RGBColor | None = None
        self._assignments: dict[int, PresetAssignment] = {}
        self._assign_index: int = 0
        self._display_count: int = 1
        self._button_count: int = 0
        self._zones: list[ColourStop] = []
        self._zone_target: int = 0
        self._pending: PresetAssignment | None = None

        # Wizard state, untouched on the bypass path.
        self._board: str = ""
        self._hw_displays: list[dict[str, Any]] = []
        self._hw_led_kinds: list[str] = []
        self._hw_buttons: list[dict[str, Any]] = []
        self._led_index: int = 0
        self._hardware_profile: HardwareProfile | None = None

    def _used_pins(self) -> set[int]:
        """Every GPIO the wizard has already handed out."""
        used: set[int] = set()
        for wiring in self._hw_displays:
            used.add(int(wiring["pin"]))
            led = wiring.get("led")
            if not led:
                continue
            if led["kind"] == LED_KIND_ADDRESSABLE:
                used.add(int(led["data_pin"]))
            elif led["kind"] == LED_KIND_RAW_RGB:
                used.update(
                    int(led[key]) for key in ("red_pin", "green_pin", "blue_pin")
                )
        used.update(int(wiring["pin"]) for wiring in self._hw_buttons)
        return used

    def _data_pins(self) -> set[int]:
        """Pins already carrying an addressable strip, which may be shared."""
        return {
            int(wiring["led"]["data_pin"])
            for wiring in self._hw_displays
            if wiring.get("led") and wiring["led"]["kind"] == LED_KIND_ADDRESSABLE
        }

    # --- naming and the hardware branch ------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name the device. One config entry is one physical board."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA)

        self._name = user_input[CONF_NAME]
        self._display_count = int(user_input[CONF_DISPLAY_COUNT])
        self._button_count = int(user_input[CONF_BUTTON_COUNT])
        return await self.async_step_hardware()

    async def async_step_hardware(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer the YAML wizard, or skip straight to binding entities."""
        return self.async_show_menu(
            step_id="hardware",
            menu_options=["wizard", "bind_displays"],
        )

    # --- the YAML wizard ----------------------------------------------------

    async def async_step_wizard(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the board to generate for."""
        if user_input is None:
            return self.async_show_form(step_id="wizard", data_schema=_board_schema())

        self._board = user_input[CONF_BOARD]
        self._hw_displays = []
        self._hw_buttons = []
        return await self.async_step_displays_hw()

    async def async_step_displays_hw(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the output GPIO for one display at a time."""
        board = get_board(self._board)
        errors: dict[str, str] = {}

        if user_input is not None:
            pin = int(user_input[CONF_PIN])
            if pin in self._used_pins():
                errors[CONF_PIN] = "pin_duplicate"
            else:
                self._hw_displays.append({"pin": pin, "led": None})
                self._hw_led_kinds.append(user_input[CONF_LED_KIND])
                if len(self._hw_displays) < self._display_count:
                    return await self.async_step_displays_hw()
                return await self.async_step_leds_hw()

        return self.async_show_form(
            step_id="displays_hw",
            data_schema=_display_hw_schema(board, self._used_pins()),
            errors=errors,
            description_placeholders={"index": str(len(self._hw_displays) + 1)},
        )

    async def async_step_leds_hw(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the LED wiring for each display that asked for one.

        Mixed setups are the point here: several displays can share one
        addressable data pin while another uses three raw PWM channels.
        """
        board = get_board(self._board)

        while self._led_index < len(self._hw_displays) and (
            self._hw_led_kinds[self._led_index] == LED_KIND_NONE
        ):
            self._led_index += 1

        if self._led_index >= len(self._hw_displays):
            return await self.async_step_buttons_hw()

        kind = self._hw_led_kinds[self._led_index]
        errors: dict[str, str] = {}

        if user_input is not None:
            led = _led_wiring(kind, user_input)
            candidate = list(self._hw_displays)
            candidate[self._led_index] = {
                **candidate[self._led_index],
                "led": led,
            }
            problems = validate_pins(
                _wizard_request("probe", self._board, candidate, self._hw_buttons)
            )
            if problems:
                errors["base"] = next(iter(problems.values()))
            else:
                self._hw_displays = candidate
                self._led_index += 1
                return await self.async_step_leds_hw()

        return self.async_show_form(
            step_id="leds_hw",
            data_schema=_led_hw_schema(
                kind, board, self._used_pins(), self._data_pins()
            ),
            errors=errors,
            description_placeholders={
                "index": str(self._led_index + 1),
                "kind": kind,
            },
        )

    async def async_step_buttons_hw(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the button GPIOs, which are global to the device."""
        board = get_board(self._board)
        errors: dict[str, str] = {}

        if len(self._hw_buttons) >= self._button_count:
            return await self.async_step_yaml_result()

        if user_input is not None:
            pin = int(user_input[CONF_PIN])
            if pin in self._used_pins():
                errors[CONF_PIN] = "pin_duplicate"
            else:
                self._hw_buttons.append(
                    {
                        "pin": pin,
                        "multi_click": bool(user_input[CONF_MULTI_CLICK]),
                    }
                )
                return await self.async_step_buttons_hw()

        return self.async_show_form(
            step_id="buttons_hw",
            data_schema=_button_hw_schema(board, self._used_pins()),
            errors=errors,
            description_placeholders={"index": str(len(self._hw_buttons) + 1)},
        )

    async def async_step_yaml_result(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the generated YAML, then hand over to binding.

        The integration does not compile or flash anything: the user copies
        this into ESPHome themselves.
        """
        self._hardware_profile = HardwareProfile(
            board=self._board,
            displays=list(self._hw_displays),
            buttons=list(self._hw_buttons),
        )
        yaml_text = generate_yaml(
            _wizard_request(
                self._name, self._board, self._hw_displays, self._hw_buttons
            )
        )

        if user_input is None:
            return self.async_show_form(
                step_id="yaml_result",
                data_schema=vol.Schema({}),
                description_placeholders={"yaml": yaml_text},
            )

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
                        light_entity_id=user_input.get(CONF_LIGHT_ENTITY_ID),
                        min_update_interval=_interval(user_input),
                    )
                )
                if len(self._displays) < self._display_count:
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
        self._feedback_colour = _colour_from_input(user_input, CONF_FEEDBACK_COLOUR)
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
                zones = int(user_input.get(CONF_ZONE_COUNT, 0))
                errors = _validate_assignment(
                    self.hass, assignment, zones_pending=bool(zones)
                )
                if not errors:
                    if zones:
                        # Zones are collected on their own pages, in the unit
                        # this assignment was just calibrated in.
                        self._pending = assignment
                        self._zones = []
                        self._zone_target = zones
                        return await self.async_step_preset_zone()
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

    async def async_step_preset_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect one LED zone, expressed in the display's own unit."""
        if user_input is not None:
            self._zones.append(_zone_from_input(user_input))
            if len(self._zones) < self._zone_target:
                return await self.async_step_preset_zone()

            assert self._pending is not None
            complete = replace(self._pending, stops=list(self._zones))
            zone_errors = _validate_assignment(self.hass, complete)
            if zone_errors:
                # Restart this assignment's zones rather than keep a bad set.
                self._zones = []
                return self.async_show_form(
                    step_id="preset_zone",
                    data_schema=_zone_schema(),
                    errors=zone_errors,
                    description_placeholders=self._zone_placeholders(),
                )

            self._assignments[self._assign_index] = complete
            self._pending = None
            self._assign_index += 1
            if self._assign_index < len(self._displays):
                return await self.async_step_preset_assign()
            return await self.async_step_preset_done()

        return self.async_show_form(
            step_id="preset_zone",
            data_schema=_zone_schema(),
            description_placeholders=self._zone_placeholders(),
        )

    def _zone_placeholders(self) -> dict[str, str]:
        """Describe which zone of which display is being asked for."""
        assignment = self._pending
        return {
            "index": str(len(self._zones) + 1),
            "count": str(self._zone_target),
            "unit": "" if assignment is None else (assignment.unit or ""),
            "display": self._displays[self._assign_index].name,
        }

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
            hardware_profile=self._hardware_profile,
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

    unit = user_input.get(CONF_UNIT) or None
    return PresetAssignment(
        source_mode=mode,
        source_entity_id=source_entity_id,
        statistic_entity_id=statistic_entity_id,
        statistic_type=user_input.get(CONF_STATISTIC_TYPE),
        statistic_period=user_input.get(CONF_STATISTIC_PERIOD),
        unit=unit,
        min_value=float(user_input[CONF_MIN_VALUE]),
        max_value=float(user_input[CONF_MAX_VALUE]),
        colour=_colour_from_input(user_input),
        led_mode=user_input.get(CONF_MODE, LED_MODE_PRESET),
        fade=bool(user_input.get(CONF_FADE, False)),
    )


def validate_source_unit(
    hass: HomeAssistant, assignment: PresetAssignment
) -> str | None:
    """Return an error key if the source cannot be read in the chosen unit.

    Catching this at config time is the point: a sensor in watts calibrated
    against a range in kilowatts would otherwise read a thousand times high
    with nothing to show anything was wrong.
    """
    if assignment.unit is None:
        return None

    entity_id = assignment.source_entity_id or assignment.statistic_entity_id
    if not entity_id:
        return None

    state = hass.states.get(entity_id)
    if state is None:
        return None

    if not compatible(
        state.attributes.get("unit_of_measurement"),
        assignment.unit,
        state.attributes.get("device_class"),
    ):
        return "incompatible_unit"
    return None


def validate_numeric_source(hass: HomeAssistant, entity_id: str) -> str | None:
    """Return an error key if the chosen source is not a number."""
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable", ""):
        # Nothing to check against yet; the runtime handles it as a dead source.
        return None
    try:
        float(state.state)
    except (TypeError, ValueError):
        return "source_not_numeric"
    return None


def _zone_from_input(user_input: dict[str, Any]) -> ColourStop:
    """Build one LED zone from a submitted form."""
    colour = _colour_from_input(user_input)
    end = user_input.get(CONF_END)
    return ColourStop(
        at=float(user_input[CONF_AT]),
        colour=colour or (255, 255, 255),
        end=None if end is None else float(end),
    )


def _validate_assignment(
    hass: HomeAssistant, assignment: PresetAssignment, *, zones_pending: bool = False
) -> dict[str, str]:
    """Check an assignment against the model and against its live source.

    ``zones_pending`` covers the gap while LED zones are still being collected
    on their own pages: everything else is checked now, and the zones are
    validated once they are attached.
    """
    candidate = assignment
    if zones_pending and not assignment.stops:
        candidate = replace(
            assignment, stops=[ColourStop(at=assignment.min_value, colour=(0, 0, 0))]
        )
    try:
        candidate.validate("preset")
    except AnalogDisplaysConfigError:
        return {_error_field(assignment): _error_key(assignment)}

    if assignment.source_entity_id:
        error = validate_numeric_source(hass, assignment.source_entity_id)
        if error:
            return {CONF_SOURCE_ENTITY_ID: error}

    error = validate_source_unit(hass, assignment)
    if error:
        return {CONF_UNIT: error}

    return {}


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


def _colour_from_input(
    user_input: dict[str, Any], field: str = CONF_COLOUR_FIELD
) -> RGBColor | None:
    """Read an optional RGB colour out of a submitted form."""
    colour = user_input.get(field)
    if not colour:
        return None
    red, green, blue = colour
    return (int(red), int(green), int(blue))


class AnalogDisplaysOptionsFlow(OptionsFlowWithReload):
    """Edit everything the initial flow collected.

    Subclassing :class:`OptionsFlowWithReload` is what makes an edit reload the
    entry cleanly instead of leaving orphaned entities behind.
    """

    def __init__(self) -> None:
        """Start with nothing loaded; the menu step reads the stored device."""
        self._device: Device | None = None
        self._preset_label: str = ""
        self._assignments: dict[int, PresetAssignment] = {}
        self._assign_index: int = 0

    @property
    def device(self) -> Device:
        """The device as currently stored, loaded once per flow."""
        if self._device is None:
            self._device = Device.from_dict(dict(self.config_entry.options))
        return self._device

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer everything that can be edited after setup."""
        options = ["displays", "add_preset", "remove_preset", "intervals"]
        if self.device.hardware_profile is not None:
            options.append("export_yaml")
        return self.async_show_menu(step_id="init", menu_options=options)

    # --- displays ----------------------------------------------------------

    async def async_step_displays(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-bind a display's output entity and LED."""
        device = self.device
        errors: dict[str, str] = {}

        if user_input is not None:
            index = int(user_input[CONF_DISPLAY_INDEX])
            output = user_input[CONF_OUTPUT_ENTITY_ID]
            error = validate_output_entity(self.hass, output)
            if error:
                errors[CONF_OUTPUT_ENTITY_ID] = error
            elif any(
                other.output_entity_id == output
                for position, other in enumerate(device.displays)
                if position != index
            ):
                errors[CONF_OUTPUT_ENTITY_ID] = "output_already_used"
            else:
                displays = list(device.displays)
                displays[index] = Display(
                    name=user_input[CONF_NAME],
                    output_entity_id=output,
                    light_entity_id=user_input.get(CONF_LIGHT_ENTITY_ID),
                    min_update_interval=_interval(user_input),
                )
                return self._save(replace(device, displays=displays))

        return self.async_show_form(
            step_id="displays",
            data_schema=_edit_display_schema(device),
            errors=errors,
        )

    # --- presets ------------------------------------------------------------

    async def async_step_add_preset(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name a new preset, then collect its per-display assignments."""
        if len(self.device.presets) >= MAX_PRESETS:
            return self.async_abort(reason="too_many_presets")

        if user_input is None:
            return self.async_show_form(
                step_id="add_preset",
                data_schema=_preset_schema(),
                description_placeholders={"index": str(len(self.device.presets) + 1)},
            )

        self._preset_label = user_input[CONF_LABEL]
        self._assignments = {}
        self._assign_index = 0
        return await self.async_step_edit_assignment()

    async def async_step_edit_assignment(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask what one display shows under the preset being added."""
        device = self.device
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
                if self._assign_index < len(device.displays):
                    return await self.async_step_edit_assignment()
                if not self._assignments:
                    errors["base"] = "preset_drives_nothing"
                    self._assign_index = 0
                else:
                    presets = [
                        *device.presets,
                        Preset(
                            label=self._preset_label,
                            assignments=dict(self._assignments),
                        ),
                    ]
                    return self._save(replace(device, presets=presets))

        return self.async_show_form(
            step_id="edit_assignment",
            data_schema=_assignment_schema(),
            errors=errors,
            description_placeholders={
                "preset": self._preset_label,
                "display": device.displays[self._assign_index].name,
            },
        )

    async def async_step_remove_preset(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delete a preset, refusing to leave the device with none."""
        device = self.device
        if len(device.presets) <= 1:
            return self.async_abort(reason="last_preset")

        if user_input is None:
            return self.async_show_form(
                step_id="remove_preset", data_schema=_preset_choice_schema(device)
            )

        index = int(user_input[CONF_PRESET_INDEX])
        presets = [
            preset
            for position, preset in enumerate(device.presets)
            if position != index
        ]
        active = min(device.active_preset_index, len(presets) - 1)
        return self._save(replace(device, presets=presets, active_preset_index=active))

    # --- intervals ----------------------------------------------------------

    async def async_step_intervals(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change how often statistics are polled."""
        device = self.device
        if user_input is None:
            return self.async_show_form(
                step_id="intervals",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_STATISTICS_INTERVAL,
                            default=device.statistics_interval.total_seconds(),
                        ): selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=30,
                                max=86400,
                                step=30,
                                unit_of_measurement="s",
                                mode=NumberSelectorMode.BOX,
                            )
                        )
                    }
                ),
            )

        return self._save(
            replace(
                device,
                statistics_interval=timedelta(
                    seconds=float(user_input[CONF_STATISTICS_INTERVAL])
                ),
            )
        )

    # --- re-export ----------------------------------------------------------

    async def async_step_export_yaml(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the ESPHome YAML again, regenerated from the current names."""
        device = self.device
        profile = device.hardware_profile
        if profile is None:
            return self.async_abort(reason="no_hardware_profile")

        if user_input is None:
            return self.async_show_form(
                step_id="export_yaml",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "yaml": generate_yaml(request_from_profile(device, profile))
                },
            )
        return await self.async_step_init()

    def _save(self, device: Device) -> ConfigFlowResult:
        """Validate the edited device and persist it, reloading the entry."""
        try:
            device.validate()
        except AnalogDisplaysConfigError:
            return self.async_abort(reason="invalid_configuration")
        return self.async_create_entry(data=device.to_dict())


def _edit_display_schema(device: Device) -> vol.Schema:
    """Build the schema for re-binding one display."""
    return vol.Schema(
        {
            vol.Required(CONF_DISPLAY_INDEX, default=0): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=str(index), label=display.name)
                        for index, display in enumerate(device.displays)
                    ]
                )
            ),
            vol.Required(CONF_NAME): str,
            vol.Required(CONF_OUTPUT_ENTITY_ID): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="number")
            ),
            vol.Optional(CONF_LIGHT_ENTITY_ID): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="light")
            ),
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
        }
    )


def _preset_choice_schema(device: Device) -> vol.Schema:
    """Build the schema for choosing one of the device's presets."""
    return vol.Schema(
        {
            vol.Required(CONF_PRESET_INDEX): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=str(index), label=preset.label)
                        for index, preset in enumerate(device.presets)
                    ]
                )
            )
        }
    )
