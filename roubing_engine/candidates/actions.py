"""Deterministic action-candidate detection (plan §19) from T+1 intraday.

Turns an observation candidate into a 低吸/半路/回封/尾盘 action candidate only
when observable conditions are met. Facts + booleans; the agent/human still
decides. Reads minute_bar (and open) for the code+date from the warehouse.
"""
from __future__ import annotations

import pandas as pd

from roubing_engine.config import WAREHOUSE
from roubing_engine.warehouse.timebox import SNAPSHOT_CUTOFFS, row_seconds


def _minutes(date: str, thscode: str) -> pd.DataFrame:
    p = WAREHOUSE / "minute_bar" / f"date={date.replace('-', '')}" / "part.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    return df[df["thscode"] == thscode].sort_values("time_label")


def detect(thscode: str, date: str, open_price: float | None,
           platform_high: float | None = None, prev_low: float | None = None,
           snapshot: str = "OPEN_0935") -> dict:
    m = _minutes(date, thscode)
    if snapshot not in SNAPSHOT_CUTOFFS:
        raise ValueError(f"unknown snapshot: {snapshot}")
    if not m.empty:
        m = m[m.apply(lambda row: (
            row_seconds(row) is not None
            and row_seconds(row) <= SNAPSHOT_CUTOFFS[snapshot]
        ), axis=1)]
    if m.empty or not open_price:
        return {"available": False, "snapshot": snapshot}
    prices = [float(x) for x in m["price"].tolist()]
    hi, lo, last = max(prices), min(prices), prices[-1]
    intraday_min_pct = round((lo / open_price - 1) * 100, 2)

    # low-point-rising: last third min above first third min
    third = max(1, len(prices) // 3)
    early_low = min(prices[:third])
    late_low = min(prices[-third:])

    return {
        "available": True,
        "banluon_breakout": bool(platform_high and hi >= platform_high),   # 半路：越平台
        "dixi_hold": bool(prev_low and lo >= prev_low),                    # 低吸：不破前低
        "low_point_rising": bool(late_low > early_low),                    # 低点抬高
        "recovered_from_red": bool(intraday_min_pct < 0 <= round((last/open_price-1)*100, 2)),
        "snapshot_last_above_open": bool(last >= open_price),
        "intraday_min_pct_from_open": intraday_min_pct,
        "last_pct_from_open": round((last / open_price - 1) * 100, 2),
        "snapshot": snapshot,
        "last_observed_time": str(m.iloc[-1].get("time_label")),
        "note": "截至快照的事实，不是尾盘或收盘结论；需结合角色/板块与盘前预案确认",
    }
