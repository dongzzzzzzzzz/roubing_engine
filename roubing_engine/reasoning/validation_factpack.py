"""Stage D input: deterministic T+1 validation facts for the T-day plan candidates.

For each candidate, from T+1 (candidate-only) partitions:
  - 竞价高开幅 (open_change_pct), 09:25 撮合
  - 竞价过程摘要: 是否一字、匹配量是否明显撤单
  - 开盘五分钟: 09:31-09:35 相对开盘的价格路径、是否翻绿/收回
  - 主动性: 开盘五分钟主动买/卖量比 (trade side)
Facts only; the 确认/降级/替代/取消 judgement is the agent's (Stage D).

This module is a hard time gate.  AUCTION_0925 sees only the opening auction;
OPEN_0935 additionally sees events through 09:35:59.  Close outcomes belong to
the later CLOSE_REVIEW/evaluation stage and are intentionally unavailable here.
"""
from __future__ import annotations

import pandas as pd

from roubing_engine.config import WAREHOUSE
from roubing_engine.warehouse.timebox import (
    OPEN_5M_END,
    OPEN_START,
    SNAPSHOT_CUTOFFS,
    row_seconds,
    snapshot_as_of,
)


def _read(dataset: str, yyyymmdd: str) -> pd.DataFrame:
    p = WAREHOUSE / dataset / f"date={yyyymmdd}" / "part.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def _clean(v):
    return None if (v is None or (isinstance(v, float) and pd.isna(v))) else v


def _auction_summary(df):
    if df.empty:
        return None
    # Old captured rows may not yet have session_type.  Filter by event time as
    # the authoritative boundary so a 14:57 closing-auction point can never be
    # interpreted as the 09:25 terminal observation.
    def is_opening_point(row):
        seconds = row_seconds(row)
        declared = row.get("session_type")
        return (declared != "CLOSING_AUCTION" and seconds is not None
                and seconds <= SNAPSHOT_CUTOFFS["AUCTION_0925"])
    df = df[df.apply(is_opening_point, axis=1)]
    if df.empty:
        return None
    df = df.assign(_event_seconds=df.apply(row_seconds, axis=1)).sort_values("_event_seconds")
    prices = df["price"].tolist()
    matched = df["matched_volume"].tolist()
    first_p, last_p = prices[0], prices[-1]
    peak_matched = max(matched) if matched else 0
    last_matched = matched[-1] if matched else 0
    return {
        "n_points": len(df),
        "first_time": _clean(df.iloc[0].get("time_label")),
        "last_time": _clean(df.iloc[-1].get("time_label")),
        "first_price": round(first_p, 3),
        "last_observed_process_price": round(last_p, 3),
        "price_flat_through_auction": bool(max(prices) - min(prices) <= 0.01),
        "matched_peak_vol": int(peak_matched),
        "matched_last_observed_vol": int(last_matched),
        # raw ratio only; 成交明细≠委托流，不断言“撤单”（见方案纪律）
        "matched_last_over_peak": round(last_matched / peak_matched, 3) if peak_matched else None,
    }


def _open5m(minutes_df, open_price, pre_close=None):
    if minutes_df.empty or open_price is None:
        return None
    df = minutes_df.copy()
    df["_event_seconds"] = df.apply(row_seconds, axis=1)
    first5 = df[df["_event_seconds"].between(OPEN_START, OPEN_5M_END)].sort_values(
        "_event_seconds")
    if first5.empty:
        return None
    path = []
    for _, r in first5.iterrows():
        p = r["price"]
        path.append({"t": r["time_label"], "price": round(p, 3),
                     "pct_from_open": round((p / open_price - 1) * 100, 2)})
    pcts = [x["pct_from_open"] for x in path]
    prev_pcts = [round((x["price"] / pre_close - 1) * 100, 2) for x in path] if pre_close else []
    return {
        "path": path,
        "first_time": _clean(first5.iloc[0].get("time_label")),
        "last_time": _clean(first5.iloc[-1].get("time_label")),
        "min_pct_from_open": min(pcts) if pcts else None,
        "last5_pct_from_open": pcts[-1] if pcts else None,
        "fell_below_open_then_recovered": bool(pcts and min(pcts) < 0 <= pcts[-1]),
        "min_pct_from_pre_close": min(prev_pcts) if prev_pcts else None,
        "last_pct_from_pre_close": prev_pcts[-1] if prev_pcts else None,
        "fell_below_preclose_then_turned_red": bool(
            prev_pcts and min(prev_pcts) < 0 <= prev_pcts[-1]),
    }


def _first5m_activity(trades_df):
    if trades_df.empty:
        return None
    df = trades_df.copy()
    df["_event_seconds"] = df.apply(row_seconds, axis=1)
    df = df[df["_event_seconds"].between(OPEN_START, OPEN_5M_END)]
    if df.empty:
        return None
    buy = df[df["side"] == "buy"]["volume"].sum()
    sell = df[df["side"] == "sell"]["volume"].sum()
    tot = buy + sell
    return {
        "buy_vol": int(buy), "sell_vol": int(sell),
        "buy_ratio": round(buy / tot, 3) if tot else None,
        "n_ticks": int(len(df)),
        "first_time": _clean(df["time_label"].min()),
        "last_time": _clean(df["time_label"].max()),
    }


def build(plan_candidates: list[dict], tplus1: str, client=None,
          snapshot: str = "OPEN_0935") -> dict:
    """Build a time-clean Stage-D fact pack.

    ``client`` is retained for call-site compatibility but deliberately unused:
    daily APIs generally return the completed T+1 bar and therefore cannot be
    queried in a 09:25/09:35 validation stage.
    """
    if snapshot not in SNAPSHOT_CUTOFFS:
        raise ValueError(f"unknown snapshot: {snapshot}")
    yyyymmdd = tplus1.replace("-", "")
    op = _read("opening_match", yyyymmdd)
    op_by = {r["thscode"]: r for _, r in op.iterrows()} if not op.empty else {}
    auc = _read("auction_point", yyyymmdd)
    mn = _read("minute_bar", yyyymmdd)
    tr = _read("trade_tick", yyyymmdd)

    out_candidates = []
    for cand in plan_candidates:
        code = cand.get("thscode")
        oprow = op_by.get(code)
        open_price = _clean(oprow.get("open_price")) if oprow is not None else None
        pre_close = _clean(oprow.get("pre_close_price")) if oprow is not None else None
        rec = {
            "thscode": code,
            "plan_tier": cand.get("output_tier"),
            "plan_role": cand.get("role"),
            "plan_theme": cand.get("theme"),
            "plan_tomorrow_must_do": cand.get("tomorrow_must_do"),
            "plan_failure_signals": cand.get("failure_signals"),
            "auction_open_change_pct": _clean(oprow.get("open_change_pct")) if oprow is not None else None,
            "pre_close": pre_close,
            "open_price": open_price,
            "auction_summary": _auction_summary(auc[auc["thscode"] == code]) if not auc.empty else None,
            "open_5min": (_open5m(mn[mn["thscode"] == code], open_price, pre_close)
                           if snapshot == "OPEN_0935" and not mn.empty else None),
            "first5m_activity": (_first5m_activity(tr[tr["thscode"] == code])
                                  if snapshot == "OPEN_0935" and not tr.empty else None),
        }
        open5_points = len((rec.get("open_5min") or {}).get("path", []))
        rec["data_completeness"] = {
            "opening_match": "AVAILABLE" if oprow is not None else "MISSING",
            "opening_auction": "AVAILABLE" if rec["auction_summary"] is not None else "MISSING",
            "open_5min": (
                "AVAILABLE" if open5_points >= 5 else "PARTIAL" if open5_points else "MISSING"
            ) if snapshot == "OPEN_0935" else "NOT_IN_SNAPSHOT",
            "first5m_activity": (
                "AVAILABLE" if rec["first5m_activity"] is not None else "MISSING"
            ) if snapshot == "OPEN_0935" else "NOT_IN_SNAPSHOT",
        }
        out_candidates.append(rec)

    facts = {
        "tplus1": tplus1,
        "snapshot": snapshot,
        "as_of": snapshot_as_of(tplus1, snapshot),
        "candidates": out_candidates,
        "market_check_data": {
            "available": False,
            "reason": "未接入截至该快照的指数/板块分时；禁止使用T+1收盘指数替代",
        },
    }
    problems = validate_snapshot_payload(facts)
    if problems:
        raise RuntimeError("invalid Stage-D snapshot: " + "; ".join(problems))
    return facts


def validate_snapshot_payload(facts: dict) -> list[str]:
    """Reject future/outcome fields and events beyond the declared cutoff."""
    forbidden = {
        "day_close_price", "tplus1_ret_pct", "tplus1_close",
        "tplus1_limit_up_est", "index_context_tplus1", "close_price",
        "final_limit_up", "outcome",
    }
    problems: list[str] = []

    def walk(value, path="$"):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in forbidden:
                    problems.append(f"{path}.{key}: forbidden after-snapshot field")
                walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(facts)
    snapshot = facts.get("snapshot")
    cutoff = SNAPSHOT_CUTOFFS.get(snapshot)
    if cutoff is None:
        problems.append(f"$.snapshot: unknown snapshot {snapshot!r}")
        return problems
    for index, candidate in enumerate(facts.get("candidates", [])):
        auction = candidate.get("auction_summary") or {}
        last_auction = row_seconds({"time_label": auction.get("last_time")})
        if last_auction is not None and last_auction > SNAPSHOT_CUTOFFS["AUCTION_0925"]:
            problems.append(f"$.candidates[{index}].auction_summary: extends beyond 09:25")
        open5 = candidate.get("open_5min") or {}
        for point_index, point in enumerate(open5.get("path", [])):
            event = row_seconds({"time_label": point.get("t")})
            if event is not None and event > cutoff:
                problems.append(
                    f"$.candidates[{index}].open_5min.path[{point_index}]: future event")
    return problems
