# Project Brief: `analog_displays` — Home Assistant Custom Integration

Build a Home Assistant custom integration, distributable via HACS, that drives
analog displays (moving-coil meters and later other display types) from any
Home Assistant sensor data.

Build it from scratch, in a fresh repository, with full CI/CD and HACS
publication readiness. Work through the phases at the bottom of this document
in order.

---

## 1. Core philosophy — read this first

**ESPHome is the hardware interface. This integration is the brains.**

The integration must **never** talk to hardware directly. It reads and writes
ordinary Home Assistant entities:

| Role | Bound to |
|---|---|
| Display output | a `number` entity |
| Display indicator LED | a `light` entity |
| Button input | a `binary_sensor` or `event` entity |
| Data source | any `sensor` entity (or recorder statistics) |

Consequences that must hold true in the design:

- A user with hand-written ESPHome YAML, a completely different board, or a
  non-ESPHome device (Tasmota, Zigbee dimmer, anything exposing a `number`)
  can use this integration with zero changes.
- The bundled YAML generator is a **convenience wizard only**. It must be
  fully skippable and must not be a dependency of any runtime code path.
- Changing which sensor feeds a display, its calibration, its presets, or its
  button actions must **never require recompiling or reflashing firmware**.

**Do not couple the logic layer to ESPHome.** If any module outside
`yaml_gen/` imports ESPHome-specific concepts, the design is wrong.

---

## 2. Architecture

Three layers, cleanly separated:

```
┌─────────────────────────────────────────────────────┐
│ Layer 1 (optional): YAML Wizard                      │
│ Board + pins + features -> downloadable ESPHome YAML │
│ Skippable. No runtime dependency.                    │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│ Layer 2: Binding                                     │
│ Map HA entities to display outputs / LEDs / buttons  │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│ Layer 3: Logic (the actual product)                  │
│ Presets, statistics, normalization, thresholds,      │
│ debounce, error handling, button actions             │
└─────────────────────────────────────────────────────┘
```

### 2.1 Output backend abstraction — required from day one

All writes to a display go through an abstract backend. This is not optional
scaffolding; an LCD/text backend is a planned future feature and must not
require a refactor.

```python
class OutputBackend(ABC):
    """Renders a normalized value onto some physical output."""

    @abstractmethod
    async def write(self, value: NormalizedValue) -> None: ...

    @abstractmethod
    async def clear(self) -> None: ...

    @property
    @abstractmethod
    def capabilities(self) -> BackendCapabilities: ...
```

Implement `NumberEntityBackend` now. Structure the code so
`TextEntityBackend` / `LcdBackend` can be added later by writing one class and
registering it — no changes to preset, normalization, or config-flow logic.

`NormalizedValue` should carry both the normalized `0.0–1.0` float **and** the
raw source value plus unit, so a future text/LCD backend can render
`"1234 W"` while the analog backend renders `0.42`.

---

## 3. Data model

Use `dataclasses` (or Pydantic-free `TypedDict`s + validators, your call) in
`models.py`. Persist in the config entry's `options`.

### Device (one per config entry)

One config entry per physical board. Multiple boards must be supported from
day one.

```
Device
  name: str
  displays: list[Display]          # 1..N
  buttons: list[ButtonBinding]     # 0..N, GLOBAL to the device, not per display
  hardware_profile: HardwareProfile | None   # only if the wizard was used
```

### Display

```
Display
  name: str
  output_entity_id: str            # a number entity
  led: LedConfig | None
  presets: list[Preset]            # 1..8, ordered
  active_preset_index: int         # restored across restarts
  min_update_interval: timedelta   # default 5s
```

### Preset

Presets are user-defined menus. **Calibration lives on the preset, not the
display** — this is what lets 4 meters cover far more than 4 sensors.

```
Preset
  label: str
  source_mode: Literal["entity", "statistic"]

  # source_mode == "entity"
  source_entity_id: str

  # source_mode == "statistic"
  statistic_entity_id: str
  statistic_type: Literal["mean", "min", "max", "sum", "state", "change"]
  statistic_period: Literal["hour", "today", "24h", "7d", "30d"]

  min_value: float                 # maps to needle 0.0
  max_value: float                 # maps to needle 1.0
  colour: RGBColor | None          # used in LED mode "preset"
```

### LedConfig

```
LedConfig
  light_entity_id: str
  mode: Literal["preset", "threshold", "off"]
  thresholds: list[Threshold]      # mode == "threshold"
```

```
Threshold
  above: float                     # NORMALIZED 0.0-1.0, not raw units
  colour: RGBColor
```

Thresholds are deliberately defined against the **normalized** value so they
remain meaningful across every preset on that display without
reconfiguration. Evaluate highest-matching-`above` wins; below all thresholds
means "base" colour (first threshold's implicit inverse, or off).

### ButtonBinding

Buttons are a **global device feature**, not a per-display one.

```
ButtonBinding
  name: str
  trigger_entity_id: str                  # binary_sensor or event entity
  event_filter: str | None                # e.g. "single", "double", "long" for event entities
  action: Literal["cycle_presets", "set_preset", "fire_event", "call_service"]

  target_display_index: int | None        # cycle_presets / set_preset
  target_preset_index: int | None         # set_preset
  service: str | None                     # call_service, e.g. "light.toggle"
  service_data: dict | None
  service_target: dict | None
```

`cycle_presets` advances the target display's active preset with wraparound.
`fire_event` fires an HA event (`analog_displays_button_pressed`) with device
and button context so users can wire arbitrary automations.

---

## 4. Runtime behaviour

### 4.1 Normalization and writing

```python
normalized = clamp((raw - preset.min_value) / (preset.max_value - preset.min_value), 0.0, 1.0)
```

Always clamp to `[0, 1]`. This generically handles negative source values
(dynamic electricity prices can go negative; a moving-coil needle cannot).

Then scale into the **target entity's own range**, read from its `min` / `max`
attributes at write time:

```python
target = out_min + normalized * (out_max - out_min)
```

This means a `0.0–1.0` ESPHome template number, someone else's `0–100`, and a
`0–255` dimmer all work with no user configuration. Respect the target
entity's `step` attribute when rounding. Guard against
`max_value == min_value` (config validation should reject it).

Write via `number.set_value`.

### 4.2 Update triggers and debounce

- `source_mode == "entity"`: subscribe with `async_track_state_change_event`.
  This is push — hence `iot_class: local_push`.
- `source_mode == "statistic"`: statistics do not push. Use a
  `DataUpdateCoordinator` per device polling only the statistic-backed
  presets, default interval 5 minutes, user-configurable.

Enforce `min_update_interval` (default 5 s) per display: coalesce rapid source
updates and write at most once per interval, always writing the **latest**
value (trailing-edge debounce, not leading-edge). Rationale: a power sensor
may update every second, and hammering a mechanical movement is pointless and
shortens its life.

Always write immediately on preset change, regardless of debounce.

### 4.3 Unavailable / unknown source

When the active preset's source becomes `unavailable`, `unknown`, or
non-numeric:

1. **Hold the last displayed value.** Never snap the needle to zero — a stale
   but plausible reading is far better than a confidently wrong one.
2. Log an error.
3. Raise a **repair issue** (`homeassistant.helpers.issue_registry`) naming
   the device, display, preset, and offending entity. Clear it automatically
   when the source recovers.
4. Mark the integration's diagnostic sensor for that display as stale.

Do **not** signal this via the LED — LEDs are for preset/threshold display
only.

---

## 5. Entities exposed by the integration

Grouped under one HA device per config entry via `device_info`.

| Platform | Per | Purpose |
|---|---|---|
| `select` | display | Active preset (options = preset labels). Writable. |
| `sensor` | display | Current raw source value, with the source's unit. |
| `sensor` | display | Current normalized value (`%`), diagnostic category. |
| `binary_sensor` | display | Source stale/unavailable, diagnostic category. |

Also provide **device triggers** for button presses so users get them in the
automation UI without knowing event names.

### Services

- `analog_displays.set_preset` — target display entity + preset index or label
- `analog_displays.next_preset` / `analog_displays.previous_preset`
- `analog_displays.refresh` — force re-read and write
- `analog_displays.export_yaml` — regenerate and return the ESPHome YAML for a
  device (response service, so it can be used from Developer Tools)

---

## 6. Config flow

Full GUI configuration. **No YAML configuration of the integration itself**
(`config_flow: true`, no `configuration.yaml` schema).

### Initial flow

1. **`user`** — device name.
2. **`hardware`** — branch:
   - *"Generate ESPHome YAML for me"* → wizard steps 3a–3c
   - *"I already have my hardware set up"* → **skip directly to step 4**

   This bypass is mandatory. The wizard must never be a prerequisite for
   binding.
3. **Wizard** (only if chosen):
   - **3a `board`** — pick board profile (see §7). Show available/unsafe pins.
   - **3b `displays_hw`** — number of displays, output GPIO per display.
   - **3c `leds_hw`** — per display: none / addressable / raw RGB.
     - Addressable: shared data pin (multiple displays may share one pin) plus
       LED index on that strip.
     - Raw RGB: three GPIOs.
     - Mixed setups must work, e.g. 3 addressable on one data pin + 1 raw RGB.
   - **3d `buttons_hw`** — button GPIOs (global list).
   - **3e `yaml_result`** — show the generated YAML, offer download, and
     instruct the user to flash via ESPHome CLI or the web installer. The
     integration does **not** compile or flash anything.
4. **`bind_displays`** — for each display: pick its `number` output entity,
   optionally its `light` entity + LED mode.
5. **`presets`** — per display, add 1–8 presets (repeating step with an
   "add another" checkbox). Each preset: label, entity-or-statistic mode,
   source, statistic type + period if applicable, min, max, colour.
6. **`buttons`** — bind button entities to actions.

### Options flow

Everything from steps 4–6 must be fully editable afterwards, plus the ability
to re-run the YAML wizard and re-export. Changing options must reload the
entry cleanly without orphaning entities.

Use entity selectors with domain filters throughout
(`selector.entity({"domain": "number"})` etc.) so the GUI only offers valid
choices. Validate that a chosen `number` entity actually exposes `min`/`max`.

---

## 7. YAML generator (`yaml_gen/`)

Isolated package. Nothing else imports it except the config flow.

### Fragment composition, not templating

Because LED type varies per display and buttons are optional, a flat
substitution template will not work. Compose per-display **fragments** and
assemble:

- `base` — `esphome`, `esp32`, `logger`, `api`, `ota`, `wifi`,
  `captive_portal`
- per display — `ledc` output + `template` number (`min_value: 0`,
  `max_value: 1`, `step: 0.001`, `optimistic: true`)
- addressable LEDs — one `esp32_rmt_led_strip` per shared data pin with
  `num_leds` = total on that pin, then one `light: platform: partition` per
  display selecting its segment. This is the correct ESPHome pattern for
  sharing one strip across logical displays.
- raw RGB — three `ledc` outputs + `light: platform: rgb`
- buttons — `binary_sensor: platform: gpio` (with `on_multi_click` producing
  distinct events where configured)

**Critical:** the generated template number must **not** call `number.set` on
itself inside its own `set_action`. That is infinite recursion and crashes the
ESP32 (this bug was hit during prototyping). With `optimistic: true`, ESPHome
publishes state automatically.

Correct form:

```yaml
number:
  - platform: template
    name: "Display 1"
    id: display_1
    min_value: 0
    max_value: 1
    step: 0.001
    optimistic: true
    set_action:
      - output.set_level:
          id: out_display_1
          level: !lambda return x;
```

Emit YAML with `ruamel.yaml` or careful string assembly — either way, add
**snapshot tests** covering: single display, 4 displays, mixed LED types,
shared addressable pin, buttons present/absent.

### Board profiles

Data-driven (`yaml_gen/boards/*.yaml` or a dict), each defining: variant,
flash size, framework, usable GPIOs, input-only pins, strapping pins, and
flash-reserved pins. Ship `esp32-devkit-v1` first (input-only: 34–39;
strapping: 0, 2, 12, 15; reserved: 6–11). The config flow must reject unsafe
or duplicate pin assignments with clear errors.

---

## 8. Repository layout

```
ha-analog-displays/
├── custom_components/analog_displays/
│   ├── __init__.py
│   ├── manifest.json
│   ├── const.py
│   ├── models.py
│   ├── config_flow.py
│   ├── coordinator.py
│   ├── controller.py          # per-display runtime logic
│   ├── normalization.py
│   ├── statistics.py          # recorder LTS access
│   ├── buttons.py             # button binding + dispatch
│   ├── device_trigger.py
│   ├── diagnostics.py
│   ├── repairs.py
│   ├── services.yaml
│   ├── strings.json
│   ├── translations/
│   │   ├── en.json
│   │   └── nl.json
│   ├── backends/
│   │   ├── __init__.py        # registry + ABC
│   │   └── number_entity.py
│   ├── yaml_gen/
│   │   ├── __init__.py
│   │   ├── boards/
│   │   └── fragments/
│   ├── select.py
│   ├── sensor.py
│   └── binary_sensor.py
├── tests/
├── .github/workflows/
├── hacs.json
├── pyproject.toml
├── .pre-commit-config.yaml
├── README.md
├── LICENSE                    # MIT
└── CHANGELOG.md
```

### `manifest.json` essentials

```json
{
  "domain": "analog_displays",
  "name": "Analog Displays",
  "config_flow": true,
  "documentation": "https://github.com/<user>/ha-analog-displays",
  "issue_tracker": "https://github.com/<user>/ha-analog-displays/issues",
  "iot_class": "local_push",
  "integration_type": "hub",
  "codeowners": ["@<user>"],
  "requirements": [],
  "version": "0.1.0"
}
```

Keep `requirements` empty if at all possible — pure-stdlib plus HA helpers
makes HACS review and CI trivial.

---

## 9. CI/CD and HACS readiness

### Workflows (`.github/workflows/`)

1. **`validate.yml`** — on push/PR/schedule:
   - `home-assistant/actions/hassfest@master`
   - `hacs/action@main` with `category: integration`
2. **`test.yml`** — on push/PR:
   - `pytest` with `pytest-homeassistant-custom-component`
   - coverage reporting, fail under a threshold (start at 80%)
   - matrix across current + previous HA minor
3. **`lint.yml`** — `ruff check`, `ruff format --check`, `mypy`
4. **`release.yml`** — on tag: build the zip of
   `custom_components/analog_displays`, attach to a GitHub release, keep
   `manifest.json` `version` in sync with the tag (fail the build if it
   doesn't match).

Add `.pre-commit-config.yaml` mirroring the lint workflow.

### HACS checklist

- `hacs.json` with `name`, `render_readme: true`,
  `homeassistant` minimum version
- Repository description and topics set
- README covering: what it does, install via HACS, the two setup paths
  (wizard vs. existing hardware), a worked example, and a wiring section
- Semantic versioning, `CHANGELOG.md` maintained
- Issue templates and a brief `CONTRIBUTING.md`

### Testing requirements

- Config flow: happy path, wizard path, **bypass path**, invalid pin, duplicate
  pin, `min == max` rejection, options-flow edits
- Normalization: negative sources, inverted ranges, clamping at both ends,
  target-entity rescaling (`0–1`, `0–100`, `0–255`), step rounding
- Debounce: rapid updates coalesce, latest value wins, preset change bypasses
- Unavailable source: value held, repair issue raised and cleared
- Statistics: mocked recorder, each stat type and period
- Buttons: each of the four actions, cycle wraparound, event filter
- YAML generator: snapshot tests as listed in §7
- Restore: active preset survives a restart

---

## 10. Reference hardware (for README and defaults)

The prototype this was designed against, useful for docs and sane defaults:

- ESP32 DevKit V1, ESP-IDF framework
- 4 × analog moving-coil meters, 10 mA full scale, 27 Ω coil resistance
- Each meter: `GPIO → 330 Ω series resistor → meter (+) → meter (−) → GND`
- With 330 Ω: `3.3 V / (330 + 27) Ω = 9.24 mA` at 100% duty — just under full
  scale, leaving headroom so tolerance drift never pins the needle past its
  stop. Because full duty equals full scale, firmware needs no per-meter
  calibration and can pass `0.0–1.0` straight through.
- The resistor also protects the movement during boot/flash windows before
  ESPHome controls the pin, where an unprotected coil would see
  `3.3 V / 27 Ω = 122 mA`.
- LEDC frequency 1000 Hz; no RC filter needed (the movement's own mechanical
  inertia damps the ripple).

Document the resistor calculation in the README so users can size it for
meters with different full-scale currents and coil resistances:
`Rs = (V_supply / I_fullscale) − R_coil`.

---

## 11. Explicit backlog — build toward, do not build now

Structure the code so these are additive, and record them in the README/issues:

1. **Generic single-binary firmware** — one static image exposing N generic
   channels, removing per-device compilation entirely. The Layer 1/2/3 split
   above already makes this a drop-in alternative to the wizard.
2. **LCD / text display backend** — via the `OutputBackend` abstraction. This
   is why `NormalizedValue` carries raw value and unit, not just a float.
3. Additional board profiles (ESP32-S3, C3, ESP8266).
4. Curve/response shaping per preset (log, sqrt, custom points) for sensors
   with wide dynamic range.
5. Needle "sweep on startup" self-test animation.

### Non-goals

- The integration never compiles or flashes firmware.
- No `configuration.yaml` support for the integration itself.
- No direct hardware/serial/network access to devices.

---

## 12. Build order

1. Repo scaffolding, `manifest.json`, `hacs.json`, CI workflows, pre-commit,
   MIT licence — get green CI on an empty integration first.
2. `models.py`, `normalization.py`, backend ABC + `NumberEntityBackend`, with
   unit tests. No HA integration wiring yet.
3. Minimal config flow: device name → bind one display → one entity preset.
   End-to-end working write. Tests.
4. `controller.py`: debounce, unavailable handling, repairs. Tests.
5. Presets (up to 8) + `select` entity + restore. Tests.
6. Statistics mode + coordinator. Tests.
7. LEDs: preset mode and threshold mode. Tests.
8. Buttons + device triggers + services. Tests.
9. `yaml_gen/` with board profiles, fragment composition, snapshot tests.
10. Wizard config-flow steps, with the bypass path.
11. Diagnostics, translations (en + nl), README, release workflow.

Ask before deviating from the architecture in §1–2. Everything else is open to
your judgement.
