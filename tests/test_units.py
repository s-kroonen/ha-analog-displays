"""Converting a source reading into the unit a display is calibrated in."""

from __future__ import annotations

import pytest

from custom_components.analog_displays.normalization import normalize
from custom_components.analog_displays.units import (
    compatible,
    convert,
    converter_for,
    units_for,
)

# --- the bug this module exists to fix --------------------------------------


def test_watts_against_a_kilowatt_scale() -> None:
    """A 1500 W source on a 0-10 kW display sits at 15 %, not full scale."""
    raw = 1500.0  # W, straight off the sensor
    converted = convert(raw, "W", "kW", "power")

    assert converted == 1.5
    assert normalize(converted, 0.0, 10.0) == pytest.approx(0.15)

    # Without the conversion the same reading pins the needle: the 1000x bug.
    assert normalize(raw, 0.0, 10.0) == 1.0


def test_temperature_is_an_offset_scale_not_a_ratio() -> None:
    """A hand-written factor gets 0 C wrong; this is why HA does the maths."""
    assert convert(0.0, "°C", "°F", "temperature") == 32.0
    assert convert(20.0, "°C", "°F", "temperature") == 68.0
    assert convert(-40.0, "°C", "°F", "temperature") == -40.0


# --- passthrough ------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "from_unit", "to_unit"),
    [
        (42.0, "W", "W"),
        (42.0, "W", None),
        (42.0, None, None),
    ],
)
def test_no_conversion_needed(
    value: float, from_unit: str | None, to_unit: str | None
) -> None:
    """No target unit means calibrated in whatever the source publishes."""
    assert convert(value, from_unit, to_unit, "power") == value


# --- the breadth the user asked for -----------------------------------------


@pytest.mark.parametrize(
    ("device_class", "value", "from_unit", "to_unit", "expected"),
    [
        ("power", 2.5, "kW", "W", 2500.0),
        ("energy", 1.0, "kWh", "Wh", 1000.0),
        ("data_size", 1.0, "GB", "MB", 1000.0),
        ("data_rate", 1.0, "Gbit/s", "Mbit/s", 1000.0),
        ("duration", 2.0, "h", "min", 120.0),
        ("pressure", 1.0, "bar", "Pa", 100000.0),
        ("distance", 1.0, "km", "m", 1000.0),
        ("speed", 1.0, "km/h", "m/s", 0.2777777),
    ],
)
def test_conversions_across_quantity_kinds(
    device_class: str,
    value: float,
    from_unit: str,
    to_unit: str,
    expected: float,
) -> None:
    """Temperature to energy to time to data, using Home Assistant's tables."""
    assert convert(value, from_unit, to_unit, device_class) == pytest.approx(expected)


# --- sources without a device class -----------------------------------------


def test_units_alone_are_enough_when_no_device_class_is_declared() -> None:
    """Plenty of template sensors publish watts without a device class."""
    assert convert(1500.0, "W", "kW", None) == 1.5
    assert convert(1500.0, "W", "kW", "") == 1.5


def test_a_wrong_device_class_falls_back_to_the_units() -> None:
    """A mislabelled sensor should still convert if the units make sense."""
    assert convert(1500.0, "W", "kW", "temperature") == 1.5


# --- refusing rather than guessing ------------------------------------------


@pytest.mark.parametrize(
    ("from_unit", "to_unit"),
    [
        ("W", "°C"),  # different quantities entirely
        ("W", "not-a-unit"),
        ("not-a-unit", "W"),
        (None, "kW"),  # source publishes no unit at all
    ],
)
def test_incompatible_conversions_return_none(
    from_unit: str | None, to_unit: str
) -> None:
    """None, never a wrong number: the needle holds instead of lying."""
    assert convert(1.0, from_unit, to_unit, "power") is None
    assert compatible(from_unit, to_unit, "power") is False


def test_compatible_reports_true_for_the_passthrough_cases() -> None:
    assert compatible("W", "W", "power") is True
    assert compatible("W", None, "power") is True
    assert compatible(None, None, None) is True


# --- populating the config flow's unit picker -------------------------------


def test_units_for_offers_the_real_choices() -> None:
    power = units_for("power")

    assert "W" in power
    assert "kW" in power
    assert power == sorted(power), "offered units should be stable and ordered"


def test_units_for_an_unknown_device_class_is_empty() -> None:
    assert units_for(None) == []
    assert units_for("not-a-device-class") == []


def test_converter_for_maps_device_classes() -> None:
    assert converter_for("power") is not None
    assert converter_for("temperature") is not converter_for("power")
    assert converter_for(None) is None
