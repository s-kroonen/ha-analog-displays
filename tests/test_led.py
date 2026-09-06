"""LED colour resolution: gradient stops, hard switching, and gaps."""

from __future__ import annotations

import pytest

from custom_components.analog_displays.led import mix, resolve_colour
from custom_components.analog_displays.models import ColourStop, RGBColor

RED: RGBColor = (255, 0, 0)
AMBER: RGBColor = (255, 191, 0)
GREEN: RGBColor = (0, 255, 0)
BLUE: RGBColor = (0, 0, 255)

# The reference battery gauge: red from 20 %, amber from 50 %, green from 80 %.
BATTERY = [
    ColourStop(at=0.20, colour=RED),
    ColourStop(at=0.50, colour=AMBER),
    ColourStop(at=0.80, colour=GREEN),
]


def test_no_stops_means_off() -> None:
    assert resolve_colour([], 0.5, fade=True) is None


@pytest.mark.parametrize("fade", [True, False])
def test_below_the_first_stop_the_led_is_off(fade: bool) -> None:
    """Nothing is lit until the first threshold is reached."""
    assert resolve_colour(BATTERY, 0.10, fade=fade) is None
    assert resolve_colour(BATTERY, 0.0, fade=fade) is None


# --- hard switching ---------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.20, RED),
        (0.45, RED),
        (0.499, RED),
        (0.50, AMBER),
        (0.70, AMBER),
        (0.799, AMBER),
        (0.80, GREEN),
        (1.0, GREEN),
    ],
)
def test_fade_off_switches_sharply_at_each_stop(
    value: float, expected: RGBColor
) -> None:
    """With blending off, the last stop at or below the value wins outright."""
    assert resolve_colour(BATTERY, value, fade=False) == expected


# --- blending ---------------------------------------------------------------


def test_fade_on_blends_between_surrounding_stops() -> None:
    """The reference case: orange at 45 %, yellow-green at 70 %."""
    at_45 = resolve_colour(BATTERY, 0.45, fade=True)
    assert at_45 == mix(RED, AMBER, (0.45 - 0.20) / (0.50 - 0.20))
    # Red held, green absent, amber most of the way in: orange.
    assert at_45 == (255, 159, 0)

    at_70 = resolve_colour(BATTERY, 0.70, fade=True)
    assert at_70 == mix(AMBER, GREEN, (0.70 - 0.50) / (0.80 - 0.50))
    assert at_70 == (85, 234, 0)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.20, RED),
        (0.50, AMBER),
        (0.80, GREEN),
        # Past the last stop the colour is held, not extrapolated.
        (0.90, GREEN),
        (1.0, GREEN),
    ],
)
def test_fade_on_lands_exactly_on_each_stop(value: float, expected: RGBColor) -> None:
    assert resolve_colour(BATTERY, value, fade=True) == expected


def test_fade_is_monotonic_across_the_scale() -> None:
    """Sweeping the value must not make the colour jump backwards."""
    reds = [resolve_colour(BATTERY, step / 100, fade=True) for step in range(50, 81)]
    greens = [colour[1] for colour in reds if colour is not None]
    assert greens == sorted(greens)


# --- gaps -------------------------------------------------------------------


@pytest.mark.parametrize("fade", [True, False])
def test_an_explicit_end_turns_the_led_off_in_the_gap(fade: bool) -> None:
    """A stop that ends before the next one begins leaves a dark band."""
    stops = [
        ColourStop(at=0.2, colour=RED, end=0.4),
        ColourStop(at=0.6, colour=GREEN),
    ]
    assert resolve_colour(stops, 0.3, fade=fade) is not None
    assert resolve_colour(stops, 0.5, fade=fade) is None
    assert resolve_colour(stops, 0.7, fade=fade) == GREEN


@pytest.mark.parametrize("fade", [True, False])
def test_an_end_on_the_last_stop_closes_the_top(fade: bool) -> None:
    stops = [ColourStop(at=0.2, colour=RED, end=0.8)]
    assert resolve_colour(stops, 0.5, fade=fade) == RED
    assert resolve_colour(stops, 0.9, fade=fade) is None


# --- ordering and edge cases ------------------------------------------------


def test_stops_need_not_be_supplied_in_order() -> None:
    shuffled = [BATTERY[2], BATTERY[0], BATTERY[1]]
    assert resolve_colour(shuffled, 0.45, fade=False) == RED
    assert resolve_colour(shuffled, 0.85, fade=False) == GREEN


def test_coincident_stops_do_not_divide_by_zero() -> None:
    stops = [ColourStop(at=0.5, colour=RED), ColourStop(at=0.5, colour=BLUE)]
    assert resolve_colour(stops, 0.5, fade=True) in (RED, BLUE)


def test_a_single_stop_holds_its_colour() -> None:
    stops = [ColourStop(at=0.0, colour=BLUE)]
    assert resolve_colour(stops, 0.0, fade=True) == BLUE
    assert resolve_colour(stops, 1.0, fade=True) == BLUE


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        (0.0, (0, 0, 0)),
        (1.0, (100, 200, 50)),
        (0.5, (50, 100, 25)),
        # Ratios outside 0-1 are clamped rather than extrapolated.
        (-1.0, (0, 0, 0)),
        (2.0, (100, 200, 50)),
    ],
)
def test_mix(ratio: float, expected: RGBColor) -> None:
    assert mix((0, 0, 0), (100, 200, 50), ratio) == expected
