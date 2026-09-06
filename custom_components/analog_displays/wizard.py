"""The bridge between the runtime model and the YAML generator.

This module exists so the generator never has to know what a preset is, and
the runtime never has to know what a GPIO is. It is the only place that
translates between the two, and it is only ever reached from the config flow
and the ``export_yaml`` service.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .yaml_gen import (
    AddressableLed,
    ButtonSpec,
    DisplaySpec,
    LedSpec,
    RawRgbLed,
    YamlRequest,
)

if TYPE_CHECKING:
    from .models import Device, HardwareProfile

LED_KIND_NONE = "none"
LED_KIND_ADDRESSABLE = "addressable"
LED_KIND_RAW_RGB = "raw_rgb"


def led_from_dict(data: dict[str, Any] | None) -> LedSpec | None:
    """Turn a stored LED wiring dict into a generator LED spec."""
    if not data:
        return None

    kind = data.get("kind", LED_KIND_NONE)
    if kind == LED_KIND_ADDRESSABLE:
        return AddressableLed(
            data_pin=int(data["data_pin"]), index=int(data.get("index", 0))
        )
    if kind == LED_KIND_RAW_RGB:
        return RawRgbLed(
            red_pin=int(data["red_pin"]),
            green_pin=int(data["green_pin"]),
            blue_pin=int(data["blue_pin"]),
        )
    return None


def request_from_profile(device: Device, profile: HardwareProfile) -> YamlRequest:
    """Rebuild the generator's input from what the wizard stored.

    Display and button *names* come from the live configuration rather than
    the profile, so renaming a display in the options flow and re-exporting
    produces YAML that matches what the user now sees.
    """
    displays = [
        DisplaySpec(
            name=_display_name(device, index),
            pin=int(wiring["pin"]),
            led=led_from_dict(wiring.get("led")),
        )
        for index, wiring in enumerate(profile.displays)
    ]
    buttons = [
        ButtonSpec(
            name=_button_name(device, index),
            pin=int(wiring["pin"]),
            multi_click=bool(wiring.get("multi_click", False)),
        )
        for index, wiring in enumerate(profile.buttons)
    ]

    return YamlRequest(
        device_name=device.name,
        board=profile.board,
        displays=displays,
        buttons=buttons,
    )


def _display_name(device: Device, index: int) -> str:
    """Name a display from the live configuration, or fall back to its index."""
    if index < len(device.displays):
        return device.displays[index].name
    return f"Display {index + 1}"


def _button_name(device: Device, index: int) -> str:
    """Name a button from the live configuration, or fall back to its index."""
    if index < len(device.buttons):
        return device.buttons[index].name
    return f"Button {index + 1}"
