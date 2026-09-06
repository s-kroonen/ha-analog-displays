"""Board profiles for the ESPHome YAML wizard.

Each profile is data, not code: the variant, framework and — most importantly —
which GPIOs are safe to use for what. That is what lets the config flow reject
a pin that would stop the board booting, before the user flashes anything.

Adding a board is one module here plus one entry in :data:`BOARDS`.
"""

from __future__ import annotations

from .esp32_devkit_v1 import ESP32_DEVKIT_V1
from .profile import BoardProfile

__all__ = ["BOARDS", "BoardProfile", "get_board", "list_boards"]

BOARDS: dict[str, BoardProfile] = {
    ESP32_DEVKIT_V1.key: ESP32_DEVKIT_V1,
}


def get_board(key: str) -> BoardProfile:
    """Look up a board profile by key."""
    try:
        return BOARDS[key]
    except KeyError:
        raise ValueError(f"unknown board {key!r}") from None


def list_boards() -> list[BoardProfile]:
    """Every board the wizard can generate for."""
    return sorted(BOARDS.values(), key=lambda profile: profile.name)
