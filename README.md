# Analog Displays

A Home Assistant custom integration that drives analog displays — moving-coil
meters today, other display types later — from any Home Assistant sensor data.

> **ESPHome is the hardware interface. This integration is the brains.**
> It never talks to hardware. It reads and writes ordinary Home Assistant
> entities, so any board or firmware that exposes a `number` entity works.

Full documentation lands with the 0.1.0 release. See [`spec.md`](spec.md) for
the design this is being built against.

## Status

Under active development. See [`CHANGELOG.md`](CHANGELOG.md).

## Licence

MIT — see [`LICENSE`](LICENSE).
