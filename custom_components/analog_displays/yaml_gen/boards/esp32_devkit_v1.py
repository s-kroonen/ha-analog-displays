"""The ESP32 DevKit V1, the board this project was prototyped against."""

from __future__ import annotations

from .profile import BoardProfile

ESP32_DEVKIT_V1 = BoardProfile(
    key="esp32-devkit-v1",
    name="ESP32 DevKit V1",
    platform="esp32",
    board="esp32dev",
    framework="esp-idf",
    flash_size="4MB",
    # GPIO 20, 24 and 28-31 do not exist on the ESP32; 34-39 are broken out
    # but input-only.
    usable_gpios=frozenset(
        {*range(20), 21, 22, 23, 25, 26, 27, 32, 33, 34, 35, 36, 37, 38, 39}
    ),
    input_only=frozenset({34, 35, 36, 37, 38, 39}),
    strapping=frozenset({0, 2, 12, 15}),
    reserved=frozenset({6, 7, 8, 9, 10, 11}),
)
