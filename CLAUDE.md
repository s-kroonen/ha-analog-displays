Read the spec.md for the project that needs to be built
## Environment
- Python 3.13 venv at `~/.venvs/ha` (system python3 is too old for HA).
- `pytest`, `ruff`, `mypy`, `pre-commit`, and `python` on PATH point at that venv.
- Never `pip install homeassistant` directly — `pytest-homeassistant-custom-component`
  pins the matching version. Adding HA separately breaks the resolver.
- Before pushing: `ruff check . && ruff format --check . && pytest`
