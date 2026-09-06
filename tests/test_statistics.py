"""Reading long-term statistics, and the coordinator that polls them."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.analog_displays.const import DOMAIN
from custom_components.analog_displays.statistics import (
    async_fetch_statistic,
    period_bounds,
    recorder_available,
)
from tests.test_init import device_options

STATISTICS_PATH = "custom_components.analog_displays.coordinator.async_fetch_statistic"


@pytest.fixture(autouse=True)
def _services(hass: HomeAssistant) -> None:
    async_mock_service(hass, "number", "set_value")


@pytest.fixture(autouse=True)
def _output(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "number.meter_left", "0", {"min": 0.0, "max": 1.0, "step": 0.001}
    )


@pytest.fixture
def set_value_calls(hass: HomeAssistant) -> list[ServiceCall]:
    return async_mock_service(hass, "number", "set_value")


# --- period windows ---------------------------------------------------------


@pytest.mark.parametrize(
    ("period", "expected_span"),
    [
        ("hour", timedelta(hours=1)),
        ("24h", timedelta(hours=24)),
        ("7d", timedelta(days=7)),
        ("30d", timedelta(days=30)),
    ],
)
def test_rolling_periods(period: str, expected_span: timedelta) -> None:
    now = dt_util.utcnow()
    start, end = period_bounds(period, now)

    assert end == now
    assert end - start == expected_span


def test_today_is_anchored_to_local_midnight() -> None:
    """Today on a dashboard means the calendar day, not the last 24 hours."""
    now = dt_util.utcnow()
    start, end = period_bounds("today", now)

    assert end == now
    assert start == dt_util.start_of_local_day().astimezone(dt_util.UTC)
    assert start <= now


def test_an_unknown_period_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown statistic period"):
        period_bounds("fortnight")


# --- fetching ---------------------------------------------------------------


async def test_no_recorder_means_no_value(hass: HomeAssistant) -> None:
    """Without the recorder a statistic reads like a dead source, not a crash."""
    assert recorder_available(hass) is False
    assert await async_fetch_statistic(hass, "sensor.x", "mean", "24h") is None


@pytest.mark.parametrize("statistic_type", ["mean", "min", "max", "change"])
async def test_aggregate_types_use_statistic_during_period(
    hass: HomeAssistant, statistic_type: str
) -> None:
    """mean/min/max/change are aggregated across the window in one call."""
    hass.config.components.add("recorder")
    aggregate = MagicMock(return_value={statistic_type: 42.5})

    with (
        patch(
            "homeassistant.components.recorder.statistics.statistic_during_period",
            aggregate,
        ),
        patch(
            "homeassistant.helpers.recorder.get_instance",
            return_value=_immediate_executor(),
        ),
    ):
        value = await async_fetch_statistic(hass, "sensor.power", statistic_type, "7d")

    assert value == 42.5
    args = aggregate.call_args.args
    assert args[3] == "sensor.power"
    assert args[4] == {statistic_type}
    assert isinstance(args[1], datetime)


@pytest.mark.parametrize("statistic_type", ["state", "sum"])
async def test_row_types_take_the_newest_bucket(
    hass: HomeAssistant, statistic_type: str
) -> None:
    """State and sum only exist per bucket, so the last one wins."""
    hass.config.components.add("recorder")
    rows = MagicMock(
        return_value={
            "sensor.energy": [
                {statistic_type: 10.0},
                {statistic_type: 20.0},
                {statistic_type: 30.0},
            ]
        }
    )

    with (
        patch(
            "homeassistant.components.recorder.statistics.statistics_during_period",
            rows,
        ),
        patch(
            "homeassistant.helpers.recorder.get_instance",
            return_value=_immediate_executor(),
        ),
    ):
        value = await async_fetch_statistic(
            hass, "sensor.energy", statistic_type, "today"
        )

    assert value == 30.0
    assert rows.call_args.args[4] == "hour"


async def test_an_empty_result_reads_as_no_value(hass: HomeAssistant) -> None:
    hass.config.components.add("recorder")

    with (
        patch(
            "homeassistant.components.recorder.statistics.statistics_during_period",
            MagicMock(return_value={}),
        ),
        patch(
            "homeassistant.helpers.recorder.get_instance",
            return_value=_immediate_executor(),
        ),
    ):
        assert await async_fetch_statistic(hass, "sensor.x", "sum", "24h") is None


async def test_unknown_type_and_period_are_rejected(hass: HomeAssistant) -> None:
    hass.config.components.add("recorder")

    assert await async_fetch_statistic(hass, "sensor.x", "median", "24h") is None
    assert await async_fetch_statistic(hass, "sensor.x", "mean", "fortnight") is None


def _immediate_executor() -> MagicMock:
    """Build a recorder stand-in that runs the query inline."""
    instance = MagicMock()

    async def run(func: Any, *args: Any) -> Any:
        return func(*args)

    instance.async_add_executor_job = run
    return instance


# --- the coordinator --------------------------------------------------------


def _statistic_preset(
    statistic_type: str = "mean", period: str = "24h"
) -> list[dict[str, Any]]:
    return [
        {
            "label": "Yesterday",
            "assignments": {
                "0": {
                    "source_mode": "statistic",
                    "statistic_entity_id": "sensor.outside_temp",
                    "statistic_type": statistic_type,
                    "statistic_period": period,
                    "min_value": -10.0,
                    "max_value": 40.0,
                    "colour": None,
                }
            },
        }
    ]


async def _setup(hass: HomeAssistant, **overrides: Any) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Meter Panel", data={}, options=device_options(**overrides)
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_a_statistic_preset_drives_the_display(
    hass: HomeAssistant, set_value_calls: list[ServiceCall]
) -> None:
    with patch(STATISTICS_PATH, return_value=15.0):
        await _setup(hass, presets=_statistic_preset())

    # 15 on a -10..40 scale is halfway.
    assert set_value_calls[-1].data["value"] == pytest.approx(0.5)


async def test_the_coordinator_polls_on_its_interval(
    hass: HomeAssistant,
    set_value_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Statistics do not push, so they are polled."""
    with patch(STATISTICS_PATH, return_value=15.0) as fetch:
        await _setup(hass, presets=_statistic_preset(), statistics_interval=300.0)
        assert fetch.call_count == 1

        freezer.tick(timedelta(seconds=301))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        assert fetch.call_count == 2


async def test_a_custom_polling_interval_is_honoured(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    with patch(STATISTICS_PATH, return_value=15.0) as fetch:
        await _setup(hass, presets=_statistic_preset(), statistics_interval=60.0)
        assert fetch.call_count == 1

        freezer.tick(timedelta(seconds=61))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        assert fetch.call_count == 2


async def test_no_coordinator_when_nothing_reads_statistics(
    hass: HomeAssistant,
) -> None:
    """A preset that reads no statistics must cost no polling."""
    hass.states.async_set("sensor.solar", "1500")
    entry = await _setup(hass)

    assert entry.runtime_data.coordinator is None


async def test_a_missing_statistic_holds_the_last_value(
    hass: HomeAssistant,
    set_value_calls: list[ServiceCall],
    freezer: FrozenDateTimeFactory,
) -> None:
    """A statistic that stops resolving behaves like a dead entity source."""
    with patch(STATISTICS_PATH, return_value=15.0):
        entry = await _setup(hass, presets=_statistic_preset())
    set_value_calls.clear()

    with patch(STATISTICS_PATH, return_value=None):
        await entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()

    assert set_value_calls == []
    assert entry.runtime_data.controllers[0].stale is True
    assert entry.runtime_data.controllers[0].last_value.normalized == pytest.approx(0.5)


async def test_the_statistic_borrows_its_source_unit(hass: HomeAssistant) -> None:
    """A future text backend needs the unit, so it is carried through."""
    hass.states.async_set("sensor.outside_temp", "12", {"unit_of_measurement": "°C"})
    with patch(STATISTICS_PATH, return_value=15.0):
        entry = await _setup(hass, presets=_statistic_preset())

    value = entry.runtime_data.controllers[0].last_value
    assert value is not None
    assert value.raw == 15.0
    assert value.unit == "°C"
    assert value.formatted() == "15 °C"
