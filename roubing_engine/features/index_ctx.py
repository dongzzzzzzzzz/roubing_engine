"""Deterministic index context up to as_of (facts only, no 主升/退潮 wording).

Fills the gap Stage B kept flagging: index trend / position vs MA / recent
return for 上证/深证/创业板. Uses only bars on/before as_of.
"""
from __future__ import annotations

from roubing_engine.collectors.financial_api import index_daily
from roubing_engine.config import WAREHOUSE
from roubing_engine.warehouse.timebox import SNAPSHOT_CUTOFFS, row_seconds, snapshot_as_of

INDICES = {
    "000001.SH": "上证指数",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
}


def _snapshot_rows(dataset: str, yyyymmdd: str, cutoff: int):
    """Read an optional intraday market dataset without manufacturing data."""
    path = WAREHOUSE / dataset / f"date={yyyymmdd}" / "part.parquet"
    if not path.exists():
        return None
    import pandas as pd
    frame = pd.read_parquet(path)
    if frame.empty:
        return frame
    if "time_seconds" in frame.columns:
        seconds = pd.to_numeric(frame["time_seconds"], errors="coerce")
    elif "time_label" in frame.columns:
        seconds = frame.apply(row_seconds, axis=1)
    else:
        return pd.DataFrame()
    frame = frame.loc[seconds.notna() & (seconds <= cutoff)].copy()
    frame["_event_seconds"] = seconds.loc[frame.index]
    return frame.sort_values("_event_seconds")


def intraday_market_context(tplus1: str, snapshot: str,
                            theme_names: list[str] | None = None) -> dict:
    """Return index/theme observations available no later than a snapshot.

    The warehouse datasets are optional because the current capture pipeline
    does not yet persist index/theme minute bars.  Missing partitions are
    represented explicitly as BLOCKED_DATA; daily close data is never used as
    a substitute for an intraday snapshot.
    """
    if snapshot not in SNAPSHOT_CUTOFFS:
        raise ValueError(f"unknown snapshot {snapshot}")
    raw = tplus1.replace("-", "")
    cutoff = SNAPSHOT_CUTOFFS[snapshot]
    as_of = snapshot_as_of(tplus1, snapshot)
    datasets = {"index_intraday": "index_minute_bar", "theme_intraday": "theme_minute_bar"}
    observed = {}
    statuses = {}
    for label, dataset in datasets.items():
        frame = _snapshot_rows(dataset, raw, cutoff)
        if frame is None:
            statuses[label] = "MISSING"
            continue
        if frame.empty:
            statuses[label] = "EMPTY"
            continue
        statuses[label] = "AVAILABLE"
        # Keep the raw rows bounded to the declared snapshot.  No inferred
        # market direction is added here; Stage D/AI may only interpret facts.
        observed[label] = frame.drop(columns=["_event_seconds"], errors="ignore").to_dict("records")
    missing = [name for name, status in statuses.items() if status != "AVAILABLE"]
    return {
        "available": not missing,
        "status": "READY" if not missing else "BLOCKED_DATA",
        "as_of": as_of,
        "snapshot": snapshot,
        "datasets": statuses,
        "index_rows": observed.get("index_intraday", []),
        "theme_rows": observed.get("theme_intraday", []),
        "theme_names_requested": theme_names or [],
        "reason": None if not missing else "截至快照的指数/板块分时数据分区缺失或为空",
    }


def _ma(vals, n):
    return round(sum(vals[-n:]) / n, 2) if len(vals) >= n else None


def index_context(as_of: str, lookback_days: int = 60) -> dict:
    import datetime as dt
    end = dt.date.fromisoformat(as_of)
    start = (end - dt.timedelta(days=lookback_days * 2)).isoformat()

    out = {}
    for code, name in INDICES.items():
        try:
            bars = index_daily(code, start, as_of)
        except Exception as e:  # noqa: BLE001
            out[code] = {"name": name, "available": False, "error": type(e).__name__}
            continue
        bars = [b for b in bars if b.get("close_price") is not None]
        if len(bars) < 6:
            out[code] = {"name": name, "available": False}
            continue
        closes = [b["close_price"] for b in bars]
        last = closes[-1]
        out[code] = {
            "name": name,
            "available": True,
            "last_close": round(last, 2),
            "ret_1d_pct": round((last / closes[-2] - 1) * 100, 2),
            "ret_5d_pct": round((last / closes[-6] - 1) * 100, 2) if len(closes) >= 6 else None,
            "ret_20d_pct": round((last / closes[-21] - 1) * 100, 2) if len(closes) >= 21 else None,
            "ma5": _ma(closes, 5), "ma10": _ma(closes, 10), "ma20": _ma(closes, 20),
            "above_ma5": (last >= _ma(closes, 5)) if _ma(closes, 5) else None,
            "above_ma20": (last >= _ma(closes, 20)) if _ma(closes, 20) else None,
            "n_bars": len(closes),
        }
    return out


if __name__ == "__main__":
    import json
    import sys
    as_of = sys.argv[1] if len(sys.argv) > 1 else "2026-09-08"
    print(json.dumps(index_context(as_of), ensure_ascii=False, indent=2))
