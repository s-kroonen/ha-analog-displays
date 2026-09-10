# Analog Displays

[![Validate](https://github.com/s-kroonen/ha-analog-displays/actions/workflows/validate.yml/badge.svg)](https://github.com/s-kroonen/ha-analog-displays/actions/workflows/validate.yml)
[![Test](https://github.com/s-kroonen/ha-analog-displays/actions/workflows/test.yml/badge.svg)](https://github.com/s-kroonen/ha-analog-displays/actions/workflows/test.yml)
[![hacs](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz)

Drive analog displays — moving-coil meters today, other display types later —
from any Home Assistant sensor data.

> **ESPHome is the hardware interface. This integration is the brains.**

The integration never talks to hardware. It reads and writes ordinary Home
Assistant entities, which means any board, firmware or protocol that exposes a
`number` entity works: hand-written ESPHome YAML, a completely different board,
Tasmota, even a Zigbee dimmer. Changing which sensor feeds a meter, how it is
calibrated, what its LED does or what its buttons do never requires
recompiling or reflashing anything.

| Role | Bound to |
|---|---|
| Display output | a `number` entity |
| Indicator LED | a `light` entity |
| Button input | a `binary_sensor` or `event` entity |
| Data source | any `sensor` entity, or recorder statistics |

## What it does

- **Presets are scenes across the whole device.** Four meters, one preset
  called "Power" showing solar, grid, battery and house; another called
  "Climate" showing temperatures. Calibration lives on the preset, which is
  what lets four meters cover far more than four sensors.
- **Normalizes and rescales automatically.** A source is mapped onto 0.0–1.0
  against the preset's range and clamped, then scaled into the target entity's
  *own* range, read live at write time. A 0.0–1.0 ESPHome template number,
  someone else's 0–100, and a 0–255 dimmer all work with no configuration.
- **Rate limits writes.** A power sensor may update every second; hammering a
  mechanical movement is pointless and shortens its life. Rapid updates
  coalesce into one write per interval (5 s by default), always carrying the
  newest value.
- **Holds, never lies.** When a source goes unavailable the needle stays where
  it is rather than snapping to zero, a repair issue names exactly which
  device, display, preset and entity are at fault, and a diagnostic sensor
  marks the display stale. The issue clears itself on recovery.
- **Reads recorder statistics** as well as live entities — mean, min, max, sum,
  state or change over the last hour, today, or the last 24 hours, 7 or 30 days.
- **Colours indicator LEDs** by the active preset, or by value along a
  gradient.
- **Generates ESPHome YAML for you**, if you want it. Entirely optional.

## Installation

### HACS

1. HACS → ⋮ → **Custom repositories** → add
   `https://github.com/s-kroonen/ha-analog-displays` as an **Integration**.
2. Search for **Analog Displays**, install, restart Home Assistant.
3. **Settings → Devices & services → Add integration → Analog Displays**.

### Manual

Copy `custom_components/analog_displays` into your `config/custom_components/`
directory and restart Home Assistant.

## Setting up

Everything is configured in the UI. There is no `configuration.yaml` schema.

After naming your device you get a choice, and **both paths are fully
supported**:

### "I already have my hardware set up"

Skips straight to binding. Pick the `number` entity that moves each display,
optionally a `light` entity for its LED, then define your presets. Use this if
you wrote your own ESPHome YAML, or if your displays are driven by something
that is not ESPHome at all.

### "Generate ESPHome YAML for me"

A wizard asks for your board, the GPIO behind each meter, the LED wiring and
the button pins, and hands you a complete ESPHome configuration to flash
yourself. It only offers pins that are safe on your board — never the flash
pins, never the strapping pins, never an input-only pin for an output.

**The integration never compiles or flashes anything.** Copy the YAML into
ESPHome and flash it with the CLI or the web installer. You will need these in
your ESPHome secrets:

```yaml
analog_displays_api_key: "..."       # esphome wizard generates one
analog_displays_ota_password: "..."
wifi_ssid: "..."
wifi_password: "..."
```

Once flashed, the wizard hands over to the same binding steps as the other
path. The generated YAML can be re-exported later from the options flow or the
`analog_displays.export_yaml` service.

## A worked example

Four meters on one ESP32, two presets.

**Preset "Power"**

| Display | Source | Needle 0 | Full scale |
|---|---|---|---|
| Solar | `sensor.solar_power` | 0 W | 4000 W |
| Grid | `sensor.grid_power` | −3000 W | 3000 W |
| Battery | `sensor.battery_level` | 0 % | 100 % |
| House | `sensor.house_power` | 0 W | 6000 W |

Grid power goes negative when you export. Because normalization clamps to
0.0–1.0, −3000 W parks the needle at zero, 0 W sits it dead centre, and
+3000 W pins it at full scale — no special handling needed.

**Preset "Climate"** reuses the same four meters for indoor temperature,
outdoor temperature, humidity and CO₂, each with its own range. Switch between
them with the `select` entity, a button, or `analog_displays.next_preset`.

### How a value reaches the needle

Two mappings happen on every write, and neither needs configuring beyond the
range you already gave the preset:

1. **Source into the display's unit.** A sensor in watts against a range in kW
   is converted; an incompatible unit holds the needle rather than showing a
   wrong number.
2. **The display's range onto the output's own range.** The preset says what
   the *face* reads — 200 °C to 300 °C, −1 kW to 5 kW, 0 % to 100 % — and the
   output entity advertises what the *signal* is. A 250 °C reading on a
   200-300 face lands as `50` on a 0-100 number, `0.5` on the 0.0-1.0 template
   number the wizard generates, and `128` on a 0-255 dimmer.

The output's range is read live at write time, so re-flashing the board with a
different scale needs no change here. Values outside the configured range are
clamped: a moving-coil needle has hard stops, and driving past them is how they
bend.

**The scale belongs to the preset, not the board.** One meter can be a −1 to
5 kW power gauge under "Power" and a 200-300 °C dial under "Climate"; switching
preset rescales it. The board never learns either range — it receives a
position, and all of this happens in the integration.

**Trim belongs to the meter.** Each display also has a *signal at needle zero*
and *signal at full scale*, defaulting to 0 % and 100 %. Those correct the
movement itself — one that reaches its stop at 92 % of drive, or rests a hair
off zero — and apply under every preset, because the deviation is the
hardware's, not the reading's.

### LED gradients

An LED in gradient mode is coloured by the display's *normalized* value, so a
stop keeps its meaning when a preset switches that meter from watts to degrees.
For a battery gauge with stops at red 20 %, amber 50 % and green 80 %:

- **Blending off** — the LED switches sharply: red until 50 %, amber until
  80 %, green above. Below 20 % it is dark.
- **Blending on** — colours are interpolated between the surrounding stops, so
  45 % reads orange and 70 % reads yellow-green.

Give a stop an explicit end to leave a deliberate dark band before the next one
begins.

## Changing things later

**Configure** on the device opens the same questions again, and every one of
them starts from what is stored rather than from a blank form:

- **Edit a display** — its name, output entity, indicator LED and debounce
  interval. With one display the picker is skipped.
- **Edit a preset** — its name, blink colour, and then, for every display, the
  source, unit, range, LED mode and each LED zone in turn. Change one threshold
  and leave the rest as they are.
- **Add** or **remove** a preset, and change the statistics polling interval.

## Entities and services

Each config entry appears as one device.

| Platform | Per | Purpose |
|---|---|---|
| `select` | device | The active preset. Writable, and restored across restarts. |
| `sensor` | display | The raw source reading, in the source's own unit. |
| `sensor` | display | Needle position, as a percentage. Diagnostic. |
| `binary_sensor` | display | Source stale. Diagnostic. |

Services: `set_preset` (by label or index), `next_preset`, `previous_preset`,
`refresh`, and `export_yaml` (a response service, so it works from Developer
Tools). Buttons also appear as **device triggers**, so you can pick
"Button 1 was pressed" out of the automation UI without knowing any event name.

## Wiring

The prototype this was designed against:

- ESP32 DevKit V1, ESP-IDF framework
- 4 × moving-coil meters, 10 mA full scale, 27 Ω coil resistance
- Per meter: `GPIO → 330 Ω series resistor → meter (+) → meter (−) → GND`
- LEDC PWM at 1000 Hz. No RC filter is needed — the movement's own mechanical
  inertia damps the ripple.

### Sizing the series resistor

```
Rs = (V_supply / I_fullscale) − R_coil
```

For the reference hardware: `3.3 V / 0.010 A − 27 Ω = 303 Ω`, so the nearest
standard value up is **330 Ω**. That gives
`3.3 V / (330 + 27) Ω = 9.24 mA` at 100 % duty — just under full scale, leaving
headroom so tolerance drift never drives the needle past its stop. Because full
duty equals full scale, the firmware needs no per-meter calibration and passes
0.0–1.0 straight through.

**The resistor is not optional.** It also protects the movement during the boot
and flash windows before ESPHome takes control of the pin, where an unprotected
10 mA coil would see `3.3 V / 27 Ω = 122 mA`.

For a different meter, substitute its own full-scale current and coil
resistance. A 1 mA / 100 Ω movement, for instance, wants
`3.3 / 0.001 − 100 = 3200 Ω`, so 3.3 kΩ.

## Planned

Deliberately not built yet, but the architecture is shaped to accept them
without a rewrite:

1. **A generic single-binary firmware** — one static image exposing N generic
   channels, removing per-device compilation entirely. The entity boundary
   already makes this a drop-in alternative to the wizard.
2. **An LCD / text display backend** — this is why values carry the raw reading
   and its unit alongside the normalized float, not just a number.
3. **More board profiles** — ESP32-S3, C3, ESP8266.
4. **Response curves per preset** (log, sqrt, custom points) for sources with a
   wide dynamic range.
5. **A sweep-on-startup self test.**

### Non-goals

- The integration never compiles or flashes firmware.
- No `configuration.yaml` support for the integration itself.
- No direct hardware, serial or network access to devices.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Bug reports and feature requests are
welcome; the two architecture rules in there are not negotiable.

## Licence

MIT — see [`LICENSE`](LICENSE).
