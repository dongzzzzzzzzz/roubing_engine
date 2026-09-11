"""Stage A: deterministic evidence compiler (no agent, no inference words).

Reads the immutable warehouse for one trade date and emits a structured facts
dict: market breadth, ladder distribution, and theme grouping keyed by
limit-up reason (plan §7.2 "涨停原因是短线题材归组的第一入口"). Downstream
agent stages (environment / mainstream / node reasoning) consume this; this
stage never uses words like 主流/龙头/洗盘.
"""
from __future__ import annotations

from collections import defaultdict
import datetime as dt

import pandas as pd

from roubing_engine.config import WAREHOUSE
from roubing_engine.collectors.storage import partition_profile
from roubing_engine.rules.themes import canonical_theme
from roubing_engine.warehouse.daily_loader import DAILY_BAR


def _read(dataset: str, yyyymmdd: str) -> pd.DataFrame:
    p = WAREHOUSE / dataset / f"date={yyyymmdd}" / "part.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def _clean(v):
    return None if (v is None or (isinstance(v, float) and pd.isna(v))) else v


def _daily_market_facts(yyyymmdd: str) -> tuple[dict, dict[str, float]]:
    """Full-market close breadth/turnover and per-code daily return."""
    if not DAILY_BAR.exists():
        return {"available": False, "reason": "stock_daily_bar missing"}, {}
    day = dt.date(int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:]))
    start = (day - dt.timedelta(days=14)).strftime("%Y%m%d")
    frame = pd.read_parquet(
        DAILY_BAR,
        columns=["thscode", "trade_date", "close", "turnover"],
        filters=[("trade_date", ">=", start), ("trade_date", "<=", yyyymmdd)],
    )
    dates = sorted(str(value) for value in frame["trade_date"].dropna().unique())
    if yyyymmdd not in dates:
        return {"available": False, "reason": "current daily market rows missing"}, {}
    prior = [value for value in dates if value < yyyymmdd]
    if not prior:
        return {"available": False, "reason": "previous market day missing"}, {}
    previous_date = prior[-1]
    current = frame[frame["trade_date"] == yyyymmdd][["thscode", "close", "turnover"]]
    previous = frame[frame["trade_date"] == previous_date][["thscode", "close", "turnover"]]
    merged = current.merge(previous, on="thscode", suffixes=("_today", "_previous"))
    merged = merged[(merged["close_previous"] > 0) & merged["close_today"].notna()]
    merged["ret_pct"] = (merged["close_today"] / merged["close_previous"] - 1) * 100
    returns = dict(zip(merged["thscode"].astype(str), merged["ret_pct"].round(4)))
    up = int((merged["ret_pct"] > 0).sum())
    down = int((merged["ret_pct"] < 0).sum())
    flat = int((merged["ret_pct"] == 0).sum())
    turnover_today = float(current["turnover"].dropna().sum())
    turnover_previous = float(previous["turnover"].dropna().sum())
    return {
        "available": True,
        "previous_trade_date": previous_date,
        "n_stocks_compared": int(len(merged)),
        "n_advance": up,
        "n_decline": down,
        "n_flat": flat,
        "turnover_today": round(turnover_today, 2),
        "turnover_previous": round(turnover_previous, 2),
        "turnover_change_pct": round((turnover_today / turnover_previous - 1) * 100, 2)
        if turnover_previous else None,
    }, returns


def _previous_universe_date(yyyymmdd: str) -> str | None:
    base = WAREHOUSE / "universe"
    dates = sorted(
        p.name.split("=", 1)[1] for p in base.glob("date=*")
        if p.name.split("=", 1)[1] < yyyymmdd
    ) if base.exists() else []
    return dates[-1] if dates else None


def _prior_strong_feedback(yyyymmdd: str, returns: dict[str, float], current: pd.DataFrame,
                           expected_previous_date: str | None = None) -> dict:
    previous_date = _previous_universe_date(yyyymmdd)
    if not previous_date:
        return {"available": False, "reason": "previous universe partition missing"}
    if expected_previous_date and previous_date != expected_previous_date:
        return {
            "available": False,
            "reason": "immediately previous universe partition missing",
            "expected_previous_trade_date": expected_previous_date,
            "nearest_captured_previous_date": previous_date,
        }
    previous = _read("universe", previous_date)
    if previous.empty:
        return {"available": False, "reason": "previous universe partition empty"}
    prior_up = previous[previous["status"] == "limit_up"]
    current_by = current.set_index("thscode").to_dict("index") if not current.empty else {}
    rows = []
    for _, record in prior_up.iterrows():
        code = str(record.get("thscode"))
        today = current_by.get(code, {})
        rows.append({
            "thscode": code,
            "name": _clean(record.get("name")),
            "previous_board_level": _clean(record.get("board_level")),
            "previous_reason": _clean(record.get("reason")),
            "today_ret_pct": _clean(returns.get(code)),
            "today_limit_status": _clean(today.get("status")),
            "today_board_level": _clean(today.get("board_level")),
        })
    known = [row["today_ret_pct"] for row in rows if row["today_ret_pct"] is not None]
    return {
        "available": bool(known),
        "previous_trade_date": previous_date,
        "n_previous_limit_up": int(len(rows)),
        "n_positive_feedback": sum(1 for value in known if value > 0),
        "n_negative_feedback": sum(1 for value in known if value < 0),
        "rows": rows,
    }


def compile_day(yyyymmdd: str) -> dict:
    uni = _read("universe", yyyymmdd)
    if uni.empty:
        return {"trade_date": yyyymmdd, "available": False, "reason": "no universe partition"}

    up = uni[uni["status"] == "limit_up"]
    down = uni[uni["status"] == "limit_down"]
    broken = uni[uni["status"] == "broken"]

    daily_market, daily_returns = _daily_market_facts(yyyymmdd)
    breadth = {
        "n_limit_up": int(len(up)),
        "n_limit_down": int(len(down)),
        "n_broken": int(len(broken)),
        "full_market": daily_market,
    }

    # ladder distribution over board_level among limit-up
    ladder = defaultdict(int)
    for b in up["board_level"].dropna():
        ladder[int(b)] += 1
    ladder_dist = {str(k): v for k, v in sorted(ladder.items())}
    max_board = int(up["board_level"].dropna().max()) if not up["board_level"].dropna().empty else 0

    # Theme aliases are merged only when an evidence-backed registry says so.
    up = up.copy()
    up["_canonical_theme"] = up["reason"].map(lambda raw: canonical_theme(raw)[0])
    themes = []
    for reason, g in up.groupby("_canonical_theme", dropna=False):
        codes = []
        for _, r in g.iterrows():
            codes.append({
                "thscode": _clean(r.get("thscode")),
                "name": _clean(r.get("name")),
                "board_level": _clean(r.get("board_level")),
                "highest_board_level": _clean(r.get("highest_board_level")),
                "consecutive_limit_days": _clean(r.get("consecutive_limit_days")),
                "limit_time": _clean(r.get("limit_time")),
                "seal_amount": _clean(r.get("seal_amount")),
                "reason_extra": _clean(r.get("limit_reason_extra")),
            })
        boards = [c["board_level"] for c in codes if c["board_level"] is not None]
        themes.append({
            "reason": _clean(reason) or "(未标注)",
            "raw_reasons": sorted({_clean(x) or "(未标注)" for x in g["reason"].tolist()}),
            "normalization": canonical_theme(_clean(g.iloc[0].get("reason")))[1],
            "n_limit_up": len(codes),
            "max_board": int(max(boards)) if boards else 0,
            "n_first_board": sum(1 for c in codes if c["board_level"] == 1),
            "codes": sorted(codes, key=lambda c: (-(c["board_level"] or 0),
                                                  c["limit_time"] or "99")),
        })
    themes.sort(key=lambda t: (-t["max_board"], -t["n_limit_up"]))

    failed_observations = []
    for _, record in pd.concat([broken, down], ignore_index=True).iterrows():
        failed_observations.append({
            "thscode": _clean(record.get("thscode")),
            "name": _clean(record.get("name")),
            "status": _clean(record.get("status")),
            "raw_reason": _clean(record.get("reason")),
            "theme": canonical_theme(_clean(record.get("reason")))[0],
            "broken_count": _clean(record.get("broken_count")),
            "note": "失败观察事实；主动/被动原因未知",
        })

    # Completeness is a coverage profile, not just a partition-exists boolean.
    have = {ds: partition_profile(ds, yyyymmdd)
            for ds in ("universe", "auction_point", "opening_match", "minute_bar", "trade_tick",
                       "announcement", "hot_topic")}

    return {
        "trade_date": yyyymmdd,
        "available": True,
        "as_of": f"{yyyymmdd} CLOSE",
        "source": "eltdx",
        "market_breadth": breadth,
        "ladder_distribution": ladder_dist,
        "max_board": max_board,
        "themes": themes,
        "failed_observations": failed_observations,
        "previous_buyer_feedback": _prior_strong_feedback(
            yyyymmdd, daily_returns, uni, daily_market.get("previous_trade_date")),
        "data_completeness": have,
        "theme_registry_policy": "evidence-backed aliases only; unknown reasons remain separate",
        "note": "deterministic facts only; no environment/mainstream/role inference here",
    }


if __name__ == "__main__":
    import json
    import sys
    date = sys.argv[1] if len(sys.argv) > 1 else "20260908"
    facts = compile_day(date)
    # compact top-of-report view
    print(json.dumps({
        "trade_date": facts["trade_date"],
        "breadth": facts.get("market_breadth"),
        "ladder": facts.get("ladder_distribution"),
        "max_board": facts.get("max_board"),
        "top_themes": [
            {"reason": t["reason"], "n": t["n_limit_up"], "max_board": t["max_board"]}
            for t in facts.get("themes", [])[:8]
        ],
        "data_completeness": facts.get("data_completeness"),
    }, ensure_ascii=False, indent=2))
