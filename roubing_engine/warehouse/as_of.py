"""Anti-lookahead spine: as_of slicing + post-hoc pollution checks.

Central rule of the whole system: a T-day reasoning may ONLY see facts whose
availability time is <= as_of. This module is the single gate that enforces it,
so walk-forward replay cannot silently leak future data.

Four time fields (plan §6.1):
  event_time   - when the market/announcement/rule actually happened
  available_at - earliest time the system could have known it
  fetched_at   - when we actually pulled it
  as_of        - cutoff the current reasoning is allowed to use

For daily facts, available_at defaults to that trade day's close (15:00 CST):
a T-day close bar is only usable from T close onward, never intraday of T.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from roubing_engine.config import WAREHOUSE

CST = dt.timezone(dt.timedelta(hours=8))
CLOSE_HHMM = (15, 0)


def _yyyymmdd(date_iso: str) -> str:
    return date_iso.replace("-", "")


def daily_available_at(trade_date: str) -> dt.datetime:
    """A daily bar for trade_date becomes available at that day's close."""
    raw = _yyyymmdd(trade_date)
    d = dt.date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    return dt.datetime(d.year, d.month, d.day, CLOSE_HHMM[0], CLOSE_HHMM[1], tzinfo=CST)


def list_partition_dates(dataset: str) -> list[str]:
    base = WAREHOUSE / dataset
    if not base.exists():
        return []
    out = []
    for p in base.glob("date=*"):
        out.append(p.name.split("=", 1)[1])
    return sorted(out)


def usable_dates(dataset: str, as_of_date: str, inclusive: bool = True) -> list[str]:
    """Partition dates whose availability (close) <= as_of close.

    inclusive=True: T-day EOD reasoning may use T's own close bar.
    inclusive=False: strictly before as_of (e.g. pre-open of T+1 must not use T+1).
    """
    cutoff = daily_available_at(as_of_date)
    dates = []
    for d in list_partition_dates(dataset):
        avail = daily_available_at(d)
        if (avail <= cutoff) if inclusive else (avail < cutoff):
            dates.append(d)
    return dates


def read_asof(dataset: str, as_of_date: str, inclusive: bool = True) -> pd.DataFrame:
    """Read a dataset restricted to partitions available at/before as_of."""
    frames = []
    for d in usable_dates(dataset, as_of_date, inclusive=inclusive):
        p = WAREHOUSE / dataset / f"date={d}" / "part.parquet"
        if p.exists():
            frames.append(pd.read_parquet(p))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ---- post-hoc pollution checks (plan §6.4) ----

def check_no_future_partitions(used_dates: list[str], as_of_date: str,
                               inclusive: bool = True) -> list[str]:
    """Return violations: any used date whose availability is after as_of."""
    cutoff = daily_available_at(as_of_date)
    bad = []
    for d in used_dates:
        avail = daily_available_at(d)
        if (avail > cutoff) if inclusive else (avail >= cutoff):
            bad.append(d)
    return [f"future data used: {d} (as_of={as_of_date})" for d in bad]


def audit_reasoning_inputs(input_dates: list[str], as_of_date: str) -> dict:
    """One-call gate for a reasoning run: PASS or INVALID_FOR_BACKTEST."""
    violations = check_no_future_partitions(input_dates, as_of_date)
    return {
        "as_of": as_of_date,
        "status": "PASS" if not violations else "INVALID_FOR_BACKTEST",
        "violations": violations,
    }
