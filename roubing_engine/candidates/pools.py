"""Deterministic, look-ahead-clean candidate-source enumerators.

These functions create *observation pools*, never final selections.  They use
node-specific source rules and expose raw relational facts.  No fixed score,
cross-role ranking, or arbitrary top-N cut is applied here.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from functools import lru_cache

import pandas as pd

from roubing_engine.config import PROJECT_ROOT, WAREHOUSE
from roubing_engine.rules.themes import canonical_theme, same_theme
from roubing_engine.warehouse.daily_loader import DAILY_BAR
from roubing_engine.warehouse.timebox import iso_at


def _date_key(date: str) -> str:
    return date.replace("-", "")


def _iso_date(date: str) -> str:
    raw = _date_key(date)
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def _clean(value):
    if value is None or (not isinstance(value, (str, bytes)) and pd.isna(value)):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:  # noqa: BLE001
            pass
    return value


def _universe(date: str) -> pd.DataFrame:
    p = WAREHOUSE / "universe" / f"date={_date_key(date)}" / "part.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def _universe_dates(as_of: str) -> list[str]:
    base = WAREHOUSE / "universe"
    cutoff = _date_key(as_of)
    if not base.exists():
        return []
    return sorted(
        p.name.split("=", 1)[1] for p in base.glob("date=*")
        if p.name.split("=", 1)[1] <= cutoff
    )


@lru_cache(maxsize=32)
def _history_asof(as_of: str) -> pd.DataFrame:
    frames = [_universe(d) for d in _universe_dates(as_of)]
    frames = [frame for frame in frames if not frame.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _daily_window(as_of: str, codes: list[str] | None = None) -> pd.DataFrame:
    if not DAILY_BAR.exists():
        return pd.DataFrame()
    end = dt.date.fromisoformat(_iso_date(as_of))
    start = (end - dt.timedelta(days=14)).strftime("%Y%m%d")
    filters = [("trade_date", ">=", start), ("trade_date", "<=", _date_key(as_of))]
    if codes:
        filters.append(("thscode", "in", set(codes)))
    columns = ["thscode", "trade_date", "open", "high", "low", "close", "volume", "turnover"]
    return pd.read_parquet(DAILY_BAR, columns=columns, filters=filters)


@lru_cache(maxsize=32)
def recent_universe_coverage(as_of: str) -> dict:
    """Whether current and immediately previous trading-day rosters exist."""
    frame = _daily_window(as_of)
    dates = sorted(str(value) for value in frame["trade_date"].dropna().unique()) if not frame.empty else []
    cutoff = _date_key(as_of)
    prior_daily = [date for date in dates if date < cutoff]
    expected_previous = prior_daily[-1] if prior_daily else None
    captured = _universe_dates(as_of)
    captured_prior = [date for date in captured if date < cutoff]
    actual_previous = captured_prior[-1] if captured_prior else None
    current_available = cutoff in captured
    return {
        "current_available": current_available,
        "expected_previous_trade_date": expected_previous,
        "captured_previous_trade_date": actual_previous,
        "continuous_recent": bool(
            current_available and expected_previous and actual_previous == expected_previous),
    }


def _latest_names(as_of: str) -> dict[str, str | None]:
    history = _history_asof(as_of)
    if history.empty:
        return {}
    latest = history.sort_values("trade_date").drop_duplicates("thscode", keep="last")
    return dict(zip(latest["thscode"], latest.get("name")))


def _daily_facts(as_of: str, codes: list[str] | None = None) -> dict[str, dict]:
    frame = _daily_window(as_of, codes)
    if frame.empty:
        return {}
    out: dict[str, dict] = {}
    for code, group in frame.groupby("thscode"):
        group = group.sort_values("trade_date")
        if len(group) < 2:
            continue
        today, previous = group.iloc[-1], group.iloc[-2]
        if str(today["trade_date"]) != _date_key(as_of):
            continue
        prev_close = float(previous["close"])
        close = float(today["close"])
        out[str(code)] = {
            "trade_date": str(today["trade_date"]),
            "open": float(today["open"]),
            "high": float(today["high"]),
            "low": float(today["low"]),
            "close": close,
            "prev_close": prev_close,
            "prev_low": float(previous["low"]),
            "turnover": float(today["turnover"]) if pd.notna(today["turnover"]) else None,
            "ret_today_pct": round((close / prev_close - 1) * 100, 2) if prev_close else None,
            "closed_not_down": bool(close >= prev_close),
            "held_previous_low": bool(float(today["low"]) >= float(previous["low"])),
            "closed_above_open": bool(close >= float(today["open"])),
        }
    return out


def _row(record, *, include_reason: str, source_pool: str,
         daily: dict | None = None) -> dict:
    raw_reason = record.get("reason") if hasattr(record, "get") else None
    theme, meta = canonical_theme(raw_reason)
    return {
        "thscode": _clean(record.get("thscode")),
        "name": _clean(record.get("name")),
        "theme": theme,
        "raw_reason": raw_reason,
        "theme_normalization": meta,
        "status": _clean(record.get("status")),
        "board_level": _clean(record.get("board_level")),
        "highest_board_level": _clean(record.get("highest_board_level")),
        "consecutive_limit_days": _clean(record.get("consecutive_limit_days")),
        "limit_reason_extra": _clean(record.get("limit_reason_extra")),
        "seal_amount": _clean(record.get("seal_amount")),
        "limit_time": _clean(record.get("limit_time")),
        "source_pool": source_pool,
        "include_reason": include_reason,
        "daily": daily,
    }


def _dedupe(rows: list[dict]) -> list[dict]:
    out: dict[str, dict] = {}
    for row in rows:
        code = row.get("thscode")
        if not code:
            continue
        if code not in out:
            out[code] = row
            continue
        old = out[code]
        old["source_pool"] = "+".join(dict.fromkeys(
            f"{old.get('source_pool', '')}+{row.get('source_pool', '')}".strip("+").split("+")
        ))
        old["include_reason"] = f"{old.get('include_reason')}; {row.get('include_reason')}"
        if not old.get("daily") and row.get("daily"):
            old["daily"] = row["daily"]
    return list(out.values())


def attach_context(rows: list[dict], as_of: str) -> list[dict]:
    """Attach only announcement/topic facts available by T close."""
    if not rows:
        return rows
    codes = {row.get("thscode") for row in rows if row.get("thscode")}
    cutoff = pd.Timestamp(iso_at(as_of, 15 * 3600))
    grouped: dict[str, dict[str, list[dict]]] = {
        code: {"announcements": [], "hot_topics": []} for code in codes
    }
    for dataset, field in (("announcement", "announcements"), ("hot_topic", "hot_topics")):
        path = WAREHOUSE / dataset / f"date={_date_key(as_of)}" / "part.parquet"
        if not path.exists():
            continue
        frame = pd.read_parquet(path)
        if "thscode" not in frame or "available_at" not in frame:
            continue
        frame = frame[frame["thscode"].isin(codes)].copy()
        available = pd.to_datetime(frame["available_at"], utc=True, errors="coerce")
        frame = frame[available <= cutoff.tz_convert("UTC")]
        for code, group in frame.groupby("thscode"):
            keep = [column for column in (
                "title", "announcement_type", "url", "publisher_source", "available_at",
                "topic_id", "topic_name", "topic_detail", "historical_safe", "source",
            ) if column in group.columns]
            grouped[str(code)][field] = group[keep].to_dict("records")
    out = []
    for row in rows:
        copy = dict(row)
        copy["context"] = grouped.get(row.get("thscode"), {"announcements": [], "hot_topics": []})
        out.append(copy)
    return out


def first_board_pool(anchor_date: str, theme: str | None = None) -> list[dict]:
    df = _universe(anchor_date)
    if df.empty:
        return []
    pool = df[(df["status"] == "limit_up") & (df["board_level"] == 1)]
    if theme:
        pool = pool[pool["reason"].map(lambda raw: same_theme(raw, theme))]
    daily = _daily_facts(anchor_date, pool["thscode"].astype(str).tolist())
    return [_row(r, include_reason="节点起算日首板", source_pool="anchor_first_board",
                 daily=daily.get(str(r.get("thscode")))) for _, r in pool.iterrows()]


def high_board_pool(date: str, min_board: int = 2) -> list[dict]:
    df = _universe(date)
    if df.empty:
        return []
    pool = df[(df["status"] == "limit_up") & (df["board_level"] >= min_board)]
    daily = _daily_facts(date, pool["thscode"].astype(str).tolist())
    return [_row(r, include_reason="当日连板高度候选", source_pool="current_high_board",
                 daily=daily.get(str(r.get("thscode"))))
            for _, r in pool.sort_values("board_level", ascending=False).iterrows()]


def emotion_breakout_pool(anchor_date: str) -> list[dict]:
    """G1: only candidates whose board height actually exceeds prior captured height."""
    current = _universe(anchor_date)
    prior_dates = [d for d in _universe_dates(anchor_date) if d < _date_key(anchor_date)]
    if current.empty or not prior_dates:
        return []
    prior_max = 0
    for date in prior_dates:
        frame = _universe(date)
        up = frame[frame["status"] == "limit_up"] if not frame.empty else frame
        if not up.empty and up["board_level"].notna().any():
            prior_max = max(prior_max, int(up["board_level"].max()))
    pool = current[(current["status"] == "limit_up") & (current["board_level"] > prior_max)]
    daily = _daily_facts(anchor_date, pool["thscode"].astype(str).tolist())
    rows = []
    for _, record in pool.iterrows():
        row = _row(record, include_reason=f"板位超过此前已捕获高度{prior_max}",
                   source_pool="emotion_height_breakout",
                   daily=daily.get(str(record.get("thscode"))))
        row["previous_captured_max_board"] = prior_max
        rows.append(row)
    return rows


def starting_cohort_pool(anchor_date: str, as_of: str,
                         theme: str | None = None) -> list[dict]:
    """G8: retain the whole same-start cohort; later survival is a fact, not a pre-filter."""
    start = _universe(anchor_date)
    if start.empty:
        return []
    seed = start[start["status"] == "limit_up"]
    if theme:
        seed = seed[seed["reason"].map(lambda raw: same_theme(raw, theme))]
    daily = _daily_facts(as_of, seed["thscode"].astype(str).tolist())
    return [_row(r, include_reason="同一起算日涨停队列，保留同期失败者",
                 source_pool="same_start_cohort", daily=daily.get(str(r.get("thscode"))))
            for _, r in seed.iterrows()]


def theme_observation_pool(as_of: str, theme: str) -> list[dict]:
    """All stocks linked to a direction in captured history, including non-limit stocks today."""
    history = _history_asof(as_of)
    if history.empty or not theme:
        return []
    linked = history[history["reason"].map(lambda raw: same_theme(raw, theme))]
    linked = linked.sort_values("trade_date").drop_duplicates("thscode", keep="last")
    daily = _daily_facts(as_of, linked["thscode"].astype(str).tolist())
    rows = []
    for _, record in linked.iterrows():
        code = str(record.get("thscode"))
        rows.append(_row(
            record,
            include_reason="历史涨停/炸板事实曾与该方向直接关联；今日不要求涨停",
            source_pool="historical_theme_member",
            daily=daily.get(code),
        ))
    return rows


def prior_role_pool(as_of: str, theme: str | None = None) -> list[dict]:
    from roubing_engine.state.ledger import load_prev_ledger
    rows: list[dict] = []
    entry = load_prev_ledger(_date_key(as_of))
    if not entry:
        return rows
    role_date = entry.get("trade_date")
    for role in entry.get("roles", []):
        if theme and not same_theme(role.get("theme"), theme):
            continue
        rows.append({
            "thscode": role.get("thscode"), "name": role.get("name"),
            "theme": role.get("theme"), "raw_reason": role.get("theme"),
            "status": None, "board_level": None, "highest_board_level": None,
            "consecutive_limit_days": None, "limit_reason_extra": None,
            "seal_amount": None, "limit_time": None,
            "source_pool": "prior_role_ledger",
            "include_reason": f"相邻前日账本角色={role.get('role')}",
            "daily": None,
            "prior_role": role.get("role"), "role_date": role_date,
        })
    facts = _daily_facts(as_of, [r["thscode"] for r in rows if r.get("thscode")])
    for row in rows:
        row["daily"] = facts.get(row.get("thscode"))
    return _dedupe(rows)


def direction_role_pool(as_of: str, theme: str) -> list[dict]:
    return _dedupe(theme_observation_pool(as_of, theme) + prior_role_pool(as_of, theme))


def explicit_candidates(node: dict, as_of: str) -> list[dict]:
    ids = [str(code) for code in (node.get("candidate_ids") or []) if code]
    if not ids:
        return []
    today = _universe(as_of)
    latest = _history_asof(as_of)
    latest = latest.sort_values("trade_date").drop_duplicates("thscode", keep="last") if not latest.empty else latest
    records = {str(r.get("thscode")): r for _, r in latest.iterrows()} if not latest.empty else {}
    daily = _daily_facts(as_of, ids)
    names = _latest_names(as_of)
    out = []
    for code in ids:
        record = records.get(code, {"thscode": code, "name": names.get(code), "reason": node.get("theme")})
        out.append(_row(record, include_reason="Stage B 单票节点明确指定",
                        source_pool="node_candidate_id", daily=daily.get(code)))
    return out


def panic_divergence_pool(as_of: str, theme: str | None = None) -> list[dict]:
    """G11 broad fact pool: stocks that stopped following the daily decline.

    This is not a buy rule.  It preserves every stock satisfying a relational
    fact (not down on close or holding the prior low) and leaves role, active
    leadership, index resonance and cancellation to Stage C/D.
    """
    facts = _daily_facts(as_of)
    history = _history_asof(as_of)
    latest = history.sort_values("trade_date").drop_duplicates("thscode", keep="last") if not history.empty else history
    records = {str(r.get("thscode")): r for _, r in latest.iterrows()} if not latest.empty else {}
    names = _latest_names(as_of)
    out = []
    for code, daily in facts.items():
        if not (daily["closed_not_down"] or daily["held_previous_low"]):
            continue
        record = records.get(code, {"thscode": code, "name": names.get(code), "reason": None})
        if theme and not same_theme(record.get("reason"), theme):
            continue
        out.append(_row(
            record,
            include_reason="相对前一交易日未继续下跌或守住前低；仅是底背离观察事实",
            source_pool="panic_relative_resilience",
            daily=daily,
        ))
    return out


# Backward-compatible names used by older scripts.
def limit_up_pool(date: str, theme: str | None = None) -> list[dict]:
    df = _universe(date)
    if df.empty:
        return []
    pool = df[df["status"] == "limit_up"]
    if theme:
        pool = pool[pool["reason"].map(lambda raw: same_theme(raw, theme))]
    daily = _daily_facts(date, pool["thscode"].astype(str).tolist())
    return [_row(r, include_reason="当日涨停事实", source_pool="limit_up",
                 daily=daily.get(str(r.get("thscode")))) for _, r in pool.iterrows()]


def broken_pool(date: str) -> list[dict]:
    df = _universe(date)
    if df.empty:
        return []
    pool = df[df["status"] == "broken"]
    daily = _daily_facts(date, pool["thscode"].astype(str).tolist())
    return [_row(r, include_reason="当日炸板事实，主动/被动未知", source_pool="broken",
                 daily=daily.get(str(r.get("thscode")))) for _, r in pool.iterrows()]


def survivors_since(anchor_date: str, as_of: str) -> list[dict]:
    return starting_cohort_pool(anchor_date, as_of)
