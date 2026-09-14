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
import hashlib

import pandas as pd

from roubing_engine.config import WAREHOUSE
from roubing_engine.collectors.storage import partition_profile
from roubing_engine.rules.themes import canonical_theme, hierarchy_for
from roubing_engine.warehouse.daily_loader import DAILY_BAR


def _read(dataset: str, yyyymmdd: str) -> pd.DataFrame:
    p = WAREHOUSE / dataset / f"date={yyyymmdd}" / "part.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def _clean(v):
    return None if (v is None or (isinstance(v, float) and pd.isna(v))) else v


def fact_id(yyyymmdd: str, scope: str, identity: str) -> str:
    """Return a stable, compact identifier for one immutable fact row.

    The readable prefix makes prompts/audits understandable while the digest
    keeps Chinese themes and changing punctuation out of identifiers.  The ID
    depends only on trade date, scope and the fact identity, never list order.
    """
    digest = hashlib.sha256(
        f"{yyyymmdd}|{scope}|{identity}".encode("utf-8")
    ).hexdigest()[:10].upper()
    return f"F-{yyyymmdd}-{scope.upper()}-{digest}"


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


def _direction_facts(uni: pd.DataFrame, yyyymmdd: str) -> list[dict]:
    """Summarize observable direction breadth without inventing full diffusion.

    The captured universe is a limit-up/broken/limit-down event roster, not a
    complete all-stock theme membership table.  Therefore the summary reports
    event counts and coverage, while explicitly marking ordinary non-limit
    diffusion as unavailable.
    """
    if uni.empty:
        return []
    work = uni.copy()
    work["_theme"] = work["reason"].map(
        lambda raw: canonical_theme(raw, yyyymmdd)[0] or "(未标注)")
    opening = _read("opening_match", yyyymmdd)
    opening_codes = set(opening["thscode"].astype(str)) if not opening.empty else set()
    turnover_by_code: dict[str, float] = {}
    if DAILY_BAR.exists():
        try:
            day = pd.read_parquet(DAILY_BAR, columns=["thscode", "trade_date", "turnover"],
                                  filters=[("trade_date", "=", yyyymmdd)])
            turnover_by_code = {
                str(row["thscode"]): float(row["turnover"])
                for _, row in day.iterrows() if pd.notna(row.get("turnover"))
            }
        except Exception:  # noqa: BLE001 - preserve a structured data gap
            turnover_by_code = {}
    out = []
    for theme, group in work.groupby("_theme", dropna=False):
        up = group[group["status"] == "limit_up"]
        ladder = defaultdict(int)
        for value in up["board_level"].dropna():
            ladder[str(int(value))] += 1
        codes = {str(value) for value in group["thscode"].dropna()}
        opening_covered = len(codes & opening_codes)
        turnover = sum(turnover_by_code.get(code, 0.0) for code in codes)
        known_turnover = sum(1 for code in codes if code in turnover_by_code)
        out.append({
            "theme": theme,
            "n_limit_up": int((group["status"] == "limit_up").sum()),
            "n_broken": int((group["status"] == "broken").sum()),
            "n_limit_down": int((group["status"] == "limit_down").sum()),
            "ladder_distribution": dict(sorted(ladder.items(), key=lambda item: int(item[0]))),
            "opening_match_coverage": {
                "covered": int(opening_covered),
                "eligible_event_rows": int(len(codes)),
                "status": ("AVAILABLE" if opening_covered == len(codes) and codes else
                           "PARTIAL" if opening_covered else "MISSING"),
            },
            "turnover": {
                "value_yuan": round(turnover, 2) if known_turnover else None,
                "known_codes": known_turnover,
                "eligible_event_rows": len(codes),
                "status": ("AVAILABLE" if known_turnover == len(codes) and codes else
                           "PARTIAL" if known_turnover else "MISSING"),
            },
            "diffusion": {
                "available": False,
                "status": "BLOCKED_DATA",
                "reason": "当前采集仅含涨停/炸板/跌停事件集合，无完整非涨停题材成员映射",
            },
        })
    return sorted(out, key=lambda row: (-row["n_limit_up"], row["theme"]))


def _context_status(yyyymmdd: str) -> dict:
    """Separate collector availability, captured rows, and historical safety."""
    result = {}
    for dataset, serializer_name in (("announcement", "serialize_announcements"),
                                     ("hot_topic", "serialize_hot_topics")):
        try:
            from roubing_engine.collectors import f10_context
            collector_exists = callable(getattr(f10_context, serializer_name, None))
        except Exception:  # pragma: no cover - import failure is itself a gap
            collector_exists = False
        profile = partition_profile(dataset, yyyymmdd)
        path = WAREHOUSE / dataset / f"date={yyyymmdd}" / "part.parquet"
        historical_safe = None
        if path.exists() and profile.get("n_rows", 0):
            try:
                frame = pd.read_parquet(path, columns=["historical_safe"])
                historical_safe = bool(frame["historical_safe"].fillna(False).all()) \
                    if "historical_safe" in frame.columns else dataset == "announcement"
            except Exception:
                historical_safe = False
        result[dataset] = {
            "collector_exists": collector_exists,
            "captured_today": bool(profile.get("available")),
            "n_rows": profile.get("n_rows", 0),
            "historical_available": historical_safe,
            "status": ("READY" if collector_exists and profile.get("available") and historical_safe
                       else "PARTIAL_DATA" if collector_exists and profile.get("available")
                       else "BLOCKED_DATA"),
            "data_block": None if (collector_exists and profile.get("available") and historical_safe)
            else "当日公告/题材数据缺失，或当前题材快照不具备历史回放安全性",
        }
    return result


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


def _direction_feedback(previous_feedback: dict, yyyymmdd: str) -> dict[str, dict]:
    """Aggregate adjacent-day buyer feedback into direction-scoped facts."""
    if not previous_feedback.get("available"):
        return {}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in previous_feedback.get("rows") or []:
        theme = canonical_theme(_clean(row.get("previous_reason")), yyyymmdd)[0] or "(未标注)"
        grouped[theme].append(row)
    out: dict[str, dict] = {}
    for theme, rows in grouped.items():
        known = [row.get("today_ret_pct") for row in rows
                 if row.get("today_ret_pct") is not None]
        out[theme] = {
            "fact_id": fact_id(yyyymmdd, "DIRBUY", theme),
            "available": bool(known),
            "previous_trade_date": previous_feedback.get("previous_trade_date"),
            "n_samples": len(rows),
            "n_known_returns": len(known),
            "n_positive_feedback": sum(1 for value in known if value > 0),
            "n_negative_feedback": sum(1 for value in known if value < 0),
            "n_flat_feedback": sum(1 for value in known if value == 0),
            "n_continue_limit_up": sum(
                1 for row in rows if row.get("today_limit_status") == "limit_up"),
            "n_broken_today": sum(
                1 for row in rows if row.get("today_limit_status") == "broken"),
            "rows": rows,
        }
    return out


def compile_day(yyyymmdd: str) -> dict:
    uni = _read("universe", yyyymmdd)
    if uni.empty:
        return {"trade_date": yyyymmdd, "available": False, "reason": "no universe partition"}

    up = uni[uni["status"] == "limit_up"]
    down = uni[uni["status"] == "limit_down"]
    broken = uni[uni["status"] == "broken"]

    daily_market, daily_returns = _daily_market_facts(yyyymmdd)
    breadth = {
        "fact_id": fact_id(yyyymmdd, "ENV", "MARKET_BREADTH"),
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
    ladder_fact_id = fact_id(yyyymmdd, "ENV", "LIMIT_LADDER")

    # Theme aliases are merged only when an evidence-backed registry says so.
    up = up.copy()
    up["_canonical_theme"] = up["reason"].map(
        lambda raw: canonical_theme(raw, yyyymmdd)[0])
    themes = []
    for reason, g in up.groupby("_canonical_theme", dropna=False):
        theme_name = _clean(reason) or "(未标注)"
        direction_fact_id = fact_id(yyyymmdd, "DIR", theme_name)
        codes = []
        for _, r in g.iterrows():
            code = _clean(r.get("thscode"))
            codes.append({
                "fact_id": fact_id(yyyymmdd, "STOCK", str(code)),
                "direction_fact_id": direction_fact_id,
                "thscode": code,
                "name": _clean(r.get("name")),
                "event_status": "limit_up",
                "theme": theme_name,
                "raw_theme": _clean(r.get("reason")),
                "sub_direction": _clean(r.get("limit_reason_extra")),
                "board_level": _clean(r.get("board_level")),
                "highest_board_level": _clean(r.get("highest_board_level")),
                "consecutive_limit_days": _clean(r.get("consecutive_limit_days")),
                "limit_time": _clean(r.get("limit_time")),
                "seal_amount": _clean(r.get("seal_amount")),
                "reason_extra": _clean(r.get("limit_reason_extra")),
            })
        boards = [c["board_level"] for c in codes if c["board_level"] is not None]
        themes.append({
            "fact_id": direction_fact_id,
            "reason": theme_name,
            "raw_reasons": sorted({_clean(x) or "(未标注)" for x in g["reason"].tolist()}),
            "normalization": canonical_theme(_clean(g.iloc[0].get("reason")), yyyymmdd)[1],
            "n_limit_up": len(codes),
            "max_board": int(max(boards)) if boards else 0,
            "n_first_board": sum(1 for c in codes if c["board_level"] == 1),
            "codes": sorted(codes, key=lambda c: (-(c["board_level"] or 0),
                                                  c["limit_time"] or "99")),
        })
    themes.sort(key=lambda t: (-t["max_board"], -t["n_limit_up"]))

    failed_observations = []
    for _, record in pd.concat([broken, down], ignore_index=True).iterrows():
        code = _clean(record.get("thscode"))
        theme_name = canonical_theme(_clean(record.get("reason")), yyyymmdd)[0] or "(未标注)"
        failed_observations.append({
            "fact_id": fact_id(yyyymmdd, "STOCK", str(code)),
            "direction_fact_id": fact_id(yyyymmdd, "DIR", theme_name),
            "thscode": code,
            "name": _clean(record.get("name")),
            "status": _clean(record.get("status")),
            "raw_reason": _clean(record.get("reason")),
            "theme": theme_name,
            "sub_direction": _clean(record.get("limit_reason_extra")),
            "board_level": _clean(record.get("board_level")),
            "highest_board_level": _clean(record.get("highest_board_level")),
            "consecutive_limit_days": _clean(record.get("consecutive_limit_days")),
            "limit_time": _clean(record.get("limit_time")),
            "seal_amount": _clean(record.get("seal_amount")),
            "broken_count": _clean(record.get("broken_count")),
            "note": "失败观察事实；主动/被动原因未知",
        })

    previous_feedback = _prior_strong_feedback(
        yyyymmdd, daily_returns, uni, daily_market.get("previous_trade_date"))
    feedback_by_direction = _direction_feedback(previous_feedback, yyyymmdd)

    direction_facts = _direction_facts(uni, yyyymmdd)
    theme_by_name = {item["reason"]: item for item in themes}
    direction_state_facts = []
    for row in direction_facts:
        theme_name = row["theme"]
        theme_row = theme_by_name.get(theme_name, {})
        direction_state_facts.append({
            "fact_id": fact_id(yyyymmdd, "DIR", theme_name),
            "theme": theme_name,
            "event_counts": {
                "limit_up": row["n_limit_up"],
                "broken": row["n_broken"],
                "limit_down": row["n_limit_down"],
            },
            "ladder_distribution": row["ladder_distribution"],
            "max_board": theme_row.get("max_board", 0),
            "n_first_board": theme_row.get("n_first_board", 0),
            "opening_match_coverage": row["opening_match_coverage"],
            "turnover": row["turnover"],
            "diffusion": row["diffusion"],
            "previous_buyer_feedback": feedback_by_direction.get(theme_name, {
                "fact_id": fact_id(yyyymmdd, "DIRBUY", theme_name),
                "available": False,
                "previous_trade_date": previous_feedback.get("previous_trade_date"),
                "n_samples": 0,
                "reason": ("no adjacent-day buyer sample for this exact canonical direction"
                           if previous_feedback.get("available") else
                           previous_feedback.get("reason", "previous buyer feedback unavailable")),
                "rows": [],
            }),
            "stock_fact_ids": [item["fact_id"] for item in theme_row.get("codes", [])],
        })

    # Completeness is a coverage profile, not just a partition-exists boolean.
    have = {ds: partition_profile(ds, yyyymmdd)
            for ds in ("universe", "auction_point", "opening_match", "minute_bar", "trade_tick",
                       "announcement", "hot_topic")}

    context_data = _context_status(yyyymmdd)
    environment_facts = [
        {
            "fact_id": breadth["fact_id"],
            "fact_type": "MARKET_BREADTH",
            "status": "AVAILABLE" if daily_market.get("available") else "PARTIAL_DATA",
            "value": breadth,
        },
        {
            "fact_id": ladder_fact_id,
            "fact_type": "LIMIT_LADDER",
            "status": "AVAILABLE",
            "value": {"distribution": ladder_dist, "max_board": max_board},
        },
        {
            "fact_id": fact_id(yyyymmdd, "ENV", "PREVIOUS_BUYER_FEEDBACK"),
            "fact_type": "PREVIOUS_BUYER_FEEDBACK",
            "status": "AVAILABLE" if previous_feedback.get("available") else "BLOCKED_DATA",
            "value": previous_feedback,
        },
        {
            "fact_id": fact_id(yyyymmdd, "ENV", "CONTEXT_DATA"),
            "fact_type": "CONTEXT_DATA",
            "status": "AVAILABLE" if any(
                item.get("status") == "READY" for item in context_data.values()
            ) else "BLOCKED_DATA",
            "value": context_data,
        },
    ]

    return {
        "trade_date": yyyymmdd,
        "available": True,
        "as_of": f"{yyyymmdd} CLOSE",
        "source": "eltdx",
        "market_breadth": breadth,
        "ladder_distribution": ladder_dist,
        "ladder_fact_id": ladder_fact_id,
        "max_board": max_board,
        "environment_facts": environment_facts,
        "themes": themes,
        "failed_observations": failed_observations,
        "direction_facts": direction_facts,
        "direction_state_facts": direction_state_facts,
        "context_data": context_data,
        "previous_buyer_feedback": previous_feedback,
        "data_completeness": have,
        "theme_registry_policy": "evidence-backed aliases only; unknown reasons remain separate",
        "theme_hierarchy": hierarchy_for(
            [item.get("theme") for item in direction_state_facts if item.get("theme")],
            yyyymmdd),
        "theme_boundary_contract": {
            "parent_theme_is_context_only": True,
            "executable_merge_requires_explicit_registry_alias": True,
            "ai_semantic_merge_forbidden": True,
        },
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
