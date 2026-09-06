"""Output backend abstraction.

Every write to a physical display goes through an :class:`OutputBackend`.
This is required from day one, not scaffolding: an LCD/text backend is a
planned feature, and adding one must mean writing a single class and
registering it — no changes to preset, normalization or config-flow logic.

That is also why :class:`NormalizedValue` carries the raw value and its unit
alongside the normalized float: an analog backend renders ``0.42`` while a
future text backend renders ``"1234 W"`` from the very same value.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

__all__ = [
    "BACKENDS",
    "BackendCapabilities",
    "NormalizedValue",
    "OutputBackend",
    "get_backend",
    "register_backend",
]


@dataclass(frozen=True, slots=True)
class NormalizedValue:
    """A value ready to render, in every form a backend might need."""

    normalized: float
    """Position on the display's scale, 0.0-1.0, already clamped."""

    raw: float | None = None
    """The source reading before normalization, for text-capable backends."""

    unit: str | None = None
    """The source's unit of measurement, if it had one."""

    def formatted(self) -> str:
        """Render the raw value and unit as a human-readable string."""
        if self.raw is None:
            return ""
        number = f"{self.raw:g}"
        return f"{number} {self.unit}" if self.unit else number


@dataclass(frozen=True, slots=True)
class BackendCapabilities:
    """What a backend can render, so callers need not special-case types."""

    analog: bool = False
    """Renders a continuous position, e.g. a needle or a bar."""

    text: bool = False
    """Renders the raw value and unit as characters."""


class OutputBackend(ABC):
    """Renders a normalized value onto some physical output."""

    @abstractmethod
    async def write(self, value: NormalizedValue) -> None:
        """Render ``value`` on the output."""

    @abstractmethod
    async def clear(self) -> None:
        """Return the output to its resting state."""

    @property
    @abstractmethod
    def capabilities(self) -> BackendCapabilities:
        """What this backend is able to render."""


BACKENDS: dict[str, type[OutputBackend]] = {}


def register_backend(
    key: str,
) -> Callable[[type[OutputBackend]], type[OutputBackend]]:
    """Register a backend implementation under ``key``.

    Adding a backend is exactly this decorator plus the class itself.
    """

    def decorator(backend: type[OutputBackend]) -> type[OutputBackend]:
        if key in BACKENDS:
            raise ValueError(f"backend {key!r} is already registered")
        BACKENDS[key] = backend
        return backend

    return decorator


def get_backend(key: str) -> type[OutputBackend]:
    """Look up a registered backend by key."""
    try:
        return BACKENDS[key]
    except KeyError:
        raise ValueError(f"unknown output backend {key!r}") from None
