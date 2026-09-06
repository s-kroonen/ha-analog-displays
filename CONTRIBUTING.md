# Contributing

Thanks for helping out.

## Architecture rules

Two rules are not negotiable, because the whole design rests on them:

1. **The integration never talks to hardware.** It reads and writes ordinary
   Home Assistant entities (`number`, `light`, `binary_sensor`, `event`,
   `sensor`). No serial, no network, no device protocols.
2. **Nothing outside `custom_components/analog_displays/yaml_gen/` may import
   an ESPHome concept.** The YAML wizard is a convenience only; it must stay
   fully skippable and must never be on a runtime code path.

Everything else is open to discussion — please open an issue first for
anything larger than a bug fix.

## Development setup

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install
```

Do **not** `pip install homeassistant` directly.
`pytest-homeassistant-custom-component` pins the matching Home Assistant
version; installing it separately breaks the resolver.

## Before you push

```bash
ruff check . && ruff format --check . && mypy && pytest
```

Test coverage must stay at or above 80%; CI enforces it.

## Commits and releases

Semantic versioning. `manifest.json`'s `version` must match the release tag —
the release workflow fails the build if it does not. Add a `CHANGELOG.md`
entry under `## [Unreleased]` with your change.
