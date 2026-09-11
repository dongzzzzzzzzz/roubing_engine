"""Deterministic per-stock features from the daily warehouse (anti-lookahead).

Batch reads bars <= as_of for a code list, then computes facts:
interval return from an anchor, lookback high/low & drawdown, breakout of prior
high, platform (consolidation) detection, turnover percentile vs own history,
up-day streak, MA position. Facts only — no 龙头/主升/洗盘.
"""
from __future__ import annotations

import pandas as pd

from roubing_engine.warehouse.daily_loader import read_daily_asof


def _py(v):
    """Coerce numpy scalars to native Python types for JSON."""
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:  # noqa: BLE001
            return v
    return v


def _ma(vals, n):
    return round(sum(vals[-n:]) / n, 3) if len(vals) >= n else None


def _pctile(series_vals, x):
    if not series_vals or x is None:
        return None
    below = sum(1 for v in series_vals if v <= x)
    return round(below / len(series_vals), 3)


def _one(g: pd.DataFrame, anchor: str | None, lookback: int) -> dict:
    g = g.sort_values("trade_date")
    closes = [float(x) for x in g["close"].tolist()]
    highs = [float(x) for x in g["high"].tolist()]
    turns = [float(x) for x in g["turnover"].dropna().tolist()] if "turnover" in g else []
    if len(closes) < 2:
        return {"available": False}
    last, prev = closes[-1], closes[-2]
    win = g.tail(lookback)
    win_high = float(win["high"].max())
    win_low = float(win["low"].min())

    interval_ret = None
    if anchor:
        a = anchor.replace("-", "")
        idx = g.index[g["trade_date"] >= a]
        if len(idx):
            pos = g.index.get_loc(idx[0])
            if pos > 0:
                base = closes[pos - 1]
                if base:
                    interval_ret = round((last / base - 1) * 100, 2)

    streak = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            streak += 1
        else:
            break

    # Every pressure/range reference is frozen strictly before the current bar.
    prior_window = g.iloc[:-1].tail(lookback)
    prior_high = float(prior_window["high"].max()) if not prior_window.empty else highs[-1]

    # Raw pre-T ranges only. Whether one of them is the relevant "platform" is
    # contextual AI/human work; the author did not define a universal 12% gate.
    prior_ranges = {}
    for n in (5, 10, 15):
        sample = g.iloc[:-1].tail(n)
        if len(sample) < n or float(sample["low"].min()) <= 0:
            prior_ranges[str(n)] = None
            continue
        high = float(sample["high"].max())
        low = float(sample["low"].min())
        prior_ranges[str(n)] = {
            "high": round(high, 3),
            "low": round(low, 3),
            "span_pct": round((high / low - 1) * 100, 2),
        }

    last_turnover = float(g["turnover"].iloc[-1]) if "turnover" in g and pd.notna(g["turnover"].iloc[-1]) else None

    return {
        "available": True,
        "last_close": round(last, 3),
        "ret_today_pct": round((last / prev - 1) * 100, 2) if prev else None,
        "interval_return_pct": interval_ret,
        "anchor": anchor,
        "lookback": lookback,
        "lookback_high": round(win_high, 3),
        "lookback_low": round(win_low, 3),
        "dist_to_lookback_high_pct": round((last / win_high - 1) * 100, 2) if win_high else None,
        "is_close_above_prior_high": bool(last >= prior_high),
        "prior_high": round(prior_high, 3),
        "pre_t_ranges": prior_ranges,
        "turnover_pctile_250d": _pctile(turns[-250:], last_turnover),
        "up_day_streak": streak,
        "ma5": _ma(closes, 5), "ma10": _ma(closes, 10), "ma20": _ma(closes, 20),
        "above_ma5": (last >= _ma(closes, 5)) if _ma(closes, 5) else None,
        "feature_discipline": "pre_t_ranges are raw facts, not an automatic platform/breakout rule",
        "n_bars": len(closes),
    }


def features_for(codes: list[str], as_of: str, anchor: str | None = None,
                 lookback: int = 60) -> dict[str, dict]:
    df = read_daily_asof(as_of, thscodes=codes)
    out = {}
    if df.empty:
        return {c: {"available": False} for c in codes}
    for code, g in df.groupby("thscode"):
        out[code] = _one(g, anchor, lookback)
    for c in codes:
        out.setdefault(c, {"available": False})
    return out


if __name__ == "__main__":
    import json
    import sys
    codes = sys.argv[1].split(",") if len(sys.argv) > 1 else ["600108.SH", "600354.SH"]
    as_of = sys.argv[2] if len(sys.argv) > 2 else "2026-09-08"
    print(json.dumps(features_for(codes, as_of), ensure_ascii=False, indent=2))
