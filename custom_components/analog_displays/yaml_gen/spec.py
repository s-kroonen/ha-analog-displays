"""What the wizard collected, in the generator's own terms.

These types deliberately do not reuse the integration's runtime model. The
generator is an isolated convenience: nothing outside it may know about GPIOs,
and it may not know about presets, sources or calibration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

__all__ = [
    "AddressableLed",
    "ButtonSpec",
    "DisplaySpec",
    "LedSpec",
    "RawRgbLed",
    "YamlRequest",
]


@dataclass(frozen=True, slots=True)
class AddressableLed:
    """One LED on a shared addressable strip."""

    data_pin: int
    index: int
    kind: Literal["addressable"] = "addressable"


@dataclass(frozen=True, slots=True)
class RawRgbLed:
    """Three PWM channels driving a common-cathode RGB LED."""

    red_pin: int
    green_pin: int
    blue_pin: int
    kind: Literal["raw_rgb"] = "raw_rgb"


LedSpec = AddressableLed | RawRgbLed


@dataclass(frozen=True, slots=True)
class DisplaySpec:
    """One meter and, optionally, its indicator LED."""

    name: str
    pin: int
    led: LedSpec | None = None


@dataclass(frozen=True, slots=True)
class ButtonSpec:
    """One momentary button."""

    name: str
    pin: int
    multi_click: bool = False


@dataclass(frozen=True, slots=True)
class YamlRequest:
    """Everything needed to emit a complete ESPHome configuration."""

    device_name: str
    board: str
    displays: list[DisplaySpec] = field(default_factory=list)
    buttons: list[ButtonSpec] = field(default_factory=list)
