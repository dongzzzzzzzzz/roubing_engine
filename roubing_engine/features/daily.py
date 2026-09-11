"""Deterministic daily-bar features for a candidate shortlist (lazy eltdx fetch).

These are FACTS only (interval return from an anchor, recent high/platform,
breakout flag, drawdown, up-day count). No 龙头/主流/洗盘 wording. Computed on
demand for a small code list, not the whole market.
"""
from __future__ import annotations

from datetime import date, datetime

from roubing_engine.collectors.eltdx_client import to_eltdx_code, with_retry


def _as_date(x) -> date | None:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return None


def daily_features(client, thscode: str, as_of: str, anchor: str | None = None,
                   lookback: int = 60) -> dict:
    """as_of / anchor are 'YYYY-MM-DD'. Uses only bars on/before as_of."""
    ec = to_eltdx_code(thscode)
    series = with_retry(client.bars.get, ec, period="day", adjust="qfq", count=250)
    bars = [b for b in (getattr(series, "bars", []) or [])
            if (_as_date(getattr(b, "time", None)) or date.max) <= date.fromisoformat(as_of)]
    if len(bars) < 2:
        return {"thscode": thscode, "available": False}

    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    last, prev = closes[-1], closes[-2]

    win = bars[-lookback:] if len(bars) >= lookback else bars
    win_high = max(b.high for b in win)
    win_low = min(b.low for b in win)

    # interval return from anchor date (inclusive of anchor's prev close base)
    interval_ret = None
    if anchor:
        adate = date.fromisoformat(anchor)
        base_idx = next((i for i, b in enumerate(bars)
                         if (_as_date(b.time) or date.min) >= adate), None)
        if base_idx is not None and base_idx > 0:
            base = closes[base_idx - 1]
            if base:
                interval_ret = round((last / base - 1) * 100, 2)

    # up-day streak (close>prev)
    streak = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            streak += 1
        else:
            break

    prior_bars = bars[:-1]
    prior_win = prior_bars[-lookback:] if len(prior_bars) >= lookback else prior_bars
    prior_high = max(b.high for b in prior_win) if prior_win else highs[-1]
    return {
        "thscode": thscode,
        "available": True,
        "as_of": as_of,
        "last_close": round(last, 3),
        "ret_today_pct": round((last / prev - 1) * 100, 2) if prev else None,
        "interval_return_pct": interval_ret,
        "anchor": anchor,
        "lookback": lookback,
        "lookback_high": round(win_high, 3),
        "lookback_low": round(win_low, 3),
        "dist_to_lookback_high_pct": round((last / win_high - 1) * 100, 2) if win_high else None,
        "drawdown_from_lookback_high_pct": round((last / win_high - 1) * 100, 2) if win_high else None,
        "is_close_above_prior_high": bool(last >= prior_high),
        "up_day_streak": streak,
        "n_bars_used": len(bars),
    }


if __name__ == "__main__":
    import json
    import sys
    from roubing_engine.collectors.eltdx_client import client
    codes = sys.argv[1].split(",") if len(sys.argv) > 1 else ["000833.SZ", "002579.SZ"]
    as_of = sys.argv[2] if len(sys.argv) > 2 else "2026-09-08"
    with client() as c:
        for code in codes:
            print(json.dumps(daily_features(c, code, as_of), ensure_ascii=False))
