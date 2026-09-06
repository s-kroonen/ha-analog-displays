"""Colour resolution for indicator LEDs.

Stops are gradient anchors on the display's *normalized* scale, not on raw
units. That is deliberate: a stop set at 0.8 stays "near full scale" under
every preset on that display, so the LED keeps meaning something when the
preset switches a meter from watts to degrees.

Below the first stop the LED is off, which is what makes a battery gauge read
naturally: nothing lit until the first threshold is reached.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .models import ColourStop, RGBColor

__all__ = ["mix", "resolve_colour"]


def mix(start: RGBColor, end: RGBColor, ratio: float) -> RGBColor:
    """Blend two colours channel by channel, ``ratio`` 0.0 giving ``start``."""
    ratio = max(0.0, min(1.0, ratio))
    return (
        round(start[0] + (end[0] - start[0]) * ratio),
        round(start[1] + (end[1] - start[1]) * ratio),
        round(start[2] + (end[2] - start[2]) * ratio),
    )


def resolve_colour(
    stops: Sequence[ColourStop], value: float, fade: bool
) -> RGBColor | None:
    """Return the LED colour for a normalized ``value``, or ``None`` for off.

    With ``fade`` off the LED switches sharply: the last stop at or below the
    value wins, at full colour. With ``fade`` on the colour is interpolated
    between the two surrounding stops, so a battery gauge with red at 0.20,
    amber at 0.50 and green at 0.80 reads orange at 0.45 and yellow-green at
    0.70.

    A stop's optional ``end`` cuts it short: past ``end``, and before the next
    stop begins, the LED goes dark instead of carrying the colour onwards.
    """
    if not stops:
        return None

    ordered = sorted(stops, key=lambda stop: stop.at)
    if value < ordered[0].at:
        return None

    index = 0
    for candidate, stop in enumerate(ordered):
        if stop.at <= value:
            index = candidate
        else:
            break

    current = ordered[index]
    if current.end is not None and value > current.end:
        # An explicit gap between this stop and the next one.
        return None

    following = ordered[index + 1] if index + 1 < len(ordered) else None
    if not fade or following is None:
        return current.colour

    span = following.at - current.at
    if span <= 0:
        return current.colour

    return mix(current.colour, following.colour, (value - current.at) / span)
