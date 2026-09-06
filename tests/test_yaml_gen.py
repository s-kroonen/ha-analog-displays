"""The ESPHome YAML wizard: pin safety, composition, and snapshots."""

from __future__ import annotations

from typing import Any

import pytest
from syrupy.assertion import SnapshotAssertion
import yaml

from custom_components.analog_displays.yaml_gen import (
    AddressableLed,
    ButtonSpec,
    DisplaySpec,
    RawRgbLed,
    YamlRequest,
    generate_yaml,
    get_board,
    list_boards,
    validate_pins,
)
from custom_components.analog_displays.yaml_gen.fragments import slug

BOARD = "esp32-devkit-v1"


class _ESPHomeLoader(yaml.SafeLoader):
    """A loader that tolerates ESPHome's !lambda and !secret tags."""


def _keep_tag(loader: yaml.Loader, tag_suffix: str, node: yaml.Node) -> Any:
    return f"{tag_suffix}:{node.value}"


_ESPHomeLoader.add_multi_constructor("!", _keep_tag)


def parse(text: str) -> dict[str, Any]:
    """Parse generated YAML, proving it is syntactically valid."""
    return yaml.load(text, Loader=_ESPHomeLoader)


def request(**overrides: Any) -> YamlRequest:
    """Build a wizard request with sane defaults."""
    fields: dict[str, Any] = {
        "device_name": "Meter Panel",
        "board": BOARD,
        "displays": [DisplaySpec("Display 1", 25)],
        "buttons": [],
    }
    return YamlRequest(**(fields | overrides))


# --- board profiles ---------------------------------------------------------


def test_the_reference_board_is_shipped() -> None:
    board = get_board(BOARD)
    assert board.name == "ESP32 DevKit V1"
    assert board.framework == "esp-idf"
    assert [profile.key for profile in list_boards()] == [BOARD]


def test_an_unknown_board_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown board"):
        get_board("esp8266-nonesuch")


@pytest.mark.parametrize("pin", [34, 35, 36, 37, 38, 39])
def test_input_only_pins_cannot_drive_a_meter(pin: int) -> None:
    board = get_board(BOARD)
    assert board.can_output(pin) is False
    # They are still perfectly good for buttons.
    assert board.can_input(pin) is True


@pytest.mark.parametrize("pin", [6, 7, 8, 9, 10, 11])
def test_flash_pins_are_unusable(pin: int) -> None:
    board = get_board(BOARD)
    assert board.can_output(pin) is False
    assert board.can_input(pin) is False


@pytest.mark.parametrize("pin", [0, 2, 12, 15])
def test_strapping_pins_are_refused_for_both_roles(pin: int) -> None:
    """A held button on a strapping pin puts the ESP32 into flash mode."""
    board = get_board(BOARD)
    assert board.can_output(pin) is False
    assert board.can_input(pin) is False


def test_pin_lists_exclude_everything_unsafe() -> None:
    board = get_board(BOARD)
    outputs = set(board.output_pins())

    assert 25 in outputs
    assert outputs.isdisjoint({0, 2, 6, 7, 8, 9, 10, 11, 12, 15, 34, 39})
    assert set(board.input_pins()) >= {4, 5, 34, 39}


# --- pin validation ---------------------------------------------------------


def test_a_safe_layout_validates() -> None:
    assert validate_pins(request()) == {}


def test_a_pin_that_is_not_on_the_board_is_rejected() -> None:
    errors = validate_pins(request(displays=[DisplaySpec("Display 1", 24)]))
    assert errors == {"display_0": "pin_not_on_board"}


def test_an_input_only_pin_is_rejected_for_a_meter() -> None:
    errors = validate_pins(request(displays=[DisplaySpec("Display 1", 36)]))
    assert errors == {"display_0": "pin_not_output_capable"}


@pytest.mark.parametrize("pin", [0, 6, 12])
def test_an_unsafe_pin_is_rejected(pin: int) -> None:
    errors = validate_pins(request(displays=[DisplaySpec("Display 1", pin)]))
    assert errors == {"display_0": "pin_unsafe"}


def test_a_button_on_a_strapping_pin_is_rejected() -> None:
    errors = validate_pins(request(buttons=[ButtonSpec("Boot", 0)]))
    assert errors == {"button_0": "pin_unsafe"}


def test_two_displays_on_one_pin_are_rejected() -> None:
    errors = validate_pins(
        request(displays=[DisplaySpec("Display 1", 25), DisplaySpec("Display 2", 25)])
    )
    assert errors == {"display_1": "pin_duplicate"}


def test_a_button_clashing_with_a_meter_is_rejected() -> None:
    errors = validate_pins(
        request(displays=[DisplaySpec("Display 1", 25)], buttons=[ButtonSpec("B", 25)])
    )
    assert errors == {"button_0": "pin_duplicate"}


def test_a_raw_rgb_channel_clash_is_rejected() -> None:
    errors = validate_pins(
        request(displays=[DisplaySpec("Display 1", 25, RawRgbLed(16, 16, 18))])
    )
    assert errors == {"display_0_led_green": "pin_duplicate"}


def test_sharing_one_addressable_data_pin_is_allowed() -> None:
    """Several meters on one strip is the intended wiring, not a clash."""
    errors = validate_pins(
        request(
            displays=[
                DisplaySpec("Display 1", 25, AddressableLed(13, 0)),
                DisplaySpec("Display 2", 26, AddressableLed(13, 1)),
                DisplaySpec("Display 3", 27, AddressableLed(13, 2)),
            ]
        )
    )
    assert errors == {}


def test_two_displays_claiming_one_led_are_rejected() -> None:
    errors = validate_pins(
        request(
            displays=[
                DisplaySpec("Display 1", 25, AddressableLed(13, 0)),
                DisplaySpec("Display 2", 26, AddressableLed(13, 0)),
            ]
        )
    )
    assert errors == {"display_1_led_index": "pin_duplicate"}


def test_generate_refuses_an_unsafe_layout() -> None:
    with pytest.raises(ValueError, match="unsafe pin assignment"):
        generate_yaml(request(displays=[DisplaySpec("Display 1", 6)]))


# --- the recursion bug this generator must never reintroduce ----------------


def test_the_template_number_never_sets_itself() -> None:
    """number.set inside its own set_action recurses and crashes the ESP32."""
    text = generate_yaml(request())

    assert "number.set" not in text
    assert "output.set_level" in text
    assert "optimistic: true" in text


# --- composition ------------------------------------------------------------


def test_ids_are_slugged_from_names() -> None:
    assert slug("Display 1") == "display_1"
    assert slug("Living Room / Power!") == "living_room_power"
    assert slug("  ") == "unnamed"
    assert slug("4 Meter") == "n4_meter"


def test_a_shared_strip_sizes_itself_from_the_highest_index() -> None:
    text = generate_yaml(
        request(
            displays=[
                DisplaySpec("Display 1", 25, AddressableLed(13, 0)),
                DisplaySpec("Display 2", 26, AddressableLed(13, 2)),
            ]
        )
    )
    parsed = parse(text)

    strips = [
        block for block in parsed["light"] if block["platform"] == "esp32_rmt_led_strip"
    ]
    assert len(strips) == 1
    assert strips[0]["num_leds"] == 3


def test_two_separate_strips_get_two_blocks() -> None:
    text = generate_yaml(
        request(
            displays=[
                DisplaySpec("Display 1", 25, AddressableLed(13, 0)),
                DisplaySpec("Display 2", 26, AddressableLed(19, 0)),
            ]
        )
    )
    parsed = parse(text)

    strips = [
        block for block in parsed["light"] if block["platform"] == "esp32_rmt_led_strip"
    ]
    assert {strip["id"] for strip in strips} == {"strip_gpio13", "strip_gpio19"}


def test_no_empty_sections_are_emitted() -> None:
    parsed = parse(generate_yaml(request()))
    assert "light" not in parsed
    assert "binary_sensor" not in parsed
    assert "event" not in parsed


def test_only_multi_click_buttons_get_an_event_entity() -> None:
    parsed = parse(
        generate_yaml(
            request(
                buttons=[
                    ButtonSpec("Plain", 4),
                    ButtonSpec("Fancy", 5, multi_click=True),
                ]
            )
        )
    )

    assert len(parsed["binary_sensor"]) == 2
    assert len(parsed["event"]) == 1
    assert parsed["event"][0]["event_types"] == ["single", "double", "long"]


# --- snapshots --------------------------------------------------------------


SNAPSHOT_CASES: dict[str, YamlRequest] = {
    "single_display": YamlRequest(
        device_name="Single Meter",
        board=BOARD,
        displays=[DisplaySpec("Power", 25)],
    ),
    "four_displays": YamlRequest(
        device_name="Meter Panel",
        board=BOARD,
        displays=[
            DisplaySpec("Display 1", 25),
            DisplaySpec("Display 2", 26),
            DisplaySpec("Display 3", 27),
            DisplaySpec("Display 4", 14),
        ],
    ),
    "shared_addressable_pin": YamlRequest(
        device_name="Meter Panel",
        board=BOARD,
        displays=[
            DisplaySpec("Display 1", 25, AddressableLed(13, 0)),
            DisplaySpec("Display 2", 26, AddressableLed(13, 1)),
            DisplaySpec("Display 3", 27, AddressableLed(13, 2)),
        ],
    ),
    "mixed_led_types": YamlRequest(
        device_name="Meter Panel",
        board=BOARD,
        displays=[
            DisplaySpec("Display 1", 25, AddressableLed(13, 0)),
            DisplaySpec("Display 2", 26, AddressableLed(13, 1)),
            DisplaySpec("Display 3", 27, AddressableLed(13, 2)),
            DisplaySpec("Display 4", 14, RawRgbLed(16, 17, 18)),
        ],
    ),
    "with_buttons": YamlRequest(
        device_name="Meter Panel",
        board=BOARD,
        displays=[DisplaySpec("Display 1", 25)],
        buttons=[
            ButtonSpec("Cycle", 4, multi_click=True),
            ButtonSpec("Toggle", 5),
        ],
    ),
    "without_buttons": YamlRequest(
        device_name="Meter Panel",
        board=BOARD,
        displays=[DisplaySpec("Display 1", 25)],
    ),
}


@pytest.mark.parametrize("case", sorted(SNAPSHOT_CASES))
def test_generated_yaml_matches_snapshot(
    case: str, snapshot: SnapshotAssertion
) -> None:
    assert generate_yaml(SNAPSHOT_CASES[case]) == snapshot


@pytest.mark.parametrize("case", sorted(SNAPSHOT_CASES))
def test_every_snapshot_case_parses_as_yaml(case: str) -> None:
    """A snapshot that is not valid YAML would not be caught by the diff."""
    parsed = parse(generate_yaml(SNAPSHOT_CASES[case]))

    assert parsed["esphome"]["friendly_name"]
    assert parsed["esp32"]["board"] == "esp32dev"
    assert parsed["number"]
