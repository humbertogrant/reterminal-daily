from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as calendars

LOCAL_TZ = ZoneInfo("America/Costa_Rica")
CLOSE_DATE_POLICY = "previous_us_session"


def edition_date(retrieved_at: str) -> str:
    """Freeze the daily edition at retrieval start, including delayed reruns."""
    timestamp = datetime.fromisoformat(retrieved_at)
    if timestamp.utcoffset() is None:
        raise ValueError("retrieved_at must include a timezone")
    return timestamp.astimezone(LOCAL_TZ).date().isoformat()


@lru_cache(maxsize=32)
def expected_close_date(edition: str) -> str:
    """Use the last US equity session strictly before the local edition day.

    Never promote same-day quotes, even if a manual run occurs after the close.
    The calendar, not a source's newest row, determines freshness. Treasury and
    Costa Rica holidays can differ; preserve and label older observations then.

    The calendar window deliberately extends beyond the requested date. On a
    weekend or holiday, exchange_calendars otherwise bounds the calendar at the
    last actual session and date_to_session() can reject the intervening
    non-session date as out of range.
    """
    day = date.fromisoformat(edition)
    previous_day = day - timedelta(days=1)
    calendar = calendars.get_calendar(
        "XNYS",
        start=previous_day - timedelta(days=370),
        end=previous_day + timedelta(days=14),
    )
    return calendar.date_to_session(
        previous_day.isoformat(), direction="previous"
    ).date().isoformat()
