# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0]

First release.

Requires Home Assistant **2026.2.0** or newer. CI tests against the current
release, the previous minor, and that floor.

### Added

- **Display binding.** Drive any `number` entity from any `sensor` entity.
  Values are normalized against the preset's range, clamped, then rescaled into
  the target entity's own range and step, read live at write time — so a
  0.0–1.0 template number, a 0–100 entity and a 0–255 dimmer all work with no
  configuration.
- **Device-level presets**, up to eight. A preset is a scene across the whole
  board, carrying calibration per display, which lets a handful of meters cover
  far more than a handful of sensors. Sparse presets are allowed: a display no
  preset points at goes to zero with its LED dark.
- **Trailing-edge debouncing** per display, 5 s by default, so a source that
  updates every second does not hammer a mechanical movement. Preset changes
  bypass it and write immediately.
- **Source-outage handling.** The needle holds its last value rather than
  snapping to zero, a repair issue names the device, display, preset and
  entity, and a diagnostic binary sensor marks the display stale. Both clear
  automatically on recovery.
- **Recorder statistics as a source** — mean, min, max, sum, state or change
  over the last hour, today, or the last 24 hours, 7 or 30 days — polled by a
  per-device coordinator that only exists when a preset actually needs it.
- **Indicator LEDs**, coloured by the active preset or by value along a
  gradient of stops placed on the normalized scale, with optional blending
  between stops and explicit dark bands.
- **Buttons** bound to cycling presets, jumping to a preset, firing an event,
  or calling an arbitrary service, from either a `binary_sensor` or an `event`
  entity with click-type filtering. Every press also surfaces as a **device
  trigger** in the automation UI.
- **Entities**: a preset `select` per device (restored across restarts), and
  per display a value sensor in the source's unit, a diagnostic needle-position
  sensor, and a diagnostic staleness binary sensor. All grouped under one Home
  Assistant device per board.
- **Services**: `set_preset`, `next_preset`, `previous_preset`, `refresh`, and
  `export_yaml` as a response service.
- **An optional ESPHome YAML wizard** for the ESP32 DevKit V1, composing
  fragments for meters, addressable and raw-RGB LEDs and buttons. It offers
  only pins that are safe on the board, supports several displays sharing one
  addressable strip, and is fully skippable — binding existing hardware never
  requires it.
- **Diagnostics** with entity ids redacted, and **English and Dutch**
  translations.

### Notes

- The integration never talks to hardware, and never compiles or flashes
  firmware.
- `manifest.json` declares no requirements: everything is Python's standard
  library plus Home Assistant's own helpers.

[Unreleased]: https://github.com/s-kroonen/ha-analog-displays/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/s-kroonen/ha-analog-displays/releases/tag/v0.1.0
