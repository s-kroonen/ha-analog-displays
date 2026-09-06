"""Tests for the output backend abstraction and the number-entity backend."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.analog_displays.backends import (
    BACKENDS,
    BackendCapabilities,
    NormalizedValue,
    OutputBackend,
    get_backend,
    register_backend,
)
from custom_components.analog_displays.backends.number_entity import (
    BACKEND_NUMBER_ENTITY,
    NumberEntityBackend,
    UnknownOutputRangeError,
)


def _set_output(
    hass: HomeAssistant,
    entity_id: str = "number.meter",
    *,
    minimum: float | None = 0.0,
    maximum: float | None = 1.0,
    step: float | None = None,
    state: str = "0",
) -> None:
    """Publish a number entity state with the given range attributes."""
    attributes: dict[str, object] = {}
    if minimum is not None:
        attributes["min"] = minimum
    if maximum is not None:
        attributes["max"] = maximum
    if step is not None:
        attributes["step"] = step
    hass.states.async_set(entity_id, state, attributes)


# --- registry ---------------------------------------------------------------


def test_number_backend_is_registered() -> None:
    assert get_backend(BACKEND_NUMBER_ENTITY) is NumberEntityBackend


def test_get_backend_rejects_unknown_key() -> None:
    with pytest.raises(ValueError, match="unknown output backend"):
        get_backend("holographic")


def test_register_backend_rejects_duplicates() -> None:
    """Adding a future backend is one class plus one decorator."""

    class _Fake(OutputBackend):
        async def write(self, value: NormalizedValue) -> None: ...
        async def clear(self) -> None: ...

        @property
        def capabilities(self) -> BackendCapabilities:
            return BackendCapabilities(text=True)

    try:
        register_backend("fake_text")(_Fake)
        assert get_backend("fake_text") is _Fake
        assert get_backend("fake_text")().capabilities.text is True

        with pytest.raises(ValueError, match="already registered"):
            register_backend("fake_text")(_Fake)
    finally:
        BACKENDS.pop("fake_text", None)


# --- NormalizedValue --------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (NormalizedValue(0.5, raw=1234.0, unit="W"), "1234 W"),
        (NormalizedValue(0.5, raw=21.5, unit="°C"), "21.5 °C"),
        (NormalizedValue(0.5, raw=7.0), "7"),
        (NormalizedValue(0.5), ""),
    ],
)
def test_normalized_value_carries_text_for_future_backends(
    value: NormalizedValue, expected: str
) -> None:
    """The raw value and unit exist so an LCD backend needs no refactor."""
    assert value.formatted() == expected


# --- NumberEntityBackend ----------------------------------------------------


@pytest.mark.parametrize(
    ("minimum", "maximum", "step", "normalized", "expected"),
    [
        # An ESPHome template number: 0.0-1.0 straight through.
        (0.0, 1.0, 0.001, 0.42, 0.42),
        # Someone else's 0-100.
        (0.0, 100.0, 1.0, 0.42, 42.0),
        # A 0-255 dimmer.
        (0.0, 255.0, 1.0, 0.42, 107.0),
        # No step attribute at all.
        (0.0, 255.0, None, 0.42, 107.1),
    ],
)
async def test_write_rescales_into_the_targets_own_range(
    hass: HomeAssistant,
    minimum: float,
    maximum: float,
    step: float | None,
    normalized: float,
    expected: float,
) -> None:
    _set_output(hass, minimum=minimum, maximum=maximum, step=step)
    calls = async_mock_service(hass, "number", "set_value")

    await NumberEntityBackend(hass, "number.meter").write(
        NormalizedValue(normalized=normalized)
    )

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == "number.meter"
    assert calls[0].data["value"] == pytest.approx(expected)


async def test_write_reads_the_range_at_write_time(hass: HomeAssistant) -> None:
    """A reflash that changes the target's range must be picked up live."""
    backend = NumberEntityBackend(hass, "number.meter")
    calls = async_mock_service(hass, "number", "set_value")

    _set_output(hass, minimum=0.0, maximum=100.0, step=1.0)
    await backend.write(NormalizedValue(normalized=0.5))

    _set_output(hass, minimum=0.0, maximum=255.0, step=1.0)
    await backend.write(NormalizedValue(normalized=0.5))

    assert [call.data["value"] for call in calls] == [50.0, 128.0]


async def test_clear_drives_to_the_bottom_of_the_range(hass: HomeAssistant) -> None:
    _set_output(hass, minimum=10.0, maximum=20.0)
    calls = async_mock_service(hass, "number", "set_value")

    await NumberEntityBackend(hass, "number.meter").clear()

    assert calls[0].data["value"] == 10.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"minimum": None},
        {"maximum": None},
        {"minimum": 5.0, "maximum": 5.0},
    ],
)
async def test_write_rejects_an_unusable_target_range(
    hass: HomeAssistant, kwargs: dict[str, float | None]
) -> None:
    _set_output(hass, **kwargs)  # type: ignore[arg-type]

    with pytest.raises(UnknownOutputRangeError):
        await NumberEntityBackend(hass, "number.meter").write(NormalizedValue(0.5))


async def test_write_rejects_a_missing_target(hass: HomeAssistant) -> None:
    with pytest.raises(UnknownOutputRangeError, match="has no state"):
        await NumberEntityBackend(hass, "number.gone").write(NormalizedValue(0.5))


async def test_write_ignores_a_nonsense_step(hass: HomeAssistant) -> None:
    """A malformed step must not stop the write; it just skips rounding."""
    _set_output(hass, minimum=0.0, maximum=100.0)
    hass.states.async_set(
        "number.meter", "0", {"min": 0.0, "max": 100.0, "step": "chunky"}
    )
    calls = async_mock_service(hass, "number", "set_value")

    await NumberEntityBackend(hass, "number.meter").write(NormalizedValue(0.425))

    assert calls[0].data["value"] == pytest.approx(42.5)


async def test_capabilities_are_analog_not_text(hass: HomeAssistant) -> None:
    capabilities = NumberEntityBackend(hass, "number.meter").capabilities
    assert capabilities.analog is True
    assert capabilities.text is False
