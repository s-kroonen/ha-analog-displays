#!/usr/bin/env python3
"""Prepare a release: bump the manifest version and close the changelog.

Home Assistant requires custom integrations to carry a version in
``manifest.json``, and ``release.yml`` refuses to publish a release whose tag
disagrees with it. Keeping those two in step by hand is exactly the sort of
thing that gets forgotten, so this does both in one command:

    python scripts/bump_version.py 0.2.0

Standard library only, so it runs without installing anything.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "custom_components" / "analog_displays" / "manifest.json"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
REPO_URL = "https://github.com/s-kroonen/ha-analog-displays"

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
UNRELEASED_HEADING = "## [Unreleased]"


class BumpError(RuntimeError):
    """Raised when the release cannot be prepared."""


def parse_version(value: str) -> tuple[int, int, int]:
    """Parse ``MAJOR.MINOR.PATCH``, rejecting anything else."""
    match = VERSION_RE.match(value)
    if match is None:
        raise BumpError(f"{value!r} is not a MAJOR.MINOR.PATCH version")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def read_manifest_version() -> str:
    """Return the version currently declared in the manifest."""
    return str(json.loads(MANIFEST.read_text())["version"])


def render_manifest(new_version: str) -> str:
    """Return the manifest text with ``version`` replaced, key order intact."""
    data = json.loads(MANIFEST.read_text())
    data["version"] = new_version
    return json.dumps(data, indent=2) + "\n"


def _unreleased_body(text: str) -> str:
    """Return the changelog entries sitting under ``## [Unreleased]``."""
    start = text.index(UNRELEASED_HEADING) + len(UNRELEASED_HEADING)
    rest = text[start:]
    next_heading = rest.find("\n## ")
    return rest if next_heading == -1 else rest[:next_heading]


def render_changelog(new_version: str, previous_version: str) -> str:
    """Return the changelog with ``## [Unreleased]`` closed as ``## [X.Y.Z]``."""
    text = CHANGELOG.read_text()

    if UNRELEASED_HEADING not in text:
        raise BumpError(f"CHANGELOG.md has no {UNRELEASED_HEADING!r} section")

    if not _unreleased_body(text).strip():
        raise BumpError(
            f"{UNRELEASED_HEADING} is empty — describe the release before cutting it"
        )

    text = text.replace(
        UNRELEASED_HEADING,
        f"{UNRELEASED_HEADING}\n\n## [{new_version}]",
        1,
    )

    # Tags are published without a prefix, so the links must match.
    text = re.sub(
        r"^\[Unreleased\]: .*$",
        f"[Unreleased]: {REPO_URL}/compare/{new_version}...HEAD",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    new_link = f"[{new_version}]: {REPO_URL}/releases/tag/{new_version}"
    return text.replace(
        f"[{previous_version}]: ",
        f"{new_link}\n[{previous_version}]: ",
        1,
    )


def _check_is_newer(new_version: str, current_version: str) -> None:
    """Raise unless ``new_version`` is a later release than the current one."""
    if parse_version(new_version) <= parse_version(current_version):
        raise BumpError(
            f"{new_version} is not newer than the current {current_version}"
        )


def main(argv: list[str] | None = None) -> int:
    """Bump the manifest and changelog to ``new_version``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="the new version, e.g. 0.2.0")
    args = parser.parse_args(argv)

    new_version = args.version
    try:
        current_version = read_manifest_version()
        _check_is_newer(new_version, current_version)
        # Render both files before writing either, so a rejected release never
        # leaves the manifest bumped and the changelog untouched.
        manifest_text = render_manifest(new_version)
        changelog_text = render_changelog(new_version, current_version)
    except BumpError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    MANIFEST.write_text(manifest_text)
    CHANGELOG.write_text(changelog_text)

    print(f"Bumped {current_version} -> {new_version}")
    print()
    print("Next:")
    print("  1. ruff check . && ruff format --check . && pytest")
    print("  2. commit on a branch, open a PR, merge to main")
    print(f"  3. publish a GitHub release on main tagged '{new_version}' (no prefix)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
