"""Assemble close-review evidence without inventing universal exit thresholds.

"该强不强" and role replacement are comparisons against the frozen prior
task, event order, direction response and real competitors.  They cannot be
reduced to +3%, MA5, or a fixed relative-return gap.
"""
from __future__ import annotations

from roubing_engine.features.stock_features import features_for


def exit_signals(thscode: str, as_of: str, role: str | None = None,
                 theme_peers: list[str] | None = None,
                 platform_high: float | None = None,
                 plan_candidate: dict | None = None) -> dict:
    codes = list(dict.fromkeys([thscode] + (theme_peers or [])))
    feats = features_for(codes, as_of)
    own = feats.get(thscode, {})
    if not own.get("available"):
        return {"available": False, "status": "BLOCKED_DATA"}

    peers = []
    for code in theme_peers or []:
        peer = feats.get(code, {})
        if peer.get("available"):
            peers.append({
                "thscode": code,
                "ret_today_pct": peer.get("ret_today_pct"),
                "last_close": peer.get("last_close"),
            })

    frozen = plan_candidate or {}
    plan_available = bool(frozen.get("tomorrow_must_do") or frozen.get("failure_signals"))
    return {
        "available": True,
        "status": "READY_FOR_CLOSE_REVIEW" if plan_available else "BLOCKED_METHOD",
        "thscode": thscode,
        "as_of": as_of,
        "frozen_role": frozen.get("role", role),
        "frozen_tasks": frozen.get("tomorrow_must_do") or [],
        "frozen_failure_signals": frozen.get("failure_signals") or [],
        "frozen_cancel_if": frozen.get("cancel_if") or [],
        "own_close_facts": {
            "ret_today_pct": own.get("ret_today_pct"),
            "last_close": own.get("last_close"),
            "above_ma5": own.get("above_ma5"),
            "close_below_predeclared_level": (
                bool(platform_high and own.get("last_close") < platform_high)
                if own.get("last_close") is not None else None),
        },
        "competitor_close_facts": peers,
        "decision": "AI_OR_HUMAN_MUST_COMPARE_FROZEN_TASK_AND_EVENT_ORDER",
        "data_blocks": [] if plan_available else [
            "缺盘前冻结的角色任务，不能定义该强不强或角色替代"],
        "discipline": (
            "不使用固定涨幅、MA5或固定相对涨幅差自动退出；MA与预标压力仅作为事实。"),
    }
