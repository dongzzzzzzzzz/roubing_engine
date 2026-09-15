"""Normalize the Financial-API market dump into stock_daily_bar (raw, unadjusted).

Stored as one columnar parquet (warehouse/stock_daily_bar/all.parquet) keyed by
(thscode, trade_date). as_of slicing is done by filtering trade_date <= cutoff,
which is cheaper than thousands of per-date partitions for full-market daily.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from roubing_engine.config import WAREHOUSE

DUMP_PATH = WAREHOUSE.parent / "dumps" / "daily_k.parquet"
DAILY_BAR = WAREHOUSE / "stock_daily_bar" / "all.parquet"

# tolerant column resolution (dump vs historical API naming)
_COL = {
    "thscode": ["thscode", "ths_code", "code", "symbol"],
    "date_ms": ["date_ms", "trade_date_ms", "time_ms"],
    "open": ["open_price", "open"],
    "high": ["high_price", "high"],
    "low": ["low_price", "low"],
    "close": ["close_price", "close"],
    "volume": ["volume", "vol"],
    "turnover": ["turnover", "amount"],
}


def _pick_col(df, names):
    for n in names:
        if n in df.columns:
            return n
    return None


def load_dump() -> dict:
    if not DUMP_PATH.exists():
        raise SystemExit(f"dump not found: {DUMP_PATH}")
    df = pd.read_parquet(DUMP_PATH)
    resolved = {k: _pick_col(df, v) for k, v in _COL.items()}
    missing = [k for k, v in resolved.items() if v is None and k != "turnover"]
    if missing:
        raise SystemExit(f"dump missing columns {missing}; actual cols={list(df.columns)[:20]}")

    out = pd.DataFrame({
        "thscode": df[resolved["thscode"]].astype(str),
        "open": df[resolved["open"]],
        "high": df[resolved["high"]],
        "low": df[resolved["low"]],
        "close": df[resolved["close"]],
        "volume": df[resolved["volume"]],
    })
    if resolved["turnover"]:
        out["amount"] = df[resolved["turnover"]]
        out["turnover"] = df[resolved["turnover"]]
    else:
        out["amount"] = pd.NA
    # trade_date YYYYMMDD from ms (Asia/Shanghai)
    ms = df[resolved["date_ms"]].astype("int64")
    out["trade_date"] = pd.to_datetime(ms, unit="ms", utc=True).dt.tz_convert(
        "Asia/Shanghai").dt.strftime("%Y%m%d")
    out["event_time"] = pd.to_datetime(ms, unit="ms", utc=True).dt.tz_convert(
        "Asia/Shanghai").dt.strftime("%Y-%m-%d 15:00:00 Asia/Shanghai")
    out["eltdx_code"] = out["thscode"].str.split(".").str[0]
    out["adjust"] = df["adjusted"].astype(str) if "adjusted" in df.columns else "none"
    out["adj_open"] = out["open"]
    out["adj_high"] = out["high"]
    out["adj_low"] = out["low"]
    out["adj_close"] = out["close"]
    out["volume_unit"] = "share"
    out["source"] = "Financial-API"
    out["interface"] = "daily_k.dump"
    fetched_at = dt.datetime.now(dt.timezone.utc).isoformat()
    out["fetched_at"] = fetched_at
    out["request_id"] = (
        "financial-api-daily-k:"
        + out["thscode"].astype(str) + ":" + out["trade_date"].astype(str)
    )
    out = out.sort_values(["thscode", "trade_date"])
    prev_close = out.groupby("thscode")["close"].shift(1)
    out["change_pct"] = ((out["close"] / prev_close - 1) * 100).round(4)
    out.loc[prev_close.isna() | (prev_close == 0), "change_pct"] = pd.NA

    out = out.dropna(subset=["thscode", "trade_date", "close"])
    out = out.drop_duplicates(subset=["thscode", "trade_date"], keep="last")

    DAILY_BAR.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(DAILY_BAR, engine="pyarrow", index=False)
    return {
        "rows": len(out),
        "n_stocks": out["thscode"].nunique(),
        "date_min": out["trade_date"].min(),
        "date_max": out["trade_date"].max(),
        "path": str(DAILY_BAR),
    }


def read_daily_asof(as_of_date: str, thscodes: list[str] | None = None) -> pd.DataFrame:
    """Daily bars with trade_date <= as_of (YYYY-MM-DD). Anti-lookahead safe."""
    if not DAILY_BAR.exists():
        return pd.DataFrame()
    cutoff = as_of_date.replace("-", "")
    filters = [("trade_date", "<=", cutoff)]
    if thscodes:
        filters.append(("thscode", "in", set(thscodes)))
    return pd.read_parquet(DAILY_BAR, engine="pyarrow", filters=filters)


if __name__ == "__main__":
    import json
    print(json.dumps(load_dump(), ensure_ascii=False, indent=2))
