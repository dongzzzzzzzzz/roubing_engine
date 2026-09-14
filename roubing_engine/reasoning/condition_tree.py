"""Hard state machine for the 09:25 -> 09:35 closed condition tree."""
from __future__ import annotations


AUCTION_PASS_STATES = {"MEETS_AUCTION_TASK", "NEEDS_OPEN_VALIDATION"}
AUCTION_STATES = AUCTION_PASS_STATES | {"DOWNGRADED", "DIRECT_FAIL", "DATA_INSUFFICIENT"}
OPEN_STATES = {"MEETS_OPEN_TASK", "OPEN_TASK_FAILED", "DATA_INSUFFICIENT"}


def terminal_no_action_result(validation_facts: dict) -> dict:
    """Return the only legal 09:35 result after 09:25 stopped.

    This branch contains no market judgement: once the frozen 09:25 condition
    tree has no action candidate, 09:35 is mechanically forbidden from opening
    a new selection.  Keeping it deterministic removes an unnecessary model
    call and makes reopening the candidate set impossible by construction.
    """
    if validation_facts.get("snapshot") != "OPEN_0935":
        raise ValueError("terminal no-action result is only valid for OPEN_0935")
    prior = validation_facts.get("prior_auction_result") or {}
    if prior.get("current_action_candidate"):
        raise ValueError("09:25 has an action candidate; open validation is required")

    context_rows = validation_facts.get("validation_context_facts") or []
    context_codes = [row.get("thscode") for row in context_rows if row.get("thscode")]
    if not context_codes:
        context_status = "NOT_REQUIRED"
        context_observed = ["09:25没有动作对象，09:35保持停止；没有验证对象需要判断。"]
    elif all(
        (row.get("data_completeness") or {}).get("open_5min") != "AVAILABLE"
        for row in context_rows
    ):
        context_status = "DATA_INSUFFICIENT"
        context_observed = [
            "09:25没有动作对象；验证对象缺少可用开盘五分钟数据，数据不足，无法判断；且不得转成新候选。"
        ]
    else:
        context_status = "UNRESOLVED"
        context_observed = [
            "09:25没有动作对象；验证对象即使有数据也只保留上下文，不得重开选股。"
        ]

    market = validation_facts.get("market_check_data") or {}
    market_note = (
        "指数/板块快照数据可用，但09:25已停止，09:35不得据此重新选票。"
        if market.get("available") else
        "指数/板块快照数据不足，数据不足，无法判断；且09:25已停止，09:35不得重新选票。"
    )
    unknowns = [] if market.get("available") else ["指数/板块分时数据不足。"]
    if context_status == "DATA_INSUFFICIENT":
        unknowns.append("验证对象缺少可用开盘五分钟数据。")
    execution = (validation_facts.get("execution_context") or {}).get("execution_task") or {}
    executions = (validation_facts.get("execution_context") or {}).get("execution_tasks") or [execution]
    path_context_checks = []
    for item in validation_facts.get("path_validation_contexts") or []:
        codes = item.get("validation_objects") or []
        rows = item.get("facts") or []
        if not codes:
            status = "NOT_REQUIRED"
            observed = ["该冻结路径没有额外验证对象。"]
        elif not market.get("available") or all(
                (row.get("data_completeness") or {}).get("open_5min") != "AVAILABLE"
                for row in rows):
            status = "DATA_INSUFFICIENT"
            observed = ["路径验证所需指数/板块或开盘五分钟数据不足，数据不足，无法判断。"]
        else:
            status = "UNRESOLVED"
            observed = ["09:25已停止；只记录路径上下文，不得据此重开动作叶子。"]
        path_context_checks.append({
            "path_kind": item.get("path_kind"), "task_id": item.get("task_id"),
            "node_id": item.get("node_id"), "validation_objects": codes,
            "status": status, "observed": observed,
        })
    return {
        "tplus1": validation_facts.get("tplus1"),
        "snapshot": "OPEN_0935",
        "as_of": validation_facts.get("as_of"),
        "market_check": {"index_held": None, "note": market_note},
        "reasoning_trace": {
            "step_order": ["MARKET_AND_PATH", "EXECUTION_NODE", "ACTION_LEAVES"],
            "market_and_path": {
                "status": "SUPPORTED" if market.get("available") else "DATA_INSUFFICIENT",
                "observed": [market_note],
            },
            "execution_node": {
                "status": "SUPPORTED" if execution.get("task_id") else "DATA_INSUFFICIENT",
                "task_id": execution.get("task_id"),
                "task_type": execution.get("task_type"),
                "theme": execution.get("theme"),
                "anchor_date": execution.get("anchor_date"),
                "observed": [
                    "09:25条件树已经停止；09:35不得重开该节点或补入新动作对象。"
                ],
            },
            "execution_nodes": [{
                "path_kind": item.get("path_kind"),
                "status": "SUPPORTED" if item.get("task_id") else "DATA_INSUFFICIENT",
                "task_id": item.get("task_id"), "task_type": item.get("task_type"),
                "theme": item.get("theme"), "node_id": item.get("node_id"),
                "anchor_date": item.get("anchor_date"),
                "observed": ["09:25已停止；该冻结节点不得在09:35重新打开股票选择。"],
            } for item in executions],
        },
        "auction_pair_comparison": validation_facts.get("relative_auction_contract") or {
            "status": "NOT_APPLICABLE", "stronger_code": None, "weaker_code": None,
            "comparison_text": "当前快照不需要双叶子竞价比较",
        },
        "context_check": {
            "validation_objects": context_codes,
            "status": context_status,
            "observed": context_observed,
        },
        "path_context_checks": path_context_checks,
        "leaf_results": [],
        "condition_tree_hit": {
            "branch": "NO_CANDIDATE",
            "primary_state": None,
            "backup_state": None,
            "reasoning": [
                "09:25没有唯一动作对象并已停止。",
                "09:35只能验证09:25传入对象，因此机械保持NO_ACTION，不读取意外强票。",
            ],
        },
        "current_action_candidate": None,
        "next_stage": "COMPLETE",
        "decision": "NO_ACTION",
        "unknowns": unknowns,
    }


def expected_action_codes(executable_plan: dict, snapshot: str,
                          prior_result: dict | None = None) -> list[str]:
    plan = executable_plan.get("action_plan") or {}
    if snapshot == "AUCTION_0925":
        return [leaf.get("thscode") for leaf in (plan.get("primary"), plan.get("backup"))
                if leaf and leaf.get("thscode")]
    if snapshot == "OPEN_0935":
        code = (prior_result or {}).get("current_action_candidate")
        return [code] if code else []
    raise ValueError(f"unknown snapshot: {snapshot}")


def validate_result(result: dict, executable_plan: dict, validation_facts: dict,
                    prior_result: dict | None = None) -> list[str]:
    problems: list[str] = []
    snapshot = validation_facts.get("snapshot")
    plan = executable_plan.get("action_plan") or {}
    leaves = [item for item in result.get("leaf_results") or []]
    by_code = {item.get("thscode"): item for item in leaves}
    expected = expected_action_codes(executable_plan, snapshot, prior_result)
    if set(by_code) != set(expected) or len(by_code) != len(leaves):
        problems.append(
            f"leaf_results 必须精确等于快照允许对象 expected={expected} got={list(by_code)}")
    current = result.get("current_action_candidate")
    decision = result.get("decision")
    next_stage = result.get("next_stage")
    hit = result.get("condition_tree_hit") or {}
    context = result.get("context_check") or {}
    expected_validation = {
        row.get("thscode") for row in validation_facts.get("validation_context_facts") or []
    }
    if set(context.get("validation_objects") or []) != expected_validation:
        problems.append("context_check.validation_objects 必须完整等于冻结验证对象")
    context_status = context.get("status")
    if not expected_validation and context_status != "NOT_REQUIRED":
        problems.append("没有验证对象时 context_check.status 必须 NOT_REQUIRED")
    if expected_validation and context_status == "NOT_REQUIRED":
        problems.append("存在验证对象时不得写 NOT_REQUIRED")
    market_available = bool((validation_facts.get("market_check_data") or {}).get("available"))
    if expected_validation and not market_available and context_status != "DATA_INSUFFICIENT":
        problems.append("缺指数/板块分时时，单只验证对象不能确认或否定方向，必须 DATA_INSUFFICIENT")
    context_rows = validation_facts.get("validation_context_facts") or []
    context_field = "opening_match" if snapshot == "AUCTION_0925" else "open_5min"
    if expected_validation and all(
        (row.get("data_completeness") or {}).get(context_field) != "AVAILABLE"
        for row in context_rows
    ) and context_status != "DATA_INSUFFICIENT":
        problems.append(f"验证对象全部缺可用 {context_field} 时必须 DATA_INSUFFICIENT")

    expected_path_contexts = {
        item.get("task_id"): item
        for item in validation_facts.get("path_validation_contexts") or []
        if item.get("task_id")
    }
    actual_path_contexts = {
        item.get("task_id"): item for item in result.get("path_context_checks") or []
        if item.get("task_id")
    }
    path_context_status: dict[str, str] = {}
    if expected_path_contexts:
        if set(actual_path_contexts) != set(expected_path_contexts) or \
                len(actual_path_contexts) != len(result.get("path_context_checks") or []):
            problems.append("path_context_checks 必须逐项等于冻结路径验证上下文")
        for task_id, expected_context in expected_path_contexts.items():
            actual_context = actual_path_contexts.get(task_id) or {}
            for field in ("path_kind", "node_id"):
                if actual_context.get(field) != expected_context.get(field):
                    problems.append(f"path_context_checks[{task_id}].{field} 与冻结路径不一致")
            expected_codes = set(expected_context.get("validation_objects") or [])
            if set(actual_context.get("validation_objects") or []) != expected_codes:
                problems.append(f"path_context_checks[{task_id}] 验证对象不完整")
            status = actual_context.get("status")
            path_context_status[task_id] = status
            rows = expected_context.get("facts") or []
            row_codes = {row.get("thscode") for row in rows if row.get("thscode")}
            if row_codes != expected_codes:
                problems.append(
                    f"path_validation_contexts[{task_id}] 事实行未完整覆盖冻结验证对象")
            if not expected_codes and status != "NOT_REQUIRED":
                problems.append(f"path_context_checks[{task_id}] 无验证对象时必须 NOT_REQUIRED")
            if expected_codes and not market_available and status != "DATA_INSUFFICIENT":
                problems.append(
                    f"path_context_checks[{task_id}] 缺指数/板块分时时必须 DATA_INSUFFICIENT")
            if expected_codes and (row_codes != expected_codes or all(
                    (row.get("data_completeness") or {}).get(context_field) != "AVAILABLE"
                    for row in rows)) and status != "DATA_INSUFFICIENT":
                problems.append(
                    f"path_context_checks[{task_id}] 验证对象缺 {context_field} 时必须 DATA_INSUFFICIENT")
    elif result.get("path_context_checks"):
        problems.append("冻结计划没有路径验证上下文时 path_context_checks 必须为空")

    plan_leaves = {
        item.get("thscode"): item
        for item in (plan.get("primary"), plan.get("backup")) if item
    }
    for code, row in by_code.items():
        expected_leaf = plan_leaves.get(code) or {}
        if row.get("leaf_id") != expected_leaf.get("leaf_id"):
            problems.append(f"{code}: leaf_id 与冻结计划不一致")
        if row.get("tier") != expected_leaf.get("tier"):
            problems.append(f"{code}: tier 与冻结计划不一致")

    if snapshot == "AUCTION_0925":
        for code, row in by_code.items():
            if row.get("leaf_state") not in AUCTION_STATES:
                problems.append(f"{code}: 09:25 使用了非竞价状态")
        primary = plan.get("primary") or {}
        backup = plan.get("backup") or {}
        primary_code = primary.get("thscode")
        backup_code = backup.get("thscode")
        primary_state = (by_code.get(primary_code) or {}).get("leaf_state")
        backup_state = (by_code.get(backup_code) or {}).get("leaf_state") if backup_code else None
        expected_current = None
        expected_branch = "NO_CANDIDATE"
        if primary_state in AUCTION_PASS_STATES:
            expected_current = primary_code
            expected_branch = "PRIMARY_CONTINUES"
        elif primary_state == "DOWNGRADED":
            expected_branch = "PRIMARY_DOWNGRADED_NO_SWITCH"
        elif primary_state == "DIRECT_FAIL":
            if backup_code and backup_state in AUCTION_PASS_STATES:
                expected_current = backup_code
                expected_branch = "PRIMARY_DIRECT_FAIL_BACKUP_CONTINUES"
            else:
                expected_branch = "BOTH_FAIL"
        elif primary_state == "DATA_INSUFFICIENT":
            expected_branch = "DATA_BLOCKED"
        elif plan.get("status") == "NO_ACTION":
            expected_branch = "NO_CANDIDATE"

        selected_leaf = plan_leaves.get(expected_current) or {}
        selected_context_status = (
            path_context_status.get(selected_leaf.get("task_id"), "DATA_INSUFFICIENT")
            if expected_current and expected_path_contexts else context_status)
        if expected_current and selected_context_status == "REJECTS":
            expected_current = None
            expected_branch = "CONTEXT_REJECTS"
        elif expected_current and selected_context_status == "DATA_INSUFFICIENT":
            expected_current = None
            expected_branch = "DATA_BLOCKED"

        if current != expected_current:
            problems.append(
                f"09:25 current_action_candidate 应为 {expected_current!r}，实际 {current!r}")
        if hit.get("branch") != expected_branch:
            problems.append(f"09:25 condition_tree_hit.branch 应为 {expected_branch}")
        if expected_current:
            if decision != "WAIT_OPEN_VALIDATION" or next_stage != "OPEN_0935":
                problems.append("09:25 有唯一对象时只能 WAIT_OPEN_VALIDATION -> OPEN_0935")
        elif decision not in {"NO_ACTION", "DATA_INSUFFICIENT"} or next_stage != "STOP":
            problems.append("09:25 无唯一对象时必须停止，不能进入09:35找新票")

    elif snapshot == "OPEN_0935":
        prior_code = (prior_result or {}).get("current_action_candidate")
        if not prior_code:
            if leaves or current is not None or decision != "NO_ACTION" or next_stage != "COMPLETE":
                problems.append("09:25 无对象时，09:35 必须保持 NO_ACTION 且不得产生叶子")
            if hit.get("branch") != "NO_CANDIDATE":
                problems.append("09:35 无前序对象时分支必须为 NO_CANDIDATE")
            return problems
        state = (by_code.get(prior_code) or {}).get("leaf_state")
        if state not in OPEN_STATES:
            problems.append(f"{prior_code}: 09:35 使用了非开盘状态")
        prior_leaf = plan_leaves.get(prior_code) or {}
        selected_context_status = (
            path_context_status.get(prior_leaf.get("task_id"), "DATA_INSUFFICIENT")
            if expected_path_contexts else context_status)
        context_allows = selected_context_status in {"CONFIRMS", "NOT_REQUIRED"}
        if state == "MEETS_OPEN_TASK" and context_allows:
            if current != prior_code or decision != "BUY" or hit.get("branch") != "OPEN_CONFIRM":
                problems.append("09:35 完成任务且验证通过时只能确认09:25唯一对象")
        elif state == "DATA_INSUFFICIENT" or selected_context_status == "DATA_INSUFFICIENT":
            if current is not None or decision != "DATA_INSUFFICIENT" \
                    or hit.get("branch") != "DATA_BLOCKED":
                problems.append("09:35 数据不足不得确认对象")
        else:
            if current is not None or decision != "NO_ACTION" or hit.get("branch") != "OPEN_REJECT":
                problems.append("09:35 任务失败必须 NO_ACTION")
        if next_stage != "COMPLETE":
            problems.append("09:35 必须结束条件树，不得继续找票")
    return problems
