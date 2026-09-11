"""Derive the 2026 trading-day calendar from a liquid reference stock."""
from __future__ import annotations

from roubing_engine.config import CALENDAR_REF_CODE


def trading_days(client, year: int = 2026, ref_code: str = CALENDAR_REF_CODE) -> list[str]:
    """Return sorted 'YYYY-MM-DD' trading days for the given year.

    Uses the reference stock's daily bars (their timestamps are actual trading
    days). count is generous to cover multiple years.
    """
    # eltdx caps page size at 800; 800 daily bars (~3.2y) covers 2026 fully.
    series = client.bars.get(ref_code, period="day", count=800)
    days = set()
    for bar in getattr(series, "bars", []) or []:
        t = getattr(bar, "time", None)
        if t is not None and getattr(t, "year", None) == year:
            days.add(t.strftime("%Y-%m-%d"))
    return sorted(days)
