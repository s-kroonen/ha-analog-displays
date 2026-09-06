"""The shape of a board profile."""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["BoardProfile"]


@dataclass(frozen=True, slots=True)
class BoardProfile:
    """Everything the generator and the pin validator need about a board."""

    key: str
    name: str
    platform: str
    board: str
    framework: str
    flash_size: str

    usable_gpios: frozenset[int] = field(default_factory=frozenset)
    """Every pin broken out on the board."""

    input_only: frozenset[int] = field(default_factory=frozenset)
    """Pins with no output driver: fine for buttons, useless for meters."""

    strapping: frozenset[int] = field(default_factory=frozenset)
    """Pins latched at boot. Driving one can stop the board starting."""

    reserved: frozenset[int] = field(default_factory=frozenset)
    """Pins wired to the flash chip. Using one bricks the boot."""

    def can_output(self, pin: int) -> bool:
        """Whether a meter or LED may be driven from this pin."""
        return (
            pin in self.usable_gpios
            and pin not in self.input_only
            and pin not in self.strapping
            and pin not in self.reserved
        )

    def can_input(self, pin: int) -> bool:
        """Whether a button may be read from this pin.

        Input-only pins are fine here. Strapping pins are not: holding one at
        the wrong level during boot puts the ESP32 into flash mode, and a
        button is exactly a thing that gets held.
        """
        return (
            pin in self.usable_gpios
            and pin not in self.strapping
            and pin not in self.reserved
        )

    def output_pins(self) -> list[int]:
        """Every pin safe to drive an output from, in order."""
        return sorted(pin for pin in self.usable_gpios if self.can_output(pin))

    def input_pins(self) -> list[int]:
        """Every pin safe to read a button from, in order."""
        return sorted(pin for pin in self.usable_gpios if self.can_input(pin))
