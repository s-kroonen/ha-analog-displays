"""Pure value normalization and rescaling.

Deliberately free of any Home Assistant or hardware concept: everything here
is a plain function over floats, so it can be reasoned about and tested in
isolation.
"""

from __future__ import annotations

__all__ = ["normalize", "to_target"]


def normalize(raw: float, lo: float, hi: float) -> float:
    """Map ``raw`` onto ``0.0-1.0`` given the preset's ``lo``/``hi`` range.

    The result is always clamped. Source values genuinely go out of range —
    dynamic electricity prices turn negative, a power sensor overshoots its
    configured maximum — and a moving-coil needle has hard stops at both ends.

    An inverted range (``hi < lo``) is honoured rather than rejected: it maps
    ``lo`` to 1.0 and ``hi`` to 0.0, which is how a user asks for a reversed
    scale.

    Raises:
        ValueError: if ``lo == hi``, which has no meaningful mapping.
    """
    span = hi - lo
    if span == 0:
        raise ValueError("min_value and max_value must differ")

    return max(0.0, min(1.0, (raw - lo) / span))


def to_target(
    normalized: float,
    out_min: float,
    out_max: float,
    step: float | None = None,
) -> float:
    """Scale a normalized ``0.0-1.0`` value into the target entity's own range.

    Reading ``out_min``/``out_max`` from the target entity at write time is what
    lets a 0.0-1.0 ESPHome template number, someone else's 0-100, and a 0-255
    dimmer all work with no user configuration.

    ``step`` rounds to the target's resolution and snaps to its grid, offset
    from ``out_min`` — a 0-255 entity with ``step: 5`` accepts 0, 5, 10, not
    3 or 7. The result never leaves ``[out_min, out_max]``.
    """
    normalized = max(0.0, min(1.0, normalized))
    target = out_min + normalized * (out_max - out_min)

    if step:
        target = out_min + round((target - out_min) / step) * step
        # Rounding can push a value a hair past an end stop.
        lower, upper = min(out_min, out_max), max(out_min, out_max)
        target = max(lower, min(upper, target))
        # Kill binary-float dust like 0.30000000000000004.
        target = round(target, 10)

    return target
