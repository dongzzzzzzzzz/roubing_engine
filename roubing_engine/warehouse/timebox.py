"""Trading-session time helpers and Stage-D snapshot boundaries.

All cut-offs use Asia/Shanghai wall-clock time.  This module deliberately
contains no market inference: it only decides whether a fact was observable at
a requested snapshot.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any
from zoneinfo import ZoneInfo

from roubing_engine.config import TZ

SHANGHAI = ZoneInfo(TZ)

SNAPSHOT_CUTOFFS = {
    "AUCTION_0925": 9 * 3600 + 25 * 60 + 59,
    "OPEN_0935": 9 * 3600 + 35 * 60 + 59,
}

OPENING_AUCTION_START = 9 * 3600 + 15 * 60
OPENING_AUCTION_END = SNAPSHOT_CUTOFFS["AUCTION_0925"]
CLOSING_AUCTION_START = 14 * 3600 + 57 * 60
CLOSING_AUCTION_END = 15 * 3600 + 59
OPEN_START = 9 * 3600 + 30 * 60
OPEN_5M_END = SNAPSHOT_CUTOFFS["OPEN_0935"]

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?")


def seconds_from_label(value: Any) -> int | None:
    """Return seconds from midnight for HH:MM[:SS] strings."""
    if value is None:
        return None
    match = _TIME_RE.match(str(value).strip())
    if not match:
        return None
    hour, minute, second = (int(x or 0) for x in match.groups())
    if hour > 23 or minute > 59 or second > 59:
        return None
    return hour * 3600 + minute * 60 + second


def row_seconds(row: Any) -> int | None:
    """Resolve an event's time without trusting a single vendor field."""
    getter = row.get if hasattr(row, "get") else lambda key: getattr(row, key, None)
    label_seconds = seconds_from_label(getter("time_label"))
    if label_seconds is not None:
        return label_seconds
    raw = getter("time_seconds")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if 0 <= value < 24 * 3600 else None


def session_type(seconds: int | None) -> str:
    if seconds is None:
        return "UNKNOWN"
    if OPENING_AUCTION_START <= seconds <= OPENING_AUCTION_END:
        return "OPENING_AUCTION"
    if CLOSING_AUCTION_START <= seconds <= CLOSING_AUCTION_END:
        return "CLOSING_AUCTION"
    return "OTHER"


def iso_at(trade_date: str, seconds: int) -> str:
    raw = trade_date.replace("-", "")
    day = dt.date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    moment = dt.datetime.combine(day, dt.time(), ZoneInfo(TZ)) + dt.timedelta(seconds=seconds)
    return moment.isoformat()


def snapshot_as_of(trade_date: str, snapshot: str) -> str:
    if snapshot not in SNAPSHOT_CUTOFFS:
        raise ValueError(f"unknown snapshot: {snapshot}")
    return iso_at(trade_date, SNAPSHOT_CUTOFFS[snapshot])


def in_snapshot(row: Any, snapshot: str) -> bool:
    """Whether a market event is observable by the named snapshot."""
    seconds = row_seconds(row)
    return seconds is not None and seconds <= SNAPSHOT_CUTOFFS[snapshot]
