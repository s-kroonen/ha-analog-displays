"""Converting a source reading into the unit a display is calibrated in.

A preset assignment says what a meter reads *in its own unit* — "0 to 10 kW" —
while the sensor behind it publishes whatever it likes, often watts. Without a
conversion step a 1500 W reading normalised against a 0-10 kW range lands the
needle at full scale instead of at 15 %.

Home Assistant already knows how to convert between units and which conversions
are legitimate, so this module is a thin wrapper over
``homeassistant.components.sensor.const.UNIT_CONVERTERS`` rather than a table of
factors. That matters beyond laziness: temperature is an offset scale, not a
ratio, and a hand-written factor gets 0 °C wrong.
"""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING

from homeassistant.components.sensor.const import UNIT_CONVERTERS

if TYPE_CHECKING:
    from homeassistant.util.unit_conversion import BaseUnitConverter

__all__ = ["compatible", "convert", "converter_for", "units_for"]


def converter_for(device_class: str | None) -> type[BaseUnitConverter] | None:
    """Return the converter Home Assistant uses for a device class."""
    if device_class is None:
        return None
    return UNIT_CONVERTERS.get(device_class)


@cache
def _converter_covering(from_unit: str, to_unit: str) -> type[BaseUnitConverter] | None:
    """Find a converter that knows both units, for sources with no device class.

    Plenty of template sensors publish watts without declaring a device class.
    Searching by unit lets those work instead of refusing to convert. The
    search is ordered by unit class so the answer is stable rather than
    dependent on dict iteration order.
    """
    for converter in sorted(set(UNIT_CONVERTERS.values()), key=lambda c: c.UNIT_CLASS):
        if from_unit in converter.VALID_UNITS and to_unit in converter.VALID_UNITS:
            return converter
    return None


def _resolve(
    from_unit: str | None, to_unit: str | None, device_class: str | None
) -> type[BaseUnitConverter] | None:
    """Pick the converter to use, preferring the source's declared device class."""
    if from_unit is None or to_unit is None:
        return None

    converter = converter_for(device_class)
    if (
        converter is not None
        and from_unit in converter.VALID_UNITS
        and to_unit in converter.VALID_UNITS
    ):
        return converter

    return _converter_covering(from_unit, to_unit)


def compatible(
    from_unit: str | None, to_unit: str | None, device_class: str | None = None
) -> bool:
    """Whether a reading in ``from_unit`` can be expressed in ``to_unit``."""
    if to_unit is None or from_unit == to_unit:
        return True
    return _resolve(from_unit, to_unit, device_class) is not None


def convert(
    value: float,
    from_unit: str | None,
    to_unit: str | None,
    device_class: str | None = None,
) -> float | None:
    """Express ``value`` in ``to_unit``, or ``None`` if that cannot be done.

    Returning ``None`` rather than the unconverted number is deliberate: a
    display silently reading 1000x wrong is worse than one that holds its
    needle and raises a repair issue.
    """
    # No target unit means the assignment is calibrated in whatever the source
    # already publishes, which is the pre-conversion behaviour.
    if to_unit is None or from_unit == to_unit:
        return value

    converter = _resolve(from_unit, to_unit, device_class)
    if converter is None:
        return None

    return converter.convert(value, from_unit, to_unit)


def units_for(device_class: str | None) -> list[str]:
    """Units a display may be calibrated in for this device class.

    Used to populate the unit picker in the config flow, so the offered choices
    come from Home Assistant rather than a list that drifts out of date.
    """
    converter = converter_for(device_class)
    if converter is None:
        return []
    return sorted(str(unit) for unit in converter.VALID_UNITS if unit is not None)
