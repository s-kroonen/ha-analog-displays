"""Reading long-term statistics out of the recorder.

Statistics do not push, so this is the one polled source mode. Everything the
rest of the integration needs sits behind :func:`async_fetch_statistic`, which
is also the seam the tests mock.

The recorder splits the job across two functions, and so does this module:
``statistic_during_period`` aggregates a whole window but only supports
mean/min/max/change, while state and sum have to come from the last row of
``statistics_during_period``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any, cast

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

RECORDER_DOMAIN = "recorder"

#: The windows a preset may ask for.
PERIODS = ("hour", "today", "24h", "7d", "30d")

#: Types the recorder can aggregate across a whole window in one call.
AGGREGATE_TYPES = frozenset({"mean", "min", "max", "change"})
#: Types that only exist per bucket, so the newest bucket is taken.
LAST_ROW_TYPES = frozenset({"state", "sum"})


def period_bounds(
    period: str, now: datetime | None = None
) -> tuple[datetime, datetime]:
    """Return the UTC window a statistic period covers.

    Everything is a rolling window except ``today``, which is anchored to local
    midnight — that is what a user means by "today" on a dashboard.
    """
    end = now or dt_util.utcnow()

    if period == "today":
        start = dt_util.start_of_local_day().astimezone(dt_util.UTC)
    elif period == "hour":
        start = end - timedelta(hours=1)
    elif period == "24h":
        start = end - timedelta(hours=24)
    elif period == "7d":
        start = end - timedelta(days=7)
    elif period == "30d":
        start = end - timedelta(days=30)
    else:
        raise ValueError(f"unknown statistic period {period!r}")

    return start, end


def recorder_available(hass: HomeAssistant) -> bool:
    """Whether the recorder is loaded and can be queried."""
    return RECORDER_DOMAIN in hass.config.components


async def async_fetch_statistic(
    hass: HomeAssistant,
    statistic_id: str,
    statistic_type: str,
    period: str,
) -> float | None:
    """Read one statistic, or ``None`` if it cannot be produced.

    Returning ``None`` rather than raising is deliberate: a missing statistic
    is handled exactly like a dead entity source — the display holds its last
    value and a repair issue explains why.
    """
    if not recorder_available(hass):
        _LOGGER.debug("Recorder is not loaded; cannot read %s", statistic_id)
        return None

    from homeassistant.components.recorder.statistics import (  # noqa: PLC0415
        statistic_during_period,
        statistics_during_period,
    )
    from homeassistant.helpers.recorder import get_instance  # noqa: PLC0415

    if period not in PERIODS:
        _LOGGER.error("Unknown statistic period %r for %s", period, statistic_id)
        return None

    start, end = period_bounds(period)

    if statistic_type in AGGREGATE_TYPES:

        def _query() -> float | None:
            result = statistic_during_period(
                hass,
                start,
                end,
                statistic_id,
                {cast(Any, statistic_type)},
                None,
            )
            return _as_float(result.get(statistic_type))

    elif statistic_type in LAST_ROW_TYPES:

        def _query() -> float | None:
            rows = statistics_during_period(
                hass,
                start,
                end,
                {statistic_id},
                "hour",
                None,
                {cast(Any, statistic_type)},
            ).get(statistic_id)
            if not rows:
                return None
            return _as_float(rows[-1].get(statistic_type))

    else:
        _LOGGER.error("Unknown statistic type %r for %s", statistic_type, statistic_id)
        return None

    return await get_instance(hass).async_add_executor_job(_query)


def _as_float(value: object) -> float | None:
    """Coerce a recorder value to a float, or ``None`` if it has none."""
    if value is None:
        return None
    try:
        return float(cast("float", value))
    except (TypeError, ValueError):
        return None
