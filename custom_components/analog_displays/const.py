"""Constants for the Analog Displays integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "analog_displays"

# --- Config entry / options keys -------------------------------------------

CONF_NAME: Final = "name"
CONF_DISPLAYS: Final = "displays"
CONF_PRESETS: Final = "presets"
CONF_BUTTONS: Final = "buttons"
CONF_ACTIVE_PRESET_INDEX: Final = "active_preset_index"
CONF_HARDWARE_PROFILE: Final = "hardware_profile"
CONF_STATISTICS_INTERVAL: Final = "statistics_interval"

CONF_OUTPUT_ENTITY_ID: Final = "output_entity_id"
CONF_MIN_UPDATE_INTERVAL: Final = "min_update_interval"
CONF_LED: Final = "led"

CONF_ADD_ANOTHER: Final = "add_another"
CONF_LABEL: Final = "label"
CONF_ASSIGNMENTS: Final = "assignments"
CONF_SOURCE_MODE: Final = "source_mode"
CONF_SOURCE_ENTITY_ID: Final = "source_entity_id"
CONF_STATISTIC_ENTITY_ID: Final = "statistic_entity_id"
CONF_STATISTIC_TYPE: Final = "statistic_type"
CONF_STATISTIC_PERIOD: Final = "statistic_period"
CONF_MIN_VALUE: Final = "min_value"
CONF_MAX_VALUE: Final = "max_value"
CONF_COLOUR: Final = "colour"

CONF_LIGHT_ENTITY_ID: Final = "light_entity_id"
CONF_MODE: Final = "mode"
CONF_STOPS: Final = "stops"
CONF_FADE: Final = "fade"
CONF_AT: Final = "at"
CONF_END: Final = "end"

CONF_TRIGGER_ENTITY_ID: Final = "trigger_entity_id"
CONF_EVENT_FILTER: Final = "event_filter"
CONF_ACTION: Final = "action"
CONF_TARGET_PRESET_INDEX: Final = "target_preset_index"
CONF_SERVICE: Final = "service"
CONF_SERVICE_DATA: Final = "service_data"
CONF_SERVICE_TARGET: Final = "service_target"

# --- Enumerated option values ----------------------------------------------

SOURCE_MODE_ENTITY: Final = "entity"
SOURCE_MODE_STATISTIC: Final = "statistic"
SOURCE_MODES: Final = (SOURCE_MODE_ENTITY, SOURCE_MODE_STATISTIC)

STATISTIC_TYPES: Final = ("mean", "min", "max", "sum", "state", "change")
STATISTIC_PERIODS: Final = ("hour", "today", "24h", "7d", "30d")

LED_MODE_PRESET: Final = "preset"
LED_MODE_GRADIENT: Final = "gradient"
LED_MODE_OFF: Final = "off"
LED_MODES: Final = (LED_MODE_PRESET, LED_MODE_GRADIENT, LED_MODE_OFF)

ACTION_CYCLE_PRESETS: Final = "cycle_presets"
ACTION_SET_PRESET: Final = "set_preset"
ACTION_FIRE_EVENT: Final = "fire_event"
ACTION_CALL_SERVICE: Final = "call_service"
BUTTON_ACTIONS: Final = (
    ACTION_CYCLE_PRESETS,
    ACTION_SET_PRESET,
    ACTION_FIRE_EVENT,
    ACTION_CALL_SERVICE,
)

# --- Defaults and limits ---------------------------------------------------

MAX_RGB_CHANNEL: Final = 255

DEFAULT_MIN_UPDATE_INTERVAL: Final = 5.0
DEFAULT_STATISTICS_INTERVAL: Final = 300.0
MAX_PRESETS: Final = 8

# --- Events ----------------------------------------------------------------

EVENT_BUTTON_PRESSED: Final = f"{DOMAIN}_button_pressed"

# --- Services --------------------------------------------------------------

SERVICE_SET_PRESET: Final = "set_preset"
SERVICE_NEXT_PRESET: Final = "next_preset"
SERVICE_PREVIOUS_PRESET: Final = "previous_preset"
SERVICE_REFRESH: Final = "refresh"
SERVICE_EXPORT_YAML: Final = "export_yaml"
