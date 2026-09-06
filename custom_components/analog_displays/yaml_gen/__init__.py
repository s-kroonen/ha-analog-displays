"""The ESPHome YAML wizard.

Isolated on purpose: nothing outside this package imports it except the config
flow, and nothing inside it knows about presets, sources or calibration. The
wizard is a convenience — a user with hand-written YAML, a different board, or
a non-ESPHome device never touches it.

The integration does not compile or flash anything. This produces text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .boards import BOARDS, BoardProfile, get_board, list_boards
from .fragments import (
    addressable_light_blocks,
    base_block,
    button_blocks,
    display_blocks,
    raw_rgb_blocks,
    section,
)
from .spec import (
    AddressableLed,
    ButtonSpec,
    DisplaySpec,
    LedSpec,
    RawRgbLed,
    YamlRequest,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    "BOARDS",
    "AddressableLed",
    "BoardProfile",
    "ButtonSpec",
    "DisplaySpec",
    "LedSpec",
    "RawRgbLed",
    "YamlRequest",
    "generate_yaml",
    "get_board",
    "list_boards",
    "validate_pins",
]


ERROR_UNKNOWN_PIN = "pin_not_on_board"
ERROR_NOT_OUTPUT = "pin_not_output_capable"
ERROR_UNSAFE = "pin_unsafe"
ERROR_DUPLICATE = "pin_duplicate"


def _assigned_pins(request: YamlRequest) -> Iterator[tuple[int, str, bool]]:
    """Yield every assigned pin as ``(pin, label, needs_output)``.

    A shared addressable data pin is yielded once per display that uses it;
    the duplicate check skips those deliberately, since sharing one strip
    across several meters is the intended wiring.
    """
    for index, display in enumerate(request.displays):
        yield display.pin, f"display_{index}", True

        led = display.led
        if isinstance(led, AddressableLed):
            yield led.data_pin, f"display_{index}_led_data", True
        elif isinstance(led, RawRgbLed):
            yield led.red_pin, f"display_{index}_led_red", True
            yield led.green_pin, f"display_{index}_led_green", True
            yield led.blue_pin, f"display_{index}_led_blue", True

    for index, button in enumerate(request.buttons):
        yield button.pin, f"button_{index}", False


def validate_pins(request: YamlRequest) -> dict[str, str]:
    """Check every pin assignment against the board, keyed by field.

    Returns an empty dict when the wiring is safe. Anything else maps a field
    name to a translated error key, so the config flow can flag exactly which
    input is wrong.
    """
    board = get_board(request.board)
    errors: dict[str, str] = {}

    shared_data_pins = {
        display.led.data_pin
        for display in request.displays
        if isinstance(display.led, AddressableLed)
    }
    seen: dict[int, str] = {}

    for pin, label, needs_output in _assigned_pins(request):
        if pin not in board.usable_gpios:
            errors[label] = ERROR_UNKNOWN_PIN
            continue

        if pin in board.reserved or pin in board.strapping:
            errors[label] = ERROR_UNSAFE
            continue

        if needs_output and not board.can_output(pin):
            errors[label] = ERROR_NOT_OUTPUT
            continue

        if not needs_output and not board.can_input(pin):
            errors[label] = ERROR_UNSAFE
            continue

        if pin in seen and pin not in shared_data_pins:
            errors[label] = ERROR_DUPLICATE
            continue

        seen.setdefault(pin, label)

    _check_strip_indices(request, errors)
    return errors


def _check_strip_indices(request: YamlRequest, errors: dict[str, str]) -> None:
    """Reject two displays claiming the same LED on one shared strip."""
    claimed: set[tuple[int, int]] = set()
    for index, display in enumerate(request.displays):
        led = display.led
        if not isinstance(led, AddressableLed):
            continue
        key = (led.data_pin, led.index)
        if key in claimed:
            errors[f"display_{index}_led_index"] = ERROR_DUPLICATE
        claimed.add(key)


def generate_yaml(request: YamlRequest) -> str:
    """Compose a complete ESPHome configuration for the wizard's answers.

    Raises:
        ValueError: if the board is unknown or any pin assignment is unsafe.
    """
    board = get_board(request.board)

    errors = validate_pins(request)
    if errors:
        raise ValueError(f"unsafe pin assignment: {errors}")

    display_outputs, numbers = display_blocks(request.displays)
    rgb_outputs, rgb_lights = raw_rgb_blocks(request.displays)
    lights = addressable_light_blocks(request.displays) + rgb_lights
    sensors, events = button_blocks(request.buttons)

    parts = [
        base_block(request, board),
        section("output", display_outputs + rgb_outputs),
        section("number", numbers),
        section("light", lights),
        section("binary_sensor", sensors),
        section("event", events),
    ]
    return "\n".join(part for part in parts if part).rstrip() + "\n"
