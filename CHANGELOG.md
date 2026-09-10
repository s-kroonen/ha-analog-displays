# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Editing starts from the configuration in force.** Every field on every
  edit page is pre-filled with what is stored: a display's name, output, LED
  and interval, and a preset's name, blink colour, source, unit, range, LED
  mode and each of its zones. Changing one threshold no longer means retyping
  a display's whole calibration from memory, which is how thresholds drift out
  of step with the meter they describe.
- Editing a display asks which one first and then shows that display's own
  form, so the fields can be filled in from it. With a single display the
  picker is skipped.

### Added

- **Per-meter trim.** Each display gains a *signal at needle zero* and a *signal
  at full scale*, as percentages of its output's range, defaulting to 0 % and
  100 %. They correct the movement itself — one that hits its stop at 92 % of
  drive, or rests off zero — and apply under every preset, since the deviation
  belongs to the hardware. The value being shown is still scaled by the preset,
  in real units.
- **Presets can be edited.** Previously the only way to change a preset's
  range, unit or LED zones was to delete it and build it again from an empty
  form, which also lost its position in the list.

### Fixed

- **A preset's blink colour is now stored.** It was collected during setup and
  then dropped, so the light feedback on switching presets could not be
  configured at all.
- **LED zones can be set when adding a preset from the options flow.** It
  asked how many zones to use and then never asked for them, leaving a
  gradient preset that failed validation.
- A preset rejected for driving nothing left the flow pointing past the last
  display, so the form it showed could not be submitted.

## [0.1.1]

### Changed

- **Value ranges now carry a unit, and the source is converted into it.** A
  sensor reporting watts against a display calibrated in kilowatts previously
  read a thousand times high with nothing to indicate anything was wrong.
  Conversion uses Home Assistant's own converters, covering power, energy,
  temperature, data size and rate, duration, pressure, distance, speed and
  more. Leaving the unit empty keeps the old behaviour of reading the source
  as-is, and a conversion that cannot be done holds the needle rather than
  displaying a wrong number.
- **LED behaviour moved from the display onto each preset assignment**, so
  thresholds can be written in real units — "red from 2 kW" rather than "red
  from 0.2 of full scale". A display-level threshold in kW would have been
  meaningless under a preset showing degrees. The display still owns which
  light it drives.
- **The config flow asks how many displays and buttons up front** instead of
  chaining "add another" checkboxes, since those are facts about the device.
- Source entities widened beyond sensors to include numbers, input numbers and
  counters, with a check that the chosen entity's state is actually numeric.

Existing configurations are migrated automatically and keep behaving exactly as
they did: old threshold positions are converted from fractions into real values
against the range they belong to, and no unit conversion is introduced.

### Added

- **LED zones are configurable at last.** Earlier versions seeded a single
  hard-coded stop and had no editor for it anywhere, despite a comment claiming
  otherwise.
- **Presets can blink for confirmation.** Give a preset a colour and every
  display it drives flashes twice on activation, then returns to normal —
  useful on a board with no screen.

### Fixed

- Release tags spelled with a capital `V` no longer fail the version check.
  `release.yml` stripped only a lowercase `v`, so a `V0.1.0` tag was compared
  literally against the manifest version and rejected.
- The changelog links pointed at a `v0.1.0` tag that was never published; they
  now use the tagless form the releases actually use.

### Added

- `scripts/bump_version.py`, which moves `manifest.json` and this changelog to
  a new version together, refuses to go backwards, and refuses to cut a release
  from an empty `Unreleased` section.
- A test asserting the manifest version matches the newest changelog section,
  so the two cannot drift into a failed release run.

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

[Unreleased]: https://github.com/s-kroonen/ha-analog-displays/compare/0.1.1...HEAD
[0.1.1]: https://github.com/s-kroonen/ha-analog-displays/releases/tag/0.1.1
[0.1.0]: https://github.com/s-kroonen/ha-analog-displays/releases/tag/0.1.0
