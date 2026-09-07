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

## Commits

Semantic versioning. Add a `CHANGELOG.md` entry under `## [Unreleased]`
describing your change; a release cannot be cut from an empty section.

## Cutting a release

Home Assistant requires custom integrations to declare a `version` in
`manifest.json`, and `release.yml` refuses to publish a release whose tag
disagrees with it. The manifest is the source of truth, so bump it *before*
tagging. One command moves the manifest and the changelog together:

```bash
git checkout -b release-0.2.0
python scripts/bump_version.py 0.2.0
ruff check . && ruff format --check . && mypy && pytest
```

Then open a PR, merge it, and publish a GitHub release **on `main`**:

- **Tag: `0.2.0`, with no prefix.** The tag is created by publishing the
  release. `v0.2.0` and `V0.2.0` are tolerated, but the published tags have no
  prefix and the changelog links assume that.
- The workflow verifies tag against manifest, builds
  `custom_components/analog_displays` into `analog_displays.zip`, and attaches
  it. HACS installs that zip, so it must stay flat with `manifest.json` at its
  root.

`pytest` fails locally if the manifest and changelog versions drift apart, so
you should never reach a failed release run.
