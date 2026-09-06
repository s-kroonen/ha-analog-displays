"""Data model for the Analog Displays integration.

Everything here is plain dataclasses plus dict round-tripping, so the whole
model can be persisted into a config entry's ``options`` and validated without
a running Home Assistant.

Note on shape: presets are **device-level**, not per-display. A preset is a
scene across the whole board — "Power" puts solar, grid, battery and house on
the four meters, "Climate" puts temperatures on them — and each preset carries
one :class:`PresetAssignment` per display it drives. Calibration lives on the
assignment, which is what lets four meters cover far more than four sensors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Self

from .const import (
    ACTION_CALL_SERVICE,
    ACTION_SET_PRESET,
    BUTTON_ACTIONS,
    CONF_ACTION,
    CONF_ACTIVE_PRESET_INDEX,
    CONF_ASSIGNMENTS,
    CONF_AT,
    CONF_BUTTONS,
    CONF_COLOUR,
    CONF_DISPLAYS,
    CONF_END,
    CONF_EVENT_FILTER,
    CONF_FADE,
    CONF_HARDWARE_PROFILE,
    CONF_LABEL,
    CONF_LED,
    CONF_LIGHT_ENTITY_ID,
    CONF_MAX_VALUE,
    CONF_MIN_UPDATE_INTERVAL,
    CONF_MIN_VALUE,
    CONF_MODE,
    CONF_NAME,
    CONF_OUTPUT_ENTITY_ID,
    CONF_PRESETS,
    CONF_SERVICE,
    CONF_SERVICE_DATA,
    CONF_SERVICE_TARGET,
    CONF_SOURCE_ENTITY_ID,
    CONF_SOURCE_MODE,
    CONF_STATISTIC_ENTITY_ID,
    CONF_STATISTIC_PERIOD,
    CONF_STATISTIC_TYPE,
    CONF_STATISTICS_INTERVAL,
    CONF_STOPS,
    CONF_TARGET_PRESET_INDEX,
    CONF_TRIGGER_ENTITY_ID,
    DEFAULT_MIN_UPDATE_INTERVAL,
    DEFAULT_STATISTICS_INTERVAL,
    LED_MODE_GRADIENT,
    LED_MODES,
    MAX_PRESETS,
    MAX_RGB_CHANNEL,
    SOURCE_MODE_ENTITY,
    SOURCE_MODE_STATISTIC,
    SOURCE_MODES,
    STATISTIC_PERIODS,
    STATISTIC_TYPES,
)

RGBColor = tuple[int, int, int]


class AnalogDisplaysConfigError(ValueError):
    """Raised when a persisted or user-supplied configuration is invalid."""


def _as_colour(value: Any) -> RGBColor | None:
    """Coerce a persisted colour into an RGB triple."""
    if value is None:
        return None
    red, green, blue = value
    return (int(red), int(green), int(blue))


def _check_colour(colour: RGBColor | None, where: str) -> None:
    """Validate that every channel of a colour is a byte."""
    if colour is None:
        return
    if any(not 0 <= channel <= MAX_RGB_CHANNEL for channel in colour):
        raise AnalogDisplaysConfigError(f"{where}: colour channels must be 0-255")


@dataclass(frozen=True, slots=True)
class ColourStop:
    """One colour anchored at a normalized position on a display's scale.

    ``at`` is where the colour reaches full strength. ``end`` optionally cuts
    the stop short: with an ``end`` below the next stop's ``at``, the LED goes
    dark in the gap between them instead of carrying the colour onwards.
    """

    at: float
    colour: RGBColor
    end: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for config entry options."""
        return {CONF_AT: self.at, CONF_COLOUR: list(self.colour), CONF_END: self.end}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Deserialize from config entry options."""
        colour = _as_colour(data[CONF_COLOUR])
        if colour is None:
            raise AnalogDisplaysConfigError("colour stop: colour is required")
        end = data.get(CONF_END)
        return cls(
            at=float(data[CONF_AT]),
            colour=colour,
            end=None if end is None else float(end),
        )

    def validate(self, where: str) -> None:
        """Raise if this stop is not a usable point on a 0.0-1.0 scale."""
        if not 0.0 <= self.at <= 1.0:
            raise AnalogDisplaysConfigError(f"{where}: stop position must be 0.0-1.0")
        if self.end is not None:
            if not 0.0 <= self.end <= 1.0:
                raise AnalogDisplaysConfigError(f"{where}: stop end must be 0.0-1.0")
            if self.end <= self.at:
                raise AnalogDisplaysConfigError(
                    f"{where}: stop end must be above its position"
                )
        _check_colour(self.colour, where)


@dataclass(frozen=True, slots=True)
class LedConfig:
    """How a display's indicator LED is driven.

    ``preset`` shows the active preset's assigned colour. ``gradient``
    colours the LED by the display's *normalized* value, so the stops stay
    meaningful across every preset on that display without reconfiguration.
    """

    light_entity_id: str
    mode: str
    stops: list[ColourStop] = field(default_factory=list)
    fade: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize for config entry options."""
        return {
            CONF_LIGHT_ENTITY_ID: self.light_entity_id,
            CONF_MODE: self.mode,
            CONF_STOPS: [stop.to_dict() for stop in self.stops],
            CONF_FADE: self.fade,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Deserialize from config entry options."""
        return cls(
            light_entity_id=data[CONF_LIGHT_ENTITY_ID],
            mode=data[CONF_MODE],
            stops=[ColourStop.from_dict(stop) for stop in data.get(CONF_STOPS, [])],
            fade=bool(data.get(CONF_FADE, False)),
        )

    def validate(self, where: str) -> None:
        """Raise if this LED configuration cannot be driven."""
        if not self.light_entity_id:
            raise AnalogDisplaysConfigError(f"{where}: a light entity is required")
        if self.mode not in LED_MODES:
            raise AnalogDisplaysConfigError(f"{where}: unknown LED mode {self.mode!r}")
        if self.mode == LED_MODE_GRADIENT and not self.stops:
            raise AnalogDisplaysConfigError(
                f"{where}: gradient mode needs at least one colour stop"
            )
        for index, stop in enumerate(self.stops):
            stop.validate(f"{where} stop {index}")


@dataclass(frozen=True, slots=True)
class Display:
    """A physical display and the entities it is bound to.

    This is binding only — which output to write and which LED to colour. What
    it *shows* comes from the active preset's assignment for this display.
    """

    name: str
    output_entity_id: str
    led: LedConfig | None = None
    min_update_interval: timedelta = field(
        default=timedelta(seconds=DEFAULT_MIN_UPDATE_INTERVAL)
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize for config entry options."""
        return {
            CONF_NAME: self.name,
            CONF_OUTPUT_ENTITY_ID: self.output_entity_id,
            CONF_LED: None if self.led is None else self.led.to_dict(),
            CONF_MIN_UPDATE_INTERVAL: self.min_update_interval.total_seconds(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Deserialize from config entry options."""
        led = data.get(CONF_LED)
        return cls(
            name=data[CONF_NAME],
            output_entity_id=data[CONF_OUTPUT_ENTITY_ID],
            led=None if led is None else LedConfig.from_dict(led),
            min_update_interval=timedelta(
                seconds=float(
                    data.get(CONF_MIN_UPDATE_INTERVAL, DEFAULT_MIN_UPDATE_INTERVAL)
                )
            ),
        )

    def validate(self, where: str) -> None:
        """Raise if this display cannot be driven."""
        if not self.name:
            raise AnalogDisplaysConfigError(f"{where}: a name is required")
        if not self.output_entity_id:
            raise AnalogDisplaysConfigError(f"{where}: an output entity is required")
        if self.min_update_interval < timedelta(0):
            raise AnalogDisplaysConfigError(
                f"{where}: minimum update interval cannot be negative"
            )
        if self.led is not None:
            self.led.validate(where)


@dataclass(frozen=True, slots=True)
class PresetAssignment:
    """What one display shows while a given preset is active.

    Calibration (``min_value``/``max_value``) lives here rather than on the
    display, so the same meter can be a 0-3000 W power gauge under one preset
    and a 0-100 % humidity gauge under another.
    """

    source_mode: str = SOURCE_MODE_ENTITY
    source_entity_id: str | None = None
    statistic_entity_id: str | None = None
    statistic_type: str | None = None
    statistic_period: str | None = None
    min_value: float = 0.0
    max_value: float = 100.0
    colour: RGBColor | None = None

    @property
    def statistic_id(self) -> str | None:
        """The recorder statistic id this assignment reads, if any."""
        if self.source_mode != SOURCE_MODE_STATISTIC:
            return None
        return self.statistic_entity_id

    def to_dict(self) -> dict[str, Any]:
        """Serialize for config entry options."""
        return {
            CONF_SOURCE_MODE: self.source_mode,
            CONF_SOURCE_ENTITY_ID: self.source_entity_id,
            CONF_STATISTIC_ENTITY_ID: self.statistic_entity_id,
            CONF_STATISTIC_TYPE: self.statistic_type,
            CONF_STATISTIC_PERIOD: self.statistic_period,
            CONF_MIN_VALUE: self.min_value,
            CONF_MAX_VALUE: self.max_value,
            CONF_COLOUR: None if self.colour is None else list(self.colour),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Deserialize from config entry options."""
        return cls(
            source_mode=data.get(CONF_SOURCE_MODE, SOURCE_MODE_ENTITY),
            source_entity_id=data.get(CONF_SOURCE_ENTITY_ID),
            statistic_entity_id=data.get(CONF_STATISTIC_ENTITY_ID),
            statistic_type=data.get(CONF_STATISTIC_TYPE),
            statistic_period=data.get(CONF_STATISTIC_PERIOD),
            min_value=float(data[CONF_MIN_VALUE]),
            max_value=float(data[CONF_MAX_VALUE]),
            colour=_as_colour(data.get(CONF_COLOUR)),
        )

    def validate(self, where: str) -> None:
        """Raise if this assignment cannot produce a value."""
        if self.source_mode not in SOURCE_MODES:
            raise AnalogDisplaysConfigError(
                f"{where}: unknown source mode {self.source_mode!r}"
            )
        if self.source_mode == SOURCE_MODE_ENTITY:
            if not self.source_entity_id:
                raise AnalogDisplaysConfigError(f"{where}: a source entity is required")
        else:
            if not self.statistic_entity_id:
                raise AnalogDisplaysConfigError(
                    f"{where}: a statistic entity is required"
                )
            if self.statistic_type not in STATISTIC_TYPES:
                raise AnalogDisplaysConfigError(
                    f"{where}: unknown statistic type {self.statistic_type!r}"
                )
            if self.statistic_period not in STATISTIC_PERIODS:
                raise AnalogDisplaysConfigError(
                    f"{where}: unknown statistic period {self.statistic_period!r}"
                )
        # An empty range has no mapping onto the needle; reject it at config
        # time rather than dividing by zero at write time.
        if self.min_value == self.max_value:
            raise AnalogDisplaysConfigError(
                f"{where}: minimum and maximum values must differ"
            )
        _check_colour(self.colour, where)


@dataclass(frozen=True, slots=True)
class Preset:
    """A named scene across the device's displays.

    ``assignments`` is sparse and keyed by display index. A display with no
    assignment is not in use under this preset: its needle goes to zero and
    its LED goes dark.
    """

    label: str
    assignments: dict[int, PresetAssignment] = field(default_factory=dict)

    def assignment_for(self, display_index: int) -> PresetAssignment | None:
        """Return the assignment driving ``display_index``, if any."""
        return self.assignments.get(display_index)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for config entry options.

        Keys are stringified because config entry options round-trip through
        JSON, which has no integer keys.
        """
        return {
            CONF_LABEL: self.label,
            CONF_ASSIGNMENTS: {
                str(index): assignment.to_dict()
                for index, assignment in sorted(self.assignments.items())
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Deserialize from config entry options."""
        return cls(
            label=data[CONF_LABEL],
            assignments={
                int(index): PresetAssignment.from_dict(assignment)
                for index, assignment in data.get(CONF_ASSIGNMENTS, {}).items()
            },
        )

    def validate(self, where: str, display_count: int) -> None:
        """Raise if this preset drives nothing, or drives a display that is gone."""
        if not self.label:
            raise AnalogDisplaysConfigError(f"{where}: a label is required")
        if not self.assignments:
            raise AnalogDisplaysConfigError(
                f"{where}: a preset must drive at least one display"
            )
        for index, assignment in self.assignments.items():
            if not 0 <= index < display_count:
                raise AnalogDisplaysConfigError(
                    f"{where}: assignment refers to unknown display {index}"
                )
            assignment.validate(f"{where} display {index}")


@dataclass(frozen=True, slots=True)
class ButtonBinding:
    """A physical button wired to an action. Global to the device."""

    name: str
    trigger_entity_id: str
    action: str
    event_filter: str | None = None
    target_preset_index: int | None = None
    service: str | None = None
    service_data: dict[str, Any] | None = None
    service_target: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for config entry options."""
        return {
            CONF_NAME: self.name,
            CONF_TRIGGER_ENTITY_ID: self.trigger_entity_id,
            CONF_ACTION: self.action,
            CONF_EVENT_FILTER: self.event_filter,
            CONF_TARGET_PRESET_INDEX: self.target_preset_index,
            CONF_SERVICE: self.service,
            CONF_SERVICE_DATA: self.service_data,
            CONF_SERVICE_TARGET: self.service_target,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Deserialize from config entry options."""
        target = data.get(CONF_TARGET_PRESET_INDEX)
        return cls(
            name=data[CONF_NAME],
            trigger_entity_id=data[CONF_TRIGGER_ENTITY_ID],
            action=data[CONF_ACTION],
            event_filter=data.get(CONF_EVENT_FILTER),
            target_preset_index=None if target is None else int(target),
            service=data.get(CONF_SERVICE),
            service_data=data.get(CONF_SERVICE_DATA),
            service_target=data.get(CONF_SERVICE_TARGET),
        )

    def validate(self, where: str, preset_count: int) -> None:
        """Raise if this binding cannot be dispatched."""
        if not self.name:
            raise AnalogDisplaysConfigError(f"{where}: a name is required")
        if not self.trigger_entity_id:
            raise AnalogDisplaysConfigError(f"{where}: a trigger entity is required")
        if self.action not in BUTTON_ACTIONS:
            raise AnalogDisplaysConfigError(f"{where}: unknown action {self.action!r}")
        if self.action == ACTION_SET_PRESET:
            if self.target_preset_index is None:
                raise AnalogDisplaysConfigError(f"{where}: a target preset is required")
            if not 0 <= self.target_preset_index < preset_count:
                raise AnalogDisplaysConfigError(
                    f"{where}: target preset {self.target_preset_index} does not exist"
                )
        if self.action == ACTION_CALL_SERVICE:
            if not self.service:
                raise AnalogDisplaysConfigError(f"{where}: a service is required")
            if self.service.count(".") != 1 or self.service.startswith("."):
                raise AnalogDisplaysConfigError(
                    f"{where}: service must be 'domain.service', got {self.service!r}"
                )


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    """What the YAML wizard produced, kept so it can be re-exported.

    Present only when the wizard was used. Nothing on a runtime code path may
    read this: a user who brought their own firmware has no profile at all,
    and everything still works.

    ``displays`` and ``buttons`` are plain dicts because this is wiring, not
    behaviour — the generator gives them meaning, and the runtime never looks.
    """

    board: str
    displays: list[dict[str, Any]] = field(default_factory=list)
    buttons: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for config entry options."""
        return {
            "board": self.board,
            "displays": [dict(item) for item in self.displays],
            "buttons": [dict(item) for item in self.buttons],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Deserialize from config entry options."""
        return cls(
            board=data["board"],
            displays=[dict(item) for item in data.get("displays", [])],
            buttons=[dict(item) for item in data.get("buttons", [])],
        )


@dataclass(frozen=True, slots=True)
class Device:
    """One physical board: its displays, its presets and its buttons."""

    name: str
    displays: list[Display] = field(default_factory=list)
    presets: list[Preset] = field(default_factory=list)
    active_preset_index: int = 0
    buttons: list[ButtonBinding] = field(default_factory=list)
    hardware_profile: HardwareProfile | None = None
    statistics_interval: timedelta = field(
        default=timedelta(seconds=DEFAULT_STATISTICS_INTERVAL)
    )

    @property
    def active_preset(self) -> Preset | None:
        """The preset currently driving the displays."""
        if not self.presets:
            return None
        return self.presets[self.active_preset_index % len(self.presets)]

    @property
    def uses_statistics(self) -> bool:
        """Whether any preset reads recorder statistics, so needs polling."""
        return any(
            assignment.source_mode == SOURCE_MODE_STATISTIC
            for preset in self.presets
            for assignment in preset.assignments.values()
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the whole device for config entry options."""
        return {
            CONF_NAME: self.name,
            CONF_DISPLAYS: [display.to_dict() for display in self.displays],
            CONF_PRESETS: [preset.to_dict() for preset in self.presets],
            CONF_ACTIVE_PRESET_INDEX: self.active_preset_index,
            CONF_BUTTONS: [button.to_dict() for button in self.buttons],
            CONF_HARDWARE_PROFILE: (
                None
                if self.hardware_profile is None
                else self.hardware_profile.to_dict()
            ),
            CONF_STATISTICS_INTERVAL: self.statistics_interval.total_seconds(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Deserialize a device from config entry options."""
        profile = data.get(CONF_HARDWARE_PROFILE)
        return cls(
            name=data.get(CONF_NAME, ""),
            displays=[
                Display.from_dict(display) for display in data.get(CONF_DISPLAYS, [])
            ],
            presets=[Preset.from_dict(preset) for preset in data.get(CONF_PRESETS, [])],
            active_preset_index=int(data.get(CONF_ACTIVE_PRESET_INDEX, 0)),
            buttons=[
                ButtonBinding.from_dict(button) for button in data.get(CONF_BUTTONS, [])
            ],
            hardware_profile=(
                None if profile is None else HardwareProfile.from_dict(profile)
            ),
            statistics_interval=timedelta(
                seconds=float(
                    data.get(CONF_STATISTICS_INTERVAL, DEFAULT_STATISTICS_INTERVAL)
                )
            ),
        )

    def validate(self) -> None:
        """Raise :class:`AnalogDisplaysConfigError` if this device is unusable."""
        if not self.name:
            raise AnalogDisplaysConfigError("device: a name is required")
        if not self.displays:
            raise AnalogDisplaysConfigError("device: at least one display is required")
        if not self.presets:
            raise AnalogDisplaysConfigError("device: at least one preset is required")
        if len(self.presets) > MAX_PRESETS:
            raise AnalogDisplaysConfigError(
                f"device: at most {MAX_PRESETS} presets are supported"
            )
        if not 0 <= self.active_preset_index < len(self.presets):
            raise AnalogDisplaysConfigError(
                f"device: active preset {self.active_preset_index} does not exist"
            )
        if self.statistics_interval <= timedelta(0):
            raise AnalogDisplaysConfigError(
                "device: statistics interval must be positive"
            )

        outputs = [display.output_entity_id for display in self.displays]
        if len(set(outputs)) != len(outputs):
            raise AnalogDisplaysConfigError(
                "device: two displays cannot share one output entity"
            )

        for index, display in enumerate(self.displays):
            display.validate(f"display {index}")
        for index, preset in enumerate(self.presets):
            preset.validate(f"preset {index}", len(self.displays))
        for index, button in enumerate(self.buttons):
            button.validate(f"button {index}", len(self.presets))
