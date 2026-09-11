"""Market-effect evaluation (plan §27.4). EVALUATION ONLY — deliberately uses
post-plan (future) bars to score outcomes. Never import this into reasoning.
"""
from __future__ import annotations

import pandas as pd

from roubing_engine.warehouse.daily_loader import DAILY_BAR


def _bars(thscode: str) -> pd.DataFrame:
    if not DAILY_BAR.exists():
        return pd.DataFrame()
    df = pd.read_parquet(DAILY_BAR, filters=[("thscode", "==", thscode)])
    return df.sort_values("trade_date")


def forward_returns(thscode: str, plan_date: str, horizons=(1, 2, 3)) -> dict:
    """Close-to-close returns from plan_date close over the next N trade days."""
    df = _bars(thscode)
    if df.empty:
        return {"available": False}
    d = plan_date.replace("-", "")
    idx = df.index[df["trade_date"] <= d]
    if len(idx) == 0:
        return {"available": False}
    pos = df.index.get_loc(idx[-1])
    closes = df["close"].tolist()
    base = closes[pos]
    out = {"available": True, "base_close": round(float(base), 3)}
    for h in horizons:
        if pos + h < len(closes):
            out[f"ret_{h}d_pct"] = round((closes[pos + h] / base - 1) * 100, 2)
        else:
            out[f"ret_{h}d_pct"] = None
    return out


def evaluate_candidates(candidates: list[dict], plan_date: str, horizons=(1, 2, 3)) -> dict:
    rows = []
    for c in candidates:
        fr = forward_returns(c.get("thscode"), plan_date, horizons=horizons)
        rows.append({"thscode": c.get("thscode"), "tier": c.get("output_tier"),
                     "role": c.get("role"),
                     "selection_status": c.get("selection_status", "SELECTED"),
                     "exclusion_reason": c.get("reason"),
                     **{k: v for k, v in fr.items() if k != "available"}})
    return {"plan_date": plan_date, "n": len(rows), "results": rows}
