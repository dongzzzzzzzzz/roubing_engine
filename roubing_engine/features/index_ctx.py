"""Deterministic index context up to as_of (facts only, no 主升/退潮 wording).

Fills the gap Stage B kept flagging: index trend / position vs MA / recent
return for 上证/深证/创业板. Uses only bars on/before as_of.
"""
from __future__ import annotations

from roubing_engine.collectors.financial_api import index_daily

INDICES = {
    "000001.SH": "上证指数",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
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
