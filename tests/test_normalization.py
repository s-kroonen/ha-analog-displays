"""Unit tests for the pure normalization layer."""

from __future__ import annotations

import pytest

from custom_components.analog_displays.normalization import normalize, to_target


@pytest.mark.parametrize(
    ("raw", "lo", "hi", "expected"),
    [
        # Straightforward interior points.
        (0.0, 0.0, 100.0, 0.0),
        (50.0, 0.0, 100.0, 0.5),
        (100.0, 0.0, 100.0, 1.0),
        # Clamping at both ends: a needle has hard stops.
        (-25.0, 0.0, 100.0, 0.0),
        (250.0, 0.0, 100.0, 1.0),
        # Negative sources, e.g. a dynamic electricity price going negative.
        (-0.10, -0.20, 0.60, 0.125),
        (0.0, -0.20, 0.60, 0.25),
        (-1.0, -0.20, 0.60, 0.0),
        # A range entirely below zero.
        (-15.0, -20.0, -10.0, 0.5),
        # Inverted range: lo maps to 1.0, hi to 0.0.
        (0.0, 100.0, 0.0, 1.0),
        (75.0, 100.0, 0.0, 0.25),
        (100.0, 100.0, 0.0, 0.0),
        (150.0, 100.0, 0.0, 0.0),
    ],
)
def test_normalize(raw: float, lo: float, hi: float, expected: float) -> None:
    assert normalize(raw, lo, hi) == pytest.approx(expected)


def test_normalize_rejects_empty_range() -> None:
    with pytest.raises(ValueError, match="must differ"):
        normalize(5.0, 10.0, 10.0)


@pytest.mark.parametrize(
    ("normalized", "out_min", "out_max", "expected"),
    [
        # An ESPHome template number passes 0.0-1.0 straight through.
        (0.42, 0.0, 1.0, 0.42),
        # Someone else's 0-100.
        (0.42, 0.0, 100.0, 42.0),
        # A 0-255 dimmer.
        (0.42, 0.0, 255.0, 107.1),
        (1.0, 0.0, 255.0, 255.0),
        (0.0, 0.0, 255.0, 0.0),
        # A range that does not start at zero.
        (0.5, 10.0, 20.0, 15.0),
        # A descending target range.
        (0.25, 100.0, 0.0, 75.0),
    ],
)
def test_to_target_rescales(
    normalized: float, out_min: float, out_max: float, expected: float
) -> None:
    assert to_target(normalized, out_min, out_max) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("normalized", "out_min", "out_max", "step", "expected"),
    [
        (0.42, 0.0, 255.0, 1.0, 107.0),
        (0.42, 0.0, 100.0, 5.0, 40.0),
        (0.45, 0.0, 100.0, 5.0, 45.0),
        (0.4234, 0.0, 1.0, 0.001, 0.423),
        # The grid is offset from out_min, not from zero.
        (0.5, 3.0, 13.0, 4.0, 7.0),
        # Rounding must never push past an end stop: the 0/3/6/9 grid has
        # no point at 10, so full scale lands on the highest legal step.
        (1.0, 0.0, 10.0, 3.0, 9.0),
        (0.0, 0.0, 10.0, 3.0, 0.0),
    ],
)
def test_to_target_respects_step(
    normalized: float,
    out_min: float,
    out_max: float,
    step: float,
    expected: float,
) -> None:
    assert to_target(normalized, out_min, out_max, step) == pytest.approx(expected)


def test_to_target_clamps_out_of_range_input() -> None:
    assert to_target(1.5, 0.0, 100.0) == 100.0
    assert to_target(-0.5, 0.0, 100.0) == 0.0


def test_to_target_step_leaves_no_float_dust() -> None:
    """0.1-style steps must not produce 0.30000000000000004."""
    assert to_target(0.3, 0.0, 1.0, 0.1) == 0.3
