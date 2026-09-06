"""Round-tripping and validation of the persisted data model."""

from __future__ import annotations

from datetime import timedelta
import json
from typing import Any

import pytest

from custom_components.analog_displays.models import (
    AnalogDisplaysConfigError,
    ButtonBinding,
    ColourStop,
    Device,
    Display,
    HardwareProfile,
    LedConfig,
    Preset,
    PresetAssignment,
)


def _device(**overrides: Any) -> Device:
    """Build a valid two-display, two-preset device for tests to mutate."""
    base: dict[str, Any] = {
        "name": "Meter Panel",
        "displays": [
            Display(name="Left", output_entity_id="number.left"),
            Display(
                name="Right",
                output_entity_id="number.right",
                led=LedConfig(
                    light_entity_id="light.right",
                    mode="gradient",
                    stops=[ColourStop(at=0.2, colour=(255, 0, 0))],
                    fade=True,
                ),
            ),
        ],
        "presets": [
            Preset(
                label="Power",
                assignments={
                    0: PresetAssignment(
                        source_entity_id="sensor.solar",
                        min_value=0.0,
                        max_value=3000.0,
                        colour=(0, 255, 0),
                    ),
                    1: PresetAssignment(
                        source_entity_id="sensor.grid",
                        min_value=-3000.0,
                        max_value=3000.0,
                    ),
                },
            ),
            # Sparse on purpose: display 1 is unused under this preset.
            Preset(
                label="Climate",
                assignments={
                    0: PresetAssignment(
                        source_mode="statistic",
                        statistic_entity_id="sensor.outside_temp",
                        statistic_type="mean",
                        statistic_period="24h",
                        min_value=-10.0,
                        max_value=40.0,
                    )
                },
            ),
        ],
        "buttons": [
            ButtonBinding(
                name="Cycle",
                trigger_entity_id="binary_sensor.button_1",
                action="cycle_presets",
            )
        ],
    }
    return Device(**(base | overrides))


def test_round_trip_preserves_everything() -> None:
    """to_dict/from_dict must survive a JSON-shaped config entry options blob."""
    device = _device(
        hardware_profile=HardwareProfile(
            board="esp32-devkit-v1",
            displays=[
                {"pin": 25, "led": {"kind": "addressable", "data_pin": 13, "index": 0}},
                {"pin": 26, "led": None},
            ],
            buttons=[{"pin": 4, "multi_click": True}],
        ),
        statistics_interval=timedelta(minutes=10),
    )
    device.validate()

    assert Device.from_dict(device.to_dict()) == device


def test_round_trip_survives_json() -> None:
    """Options really are stored as JSON, so integer keys must not be lost."""
    device = _device()
    restored = Device.from_dict(json.loads(json.dumps(device.to_dict())))

    assert restored == device
    assert set(restored.presets[0].assignments) == {0, 1}


def test_active_preset_and_statistics_detection() -> None:
    device = _device(active_preset_index=1)
    assert device.active_preset is not None
    assert device.active_preset.label == "Climate"
    assert device.uses_statistics is True

    entity_only = _device(presets=[_device().presets[0]])
    assert entity_only.uses_statistics is False


def test_sparse_preset_reports_unassigned_display() -> None:
    """A preset need not drive every display."""
    climate = _device().presets[1]
    assert climate.assignment_for(0) is not None
    assert climate.assignment_for(1) is None


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"name": ""}, "a name is required"),
        ({"displays": []}, "at least one display"),
        ({"presets": []}, "at least one preset"),
        ({"active_preset_index": 5}, "does not exist"),
        ({"statistics_interval": timedelta(0)}, "must be positive"),
    ],
)
def test_device_validation_rejects(overrides: dict[str, Any], match: str) -> None:
    with pytest.raises(AnalogDisplaysConfigError, match=match):
        _device(**overrides).validate()


def test_rejects_more_than_eight_presets() -> None:
    preset = _device().presets[0]
    with pytest.raises(AnalogDisplaysConfigError, match="at most 8 presets"):
        _device(presets=[preset] * 9).validate()


def test_rejects_two_displays_sharing_an_output() -> None:
    with pytest.raises(AnalogDisplaysConfigError, match="share one output"):
        _device(
            displays=[
                Display(name="Left", output_entity_id="number.same"),
                Display(name="Right", output_entity_id="number.same"),
            ]
        ).validate()


def test_rejects_min_equals_max() -> None:
    """An empty calibration range has no mapping onto the needle."""
    with pytest.raises(AnalogDisplaysConfigError, match="must differ"):
        _device(
            presets=[
                Preset(
                    label="Broken",
                    assignments={
                        0: PresetAssignment(
                            source_entity_id="sensor.x",
                            min_value=50.0,
                            max_value=50.0,
                        )
                    },
                )
            ]
        ).validate()


def test_rejects_preset_with_no_assignments() -> None:
    with pytest.raises(AnalogDisplaysConfigError, match="at least one display"):
        _device(presets=[Preset(label="Empty")]).validate()


def test_rejects_assignment_to_missing_display() -> None:
    with pytest.raises(AnalogDisplaysConfigError, match="unknown display 7"):
        _device(
            presets=[
                Preset(
                    label="Ghost",
                    assignments={7: PresetAssignment(source_entity_id="sensor.x")},
                )
            ]
        ).validate()


@pytest.mark.parametrize(
    ("assignment", "match"),
    [
        (PresetAssignment(source_mode="telepathy"), "unknown source mode"),
        (PresetAssignment(source_entity_id=None), "a source entity is required"),
        (
            PresetAssignment(source_mode="statistic"),
            "a statistic entity is required",
        ),
        (
            PresetAssignment(
                source_mode="statistic",
                statistic_entity_id="sensor.x",
                statistic_type="median",
            ),
            "unknown statistic type",
        ),
        (
            PresetAssignment(
                source_mode="statistic",
                statistic_entity_id="sensor.x",
                statistic_type="mean",
                statistic_period="fortnight",
            ),
            "unknown statistic period",
        ),
        (
            PresetAssignment(source_entity_id="sensor.x", colour=(300, 0, 0)),
            "colour channels must be 0-255",
        ),
    ],
)
def test_assignment_validation_rejects(
    assignment: PresetAssignment, match: str
) -> None:
    with pytest.raises(AnalogDisplaysConfigError, match=match):
        assignment.validate("assignment")


@pytest.mark.parametrize(
    ("led", "match"),
    [
        (LedConfig(light_entity_id="", mode="preset"), "a light entity is required"),
        (LedConfig(light_entity_id="light.x", mode="disco"), "unknown LED mode"),
        (
            LedConfig(light_entity_id="light.x", mode="gradient"),
            "at least one colour stop",
        ),
        (
            LedConfig(
                light_entity_id="light.x",
                mode="gradient",
                stops=[ColourStop(at=1.5, colour=(1, 2, 3))],
            ),
            "stop position must be 0.0-1.0",
        ),
        (
            LedConfig(
                light_entity_id="light.x",
                mode="gradient",
                stops=[ColourStop(at=0.5, colour=(1, 2, 3), end=0.4)],
            ),
            "stop end must be above its position",
        ),
        (
            LedConfig(
                light_entity_id="light.x",
                mode="gradient",
                stops=[ColourStop(at=0.5, colour=(1, 2, 3), end=1.4)],
            ),
            "stop end must be 0.0-1.0",
        ),
    ],
)
def test_led_validation_rejects(led: LedConfig, match: str) -> None:
    with pytest.raises(AnalogDisplaysConfigError, match=match):
        led.validate("led")


@pytest.mark.parametrize(
    ("button", "match"),
    [
        (
            ButtonBinding(name="", trigger_entity_id="x", action="fire_event"),
            "a name is required",
        ),
        (
            ButtonBinding(name="B", trigger_entity_id="", action="fire_event"),
            "a trigger entity is required",
        ),
        (
            ButtonBinding(name="B", trigger_entity_id="x", action="explode"),
            "unknown action",
        ),
        (
            ButtonBinding(name="B", trigger_entity_id="x", action="set_preset"),
            "a target preset is required",
        ),
        (
            ButtonBinding(
                name="B",
                trigger_entity_id="x",
                action="set_preset",
                target_preset_index=9,
            ),
            "does not exist",
        ),
        (
            ButtonBinding(name="B", trigger_entity_id="x", action="call_service"),
            "a service is required",
        ),
        (
            ButtonBinding(
                name="B",
                trigger_entity_id="x",
                action="call_service",
                service="toggle",
            ),
            "must be 'domain.service'",
        ),
    ],
)
def test_button_validation_rejects(button: ButtonBinding, match: str) -> None:
    with pytest.raises(AnalogDisplaysConfigError, match=match):
        button.validate("button", preset_count=2)


def test_display_validation_rejects_negative_interval() -> None:
    display = Display(
        name="Left",
        output_entity_id="number.left",
        min_update_interval=timedelta(seconds=-1),
    )
    with pytest.raises(AnalogDisplaysConfigError, match="cannot be negative"):
        display.validate("display 0")


def test_colour_stop_requires_a_colour() -> None:
    with pytest.raises(AnalogDisplaysConfigError, match="colour is required"):
        ColourStop.from_dict({"at": 0.5, "colour": None})
