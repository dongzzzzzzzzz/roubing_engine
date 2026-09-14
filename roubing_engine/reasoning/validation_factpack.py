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
    # These are raw unmatched-order observations.  They are deliberately
    # exposed as a time-ordered snapshot, not translated into a withdrawal or
    # aggressor conclusion: matched trades alone cannot identify who cancelled
    # or which side initiated the change.
    def column_values(name):
        return [_clean(v) for v in df[name].tolist()] if name in df.columns else []

    unmatched = column_values("unmatched_volume")
    unmatched_signed = column_values("unmatched_signed_raw")
    unmatched_direction = column_values("unmatched_direction_raw")
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
        "unmatched_first_observed_vol": unmatched[0] if unmatched else None,
        "unmatched_last_observed_vol": unmatched[-1] if unmatched else None,
        "unmatched_peak_vol": max(unmatched) if unmatched else None,
        "unmatched_signed_first_raw": unmatched_signed[0] if unmatched_signed else None,
        "unmatched_signed_last_raw": unmatched_signed[-1] if unmatched_signed else None,
        "unmatched_direction_first_raw": unmatched_direction[0] if unmatched_direction else None,
        "unmatched_direction_last_raw": unmatched_direction[-1] if unmatched_direction else None,
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


def _record(leaf: dict, op_by: dict, auc: pd.DataFrame, mn: pd.DataFrame,
            tr: pd.DataFrame, snapshot: str, previous_close: dict[str, float]) -> dict:
    code = leaf.get("thscode")
    oprow = op_by.get(code)
    open_price = None
    pre_close = previous_close.get(code)
    open_change = None
    if oprow is not None:
        open_price = _clean(oprow.get("open_price")) or _clean(oprow.get("price"))
        pre_close = _clean(oprow.get("pre_close_price")) or pre_close
        open_change = _clean(oprow.get("open_change_pct"))
        if open_change is None and open_price is not None and pre_close:
            open_change = round((float(open_price) / float(pre_close) - 1) * 100, 2)
    rec = {
        "thscode": code,
        "leaf_id": leaf.get("leaf_id"),
        "tier": leaf.get("tier"),
        "path_kind": leaf.get("path_kind"),
        "task_id": leaf.get("task_id"),
        "node_id": leaf.get("node_id"),
        "anchor_date": leaf.get("anchor_date"),
        "stock_start_date": leaf.get("stock_start_date"),
        "current_function": leaf.get("current_function"),
        "entry_event": leaf.get("entry_event") or [],
        "exit_conditions": leaf.get("exit_conditions") or [],
        "task_to_complete": leaf.get("task_to_complete"),
        "auction_conditions": leaf.get("auction_conditions") or [],
        "open_conditions": leaf.get("open_conditions") or [],
        "downgrade_conditions": leaf.get("downgrade_conditions") or [],
        "direct_fail_conditions": leaf.get("direct_fail_conditions") or [],
        "auction_open_change_pct": open_change,
        "auction_open_change_text": (
            f"{float(open_change):+.2f}%" if open_change is not None else None),
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
    return rec


def _relative_auction_contract(records: list[dict], snapshot: str) -> dict:
    if snapshot != "AUCTION_0925" or len(records) != 2:
        return {"status": "NOT_APPLICABLE", "stronger_code": None,
                "weaker_code": None, "comparison_text": "当前快照不需要双叶子竞价比较"}
    if any(row.get("auction_open_change_pct") is None for row in records):
        return {"status": "DATA_INSUFFICIENT", "stronger_code": None,
                "weaker_code": None, "comparison_text": "竞价开盘变动数据不足，无法判断"}
    stronger, weaker = sorted(
        records, key=lambda row: float(row["auction_open_change_pct"]), reverse=True)
    spread = float(stronger["auction_open_change_pct"]) - float(weaker["auction_open_change_pct"])
    return {
        "status": "AVAILABLE",
        "stronger_code": stronger.get("thscode"),
        "weaker_code": weaker.get("thscode"),
        "comparison_text": (
            f"{stronger.get('thscode')} {stronger.get('auction_open_change_text')} 强于 "
            f"{weaker.get('thscode')} {weaker.get('auction_open_change_text')}，"
            f"相差约 {spread:.2f} 个百分点"),
    }


def build(executable_plan: dict, tplus1: str, client=None,
          snapshot: str = "OPEN_0935", prior_result: dict | None = None) -> dict:
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
    from roubing_engine.features.index_ctx import intraday_market_context
    market_context = intraday_market_context(tplus1, snapshot)

    from roubing_engine.reasoning.condition_tree import expected_action_codes
    from roubing_engine.reasoning.day_factpack import _previous_close_map
    previous_close = _previous_close_map(yyyymmdd)
    plan = executable_plan.get("action_plan") or {}
    leaf_by_code = {
        leaf.get("thscode"): leaf for leaf in (plan.get("primary"), plan.get("backup")) if leaf
    }
    action_codes = expected_action_codes(executable_plan, snapshot, prior_result)
    action_leaf_facts = [
        _record(leaf_by_code[code], op_by, auc, mn, tr, snapshot, previous_close)
        for code in action_codes if code in leaf_by_code
    ]
    context_leaves = [{
        "thscode": code, "leaf_id": f"VALIDATION-{code}", "tier": "VALIDATION_ONLY",
        "task_to_complete": "验证方向/分支是否响应，不具备动作资格",
        "auction_conditions": [], "open_conditions": [],
        "downgrade_conditions": [], "direct_fail_conditions": [],
    } for code in plan.get("validation_objects") or []]
    validation_context_facts = [
        _record(leaf, op_by, auc, mn, tr, snapshot, previous_close) for leaf in context_leaves
    ]
    path_validation_contexts = []
    seen_context_tasks = set()
    for action_leaf in (plan.get("primary"), plan.get("backup")):
        if not action_leaf or not action_leaf.get("path_kind") \
                or action_leaf.get("task_id") in seen_context_tasks:
            continue
        seen_context_tasks.add(action_leaf.get("task_id"))
        path_context_leaves = [{
            "thscode": code,
            "leaf_id": f"VALIDATION-{action_leaf.get('task_id')}-{code}",
            "tier": "VALIDATION_ONLY", "path_kind": action_leaf.get("path_kind"),
            "task_id": action_leaf.get("task_id"), "node_id": action_leaf.get("node_id"),
            "anchor_date": action_leaf.get("anchor_date"),
            "task_to_complete": "只验证该叶子所属路径/分支响应，不具备动作资格",
            "auction_conditions": [], "open_conditions": [],
            "downgrade_conditions": [], "direct_fail_conditions": [],
        } for code in action_leaf.get("path_validation_objects") or []]
        path_validation_contexts.append({
            "path_kind": action_leaf.get("path_kind"),
            "task_id": action_leaf.get("task_id"),
            "node_id": action_leaf.get("node_id"),
            "validation_objects": [leaf["thscode"] for leaf in path_context_leaves],
            "facts": [_record(leaf, op_by, auc, mn, tr, snapshot, previous_close)
                      for leaf in path_context_leaves],
        })

    facts = {
        "tplus1": tplus1,
        "snapshot": snapshot,
        "as_of": snapshot_as_of(tplus1, snapshot),
        "action_leaf_facts": action_leaf_facts,
        "relative_auction_contract": _relative_auction_contract(action_leaf_facts, snapshot),
        "validation_context_facts": validation_context_facts,
        "path_validation_contexts": path_validation_contexts,
        "prior_auction_result": prior_result if snapshot == "OPEN_0935" else None,
        "market_check_data": market_context,
        "execution_context": {
            "primary_path": executable_plan.get("primary_path") or {},
            "execution_task": executable_plan.get("execution_task") or {},
            "execution_tasks": executable_plan.get("execution_tasks") or [
                executable_plan.get("execution_task") or {}],
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
    rows = ((facts.get("action_leaf_facts") or [])
            + (facts.get("validation_context_facts") or [])
            + [row for context in facts.get("path_validation_contexts") or []
               for row in context.get("facts") or []])
    for index, candidate in enumerate(rows):
        auction = candidate.get("auction_summary") or {}
        last_auction = row_seconds({"time_label": auction.get("last_time")})
        if last_auction is not None and last_auction > SNAPSHOT_CUTOFFS["AUCTION_0925"]:
            problems.append(f"$.candidates[{index}].auction_summary: extends beyond 09:25")
        open5 = candidate.get("open_5min") or {}
        for point_index, point in enumerate(open5.get("path", [])):
            event = row_seconds({"time_label": point.get("t")})
            if event is not None and event > cutoff:
                problems.append(
                    f"$.snapshot_rows[{index}].open_5min.path[{point_index}]: future event")
    return problems


def validate_stage_d_result(result: dict, facts: dict) -> list[str]:
    """Hard semantic gates for Stage-D conclusions against frozen coverage."""
    problems: list[str] = []
    snapshot = facts.get("snapshot")
    market = facts.get("market_check_data") or {}
    if not market.get("available") and (result.get("market_check") or {}).get("index_held") is not None:
        problems.append("market_check.index_held: market snapshot is BLOCKED_DATA and must be null")
    trace = result.get("reasoning_trace") or {}
    if trace.get("step_order") != ["MARKET_AND_PATH", "EXECUTION_NODE", "ACTION_LEAVES"]:
        problems.append("reasoning_trace.step_order: 必须先环境/主路径，再执行节点，最后个股叶子")
    if not market.get("available") and (trace.get("market_and_path") or {}).get("status") != "DATA_INSUFFICIENT":
        problems.append("reasoning_trace.market_and_path: 缺指数/板块分时时必须 DATA_INSUFFICIENT")
    if not market.get("available") and "数据不足，无法判断" not in " ".join(
            (trace.get("market_and_path") or {}).get("observed") or []):
        problems.append("reasoning_trace.market_and_path: 数据缺失时必须明示‘数据不足，无法判断’")
    context = result.get("context_check") or {}
    if context.get("status") == "DATA_INSUFFICIENT" and "数据不足，无法判断" not in " ".join(
            context.get("observed") or []):
        problems.append("context_check: DATA_INSUFFICIENT 必须明示‘数据不足，无法判断’")
    for index, item in enumerate(result.get("path_context_checks") or []):
        if item.get("status") == "DATA_INSUFFICIENT" and "数据不足，无法判断" not in " ".join(
                item.get("observed") or []):
            problems.append(
                f"path_context_checks[{index}]: DATA_INSUFFICIENT 必须明示‘数据不足，无法判断’")
    expected_node = (facts.get("execution_context") or {}).get("execution_task") or {}
    actual_node = trace.get("execution_node") or {}
    for field in ("task_id", "task_type", "theme", "anchor_date"):
        if field in expected_node and actual_node.get(field) != expected_node.get(field):
            problems.append(f"reasoning_trace.execution_node.{field}: 与冻结执行节点不一致")
    expected_nodes = (facts.get("execution_context") or {}).get("execution_tasks") or []
    actual_nodes = trace.get("execution_nodes") or []
    expected_by_task = {item.get("task_id"): item for item in expected_nodes}
    actual_by_task = {item.get("task_id"): item for item in actual_nodes}
    if set(actual_by_task) != set(expected_by_task) or \
            len(actual_by_task) != len(actual_nodes) or len(expected_by_task) != len(expected_nodes):
        problems.append("reasoning_trace.execution_nodes: 必须完整逐项抄写所有冻结路径任务")
    else:
        for task_id, expected in expected_by_task.items():
            actual = actual_by_task.get(task_id) or {}
            for field in ("path_kind", "task_type", "theme", "node_id", "anchor_date"):
                if actual.get(field) != expected.get(field):
                    problems.append(
                        f"reasoning_trace.execution_nodes[{task_id}].{field}: 与冻结任务不一致")
    for index, candidate in enumerate(result.get("leaf_results", [])):
        facts_row = next((row for row in facts.get("action_leaf_facts", [])
                          if row.get("thscode") == candidate.get("thscode")), None)
        if not facts_row:
            continue
        for field in ("path_kind", "task_id", "node_id", "anchor_date", "stock_start_date",
                      "current_function", "entry_event", "exit_conditions"):
            if candidate.get(field) != facts_row.get(field):
                problems.append(f"leaf_results[{index}].{field}: 未原样引用冻结叶子来源/角色合同")
        coverage = facts_row.get("data_completeness") or {}
        expected_change_text = facts_row.get("auction_open_change_text")
        if expected_change_text and expected_change_text not in " ".join(candidate.get("observed") or []):
            problems.append(
                f"leaf_results[{index}].observed: 必须原样引用竞价涨跌幅 {expected_change_text}")
        if snapshot == "AUCTION_0925" and coverage.get("open_5min") == "NOT_IN_SNAPSHOT":
            missing_text = " ".join(candidate.get("observed") or []) + " " + str(
                candidate.get("vs_plan") or "") + " " + " ".join(candidate.get("reason") or [])
            if "数据不足，无法判断" not in missing_text:
                problems.append(
                    f"leaf_results[{index}]: 缺开盘五分钟时必须明示‘数据不足，无法判断’")
        if snapshot == "AUCTION_0925":
            if candidate.get("leaf_state") in {"MEETS_OPEN_TASK", "OPEN_TASK_FAILED"}:
                problems.append(f"leaf_results[{index}].leaf_state: 09:25 forbids open-five-minute conclusion")
        elif coverage.get("open_5min") != "AVAILABLE":
            if candidate.get("leaf_state") != "DATA_INSUFFICIENT":
                problems.append(f"leaf_results[{index}].leaf_state: open_5min coverage is {coverage.get('open_5min')}")
        if coverage.get("opening_match") != "AVAILABLE" and candidate.get("leaf_state") in {
            "MEETS_AUCTION_TASK", "NEEDS_OPEN_VALIDATION", "DOWNGRADED"
        }:
            problems.append(f"leaf_results[{index}].leaf_state: opening_match missing")
        if coverage.get("opening_auction") != "AVAILABLE" \
                and candidate.get("leaf_state") == "MEETS_AUCTION_TASK":
            problems.append(f"leaf_results[{index}].leaf_state: opening auction summary missing")
        if snapshot == "OPEN_0935" and coverage.get("first5m_activity") != "AVAILABLE":
            text = " ".join(candidate.get("observed") or []) + " " + str(candidate.get("vs_plan") or "")
            if any(word in text for word in ("主动带动", "主动增强", "主动买", "真实承接")):
                problems.append(f"leaf_results[{index}]: first5m_activity missing; cannot assert active/real support")
    expected_comparison = facts.get("relative_auction_contract") or {}
    actual_comparison = result.get("auction_pair_comparison") or {}
    for field in ("status", "stronger_code", "weaker_code", "comparison_text"):
        if actual_comparison.get(field) != expected_comparison.get(field):
            problems.append(f"auction_pair_comparison.{field}: 未原样引用冻结竞价比较合同")
    return problems
