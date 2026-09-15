"""Compile a Stage-C narrative into a closed, executable next-day plan.

The compiler does not choose stocks.  It rejects any model output that escapes
the frozen primary path/task/pool or leaves an ambiguous morning decision.
"""
from __future__ import annotations

import hashlib
import re


_FIXED_THRESHOLD = re.compile(
    r"(?:\d+(?:\.\d+)?\s*%|高开\s*\d|低开\s*\d|封单.{0,8}\d+(?:\.\d+)?\s*[万亿]|"
    r"成交额.{0,8}\d+(?:\.\d+)?\s*[万亿])"
)


def _leaf_id(task_id: str, tier: str, code: str) -> str:
    digest = hashlib.sha256(f"{task_id}|{tier}|{code}".encode()).hexdigest()[:10].upper()
    return f"LEAF-{digest}"


def _condition_text(leaf: dict | None) -> list[str]:
    if not leaf:
        return []
    return [str(item) for field in (
        "auction_conditions", "open_conditions", "downgrade_conditions",
        "direct_fail_conditions",
    ) for item in (leaf.get(field) or [])]


def _tail_contract_violations(leaf: dict | None) -> list[str]:
    if not leaf or leaf.get("action_type") != "TAIL_CONFIRMATION":
        return []
    required = [
        "tail_event_trigger", "required_board_reflux", "required_breakout_state",
        "regulatory_condition", "latest_valid_time", "cancel_conditions",
    ]
    missing = [key for key in required if not leaf.get(key)]
    return [f"TAIL_CONFIRMATION 缺少冻结尾盘事件字段: {missing}"] if missing else []


def _pair_order_violations(action: dict, pairwise_rows: list[dict],
                           task: dict) -> list[str]:
    """Reject a PRIMARY/BACKUP order not proved by this task's functions."""
    contract = task.get("pair_preference_contract") or {}
    if action.get("status") != "CONDITIONAL_PAIR" or \
            contract.get("status") != "SYMMETRIC_UNRESOLVED":
        return []
    primary = (action.get("primary") or {}).get("thscode")
    backup = (action.get("backup") or {}).get("thscode")
    direct = [row for row in pairwise_rows
              if {row.get("left_thscode"), row.get("right_thscode")} ==
              {primary, backup}]
    if len(direct) != 1:
        return ["对称未决两只缺唯一直接逐对关系，不能强排 PRIMARY/BACKUP"]
    relation = direct[0]
    expected = ("LEFT_PRIMARY" if relation.get("left_thscode") == primary
                else "RIGHT_PRIMARY")
    violations = []
    if relation.get("conclusion") != expected:
        violations.append("逐对结论未形成支持 PRIMARY 的单边任务功能优势")
    families = set(relation.get("evidence_families") or [])
    allowed = set(contract.get("allowed_evidence_families") or [])
    if not families or (allowed and not families.issubset(allowed)):
        violations.append("逐对排序缺任务允许的 evidence_families")
    advantages = (relation.get("left_advantages") if expected == "LEFT_PRIMARY"
                  else relation.get("right_advantages")) or []
    if not advantages or not relation.get("fact_ids"):
        violations.append("逐对排序缺单边功能优势或事实引用")
    return violations


def _compile_multi_path(stage_b: dict, stage_c: dict, task_bundle: dict,
                        candidate_pools: list[dict], facts: dict) -> dict:
    """Compile C2 path plans into the same closed two-leaf runtime contract."""
    violations: list[str] = []
    tasks = {item.get("task_id"): item
             for item in task_bundle.get("task_candidates") or []}
    pools = {item.get("task_id"): item for item in candidate_pools}
    path_plans = stage_c.get("path_plans") or []
    leaf_sources: dict[tuple[str, str, str], tuple[dict, dict, dict]] = {}
    execution_tasks = []
    validation_codes: set[str] = set()

    for path_plan in path_plans:
        execution = path_plan.get("execution_task") or {}
        task_id = execution.get("task_id")
        path_kind = path_plan.get("path_kind")
        task = tasks.get(task_id)
        pool = pools.get(task_id) or {}
        if not task or pool.get("status") != "ACTION_READY":
            violations.append(f"{path_kind}/{task_id}: 任务或候选池不可执行")
            continue
        execution_tasks.append({**execution, "path_kind": path_kind,
                                "node_id": task.get("node_id"),
                                "anchor_date": task.get("anchor_date")})
        validation_codes.update(
            row.get("thscode") for row in pool.get("validation_pool") or []
            if row.get("thscode"))
        candidates = {row.get("thscode"): row
                      for row in path_plan.get("candidates") or []}
        action = path_plan.get("action_plan") or {}
        violations.extend(
            f"{path_kind}/{task_id}: {problem}" for problem in
            _pair_order_violations(
                action, path_plan.get("pairwise_comparison") or [], task))
        for leaf in (action.get("primary"), action.get("backup")):
            if not leaf:
                continue
            code = leaf.get("thscode")
            if leaf.get("task_id") != task_id or leaf.get("path_kind") != path_kind:
                violations.append(f"{path_kind}/{task_id}/{code}: 叶子身份与路径任务不一致")
            if code not in candidates:
                violations.append(f"{path_kind}/{task_id}/{code}: 叶子不在路径候选中")
            violations.extend(
                f"{path_kind}/{task_id}/{code}: {problem}"
                for problem in _tail_contract_violations(leaf))
            for condition in _condition_text(leaf):
                if _FIXED_THRESHOLD.search(condition):
                    violations.append(
                        f"{path_kind}/{task_id}/{code}: 动作条件包含固定数字阈值 `{condition}`")
            leaf_sources[(path_kind, task_id, code)] = (leaf, candidates.get(code) or {}, task)

    final = stage_c.get("final_action_plan") or {}
    primary_ref, backup_ref = final.get("primary_ref"), final.get("backup_ref")

    def ref_key(ref: dict | None):
        if not ref:
            return None
        return ref.get("path_kind"), ref.get("task_id"), ref.get("thscode")

    primary_key, backup_key = ref_key(primary_ref), ref_key(backup_ref)
    if primary_key and primary_key not in leaf_sources:
        violations.append("final primary_ref 不在冻结路径叶子")
    if backup_key and backup_key not in leaf_sources:
        violations.append("final backup_ref 不在冻结路径叶子")
    if primary_key and backup_key and primary_key == backup_key:
        violations.append("最终 PRIMARY/BACKUP 不得相同")
    if final.get("status") == "NO_ACTION":
        if primary_key or backup_key:
            violations.append("NO_ACTION 不得带动作引用")
    elif final.get("status") == "SINGLE":
        if not primary_key or backup_key:
            violations.append("SINGLE 必须只有 primary_ref")
    elif final.get("status") == "CONDITIONAL_PAIR":
        if not primary_key or not backup_key:
            violations.append("CONDITIONAL_PAIR 必须同时有 primary_ref/backup_ref")
        switch_text = final.get("switch_rule") or ""
        if "直接失败" not in switch_text or "独立" not in switch_text:
            violations.append("备选切换必须要求 PRIMARY 直接失败且 BACKUP 独立通过")

    if violations:
        return {"verdict": "NEEDS_REVISION", "violations": violations,
                "executable_plan": None}

    def compile_ref(tier: str, key):
        if not key:
            return None
        leaf, candidate, task = leaf_sources[key]
        path_kind, task_id, code = key
        return {
            "leaf_id": _leaf_id(task_id, tier, code),
            "tier": tier,
            "path_kind": path_kind,
            "task_id": task_id,
            "anchor_date": candidate.get("anchor_date") or task.get("anchor_date"),
            "node_id": candidate.get("node_id") or task.get("node_id"),
            "stock_start_date": candidate.get("stock_start_date"),
            "role": candidate.get("role"),
            "role_family": candidate.get("role_family"),
            "role_status": candidate.get("role_status"),
            "path_validation_objects": sorted(
                row.get("thscode") for row in
                (pools.get(task_id, {}).get("validation_pool") or [])
                if row.get("thscode")),
            "current_function": candidate.get("observed_function") or leaf.get("task_to_complete"),
            "entry_event": candidate.get("observed_state") or [],
            "exit_conditions": list(dict.fromkeys(
                (candidate.get("cancel_if") or []) + (leaf.get("direct_fail_conditions") or []))),
            **leaf,
        }

    primary_leaf = compile_ref("PRIMARY", primary_key)
    backup_leaf = compile_ref("BACKUP", backup_key)
    primary_execution = next((item for item in execution_tasks
                              if primary_key and item.get("task_id") == primary_key[1]), None)
    if primary_execution is None:
        primary_execution = execution_tasks[0] if execution_tasks else {
            "status": "NONE", "task_id": None, "task_type": None, "theme": None,
            "anchor_date": None, "path_kind": None,
        }
    executable = {
        "version": "3.0",
        "plan_date": str(stage_b.get("as_of") or "")[:8],
        "as_of": stage_b.get("as_of"),
        "primary_path": stage_b.get("primary_path") or {},
        "execution_task": primary_execution,
        "execution_tasks": execution_tasks,
        "action_plan": {
            "status": final.get("status"),
            "task_id": primary_key[1] if primary_key else None,
            "primary": primary_leaf,
            "backup": backup_leaf,
            "validation_objects": sorted(validation_codes),
            "rule_ids": final.get("rule_ids") or [],
            "switch_policy": "PRIMARY_DIRECT_FAIL_AND_BACKUP_INDEPENDENT_PASS",
            "no_action_conditions": final.get("no_action_conditions") or [],
        },
        "allowed_action_codes": sorted(
            leaf.get("thscode") for leaf in (primary_leaf, backup_leaf) if leaf),
        "forbidden_new_candidates": True,
        "source_task_pool_status": {
            task_id: pools.get(task_id, {}).get("status")
            for task_id in {item.get("task_id") for item in execution_tasks}
        },
    }
    return {"verdict": "PASS", "violations": [], "executable_plan": executable}


def compile_plan(stage_b: dict, stage_c: dict, task_bundle: dict,
                 candidate_pools: list[dict], facts: dict) -> dict:
    if "path_plans" in stage_c:
        return _compile_multi_path(stage_b, stage_c, task_bundle, candidate_pools, facts)
    violations: list[str] = []
    primary_path = stage_b.get("primary_path") or {}
    execution = stage_c.get("execution_task") or {}
    action_plan = stage_c.get("action_plan") or {}
    group = stage_c.get("action_competition_group") or {}
    tasks = {item.get("task_id"): item
             for item in task_bundle.get("task_candidates") or []}
    pools = {item.get("task_id"): item for item in candidate_pools}
    selected_id = execution.get("task_id")
    task = tasks.get(selected_id)
    pool = pools.get(selected_id) or {}

    if execution.get("status") == "SELECTED":
        if primary_path.get("status") != "SELECTED":
            violations.append("没有动态主路径时不得选择执行任务")
        if not task:
            violations.append("execution_task.task_id 不在冻结 task_candidates")
        else:
            if task.get("theme") != primary_path.get("theme"):
                violations.append("执行任务方向与动态主路径不一致")
            if task.get("direction_fact_id") != primary_path.get("direction_fact_id"):
                violations.append("执行任务引用的方向事实与动态主路径不一致")
            if execution.get("task_type") != task.get("task_type"):
                violations.append("execution_task.task_type 与冻结任务不一致")
            if execution.get("theme") != task.get("theme"):
                violations.append("execution_task.theme 与冻结任务不一致")
        if pool.get("status") != "READY":
            violations.append("选中任务候选池非 READY")
    elif action_plan.get("status") != "NO_ACTION":
        violations.append("execution_task 未选中时 action_plan 必须 NO_ACTION")

    catalog = facts.get("fact_catalog") or {}
    for ref in execution.get("supporting_fact_ids") or []:
        if ref not in catalog:
            violations.append(f"execution_task 引用了不存在的 fact_id {ref}")

    pool_codes = {row.get("thscode") for row in pool.get("pool") or []}
    validation_codes = {row.get("thscode") for row in pool.get("validation_pool") or []}
    fact_codes = {row.get("thscode") for row in facts.get("stage_b_observation_universe") or []}
    candidate_by_code = {row.get("thscode"): row for row in stage_c.get("candidates") or []}
    action_members = set(group.get("members") or [])
    declared_validation = set(group.get("validation_objects") or [])
    relation_members = {
        code for code, row in candidate_by_code.items()
        if row.get("task_relation") == "ACTION_COMPETITOR"
    }
    relation_validation = {
        code for code, row in candidate_by_code.items()
        if row.get("task_relation") == "VALIDATION_ONLY"
    }
    if selected_id and group.get("task_id") != selected_id:
        violations.append("action_competition_group.task_id 与执行任务不一致")
    if action_members != relation_members:
        violations.append("动作竞争组必须等于 ACTION_COMPETITOR 股票集合")
    if declared_validation != validation_codes or relation_validation != validation_codes:
        violations.append("验证对象必须与冻结 validation_pool 完全一致")
    if not action_members.issubset(pool_codes):
        violations.append("动作竞争组包含选中任务池之外的股票")
    if action_members & validation_codes:
        violations.append("VALIDATION_ONLY 对象不得进入动作竞争组")
    if not (action_members | validation_codes).issubset(fact_codes):
        violations.append("计划包含事实包之外的股票")

    status = action_plan.get("status")
    plan_task_id = action_plan.get("task_id")
    primary = action_plan.get("primary")
    backup = action_plan.get("backup")
    if status == "NO_ACTION":
        if primary is not None or backup is not None:
            violations.append("NO_ACTION 时 primary/backup 必须为 null")
    elif status == "SINGLE":
        if not primary or backup is not None:
            violations.append("SINGLE 必须且只能有 primary")
    elif status == "CONDITIONAL_PAIR":
        if not primary or not backup:
            violations.append("CONDITIONAL_PAIR 必须同时定义 primary 和 backup")
        elif primary.get("thscode") == backup.get("thscode"):
            violations.append("PRIMARY 与 BACKUP 不得是同一股票")
        switch_text = str(action_plan.get("switch_rule") or "")
        if "直接失败" not in switch_text or "独立" not in switch_text:
            violations.append("备选切换规则必须同时要求 PRIMARY 直接失败和 BACKUP 独立满足")
    if execution.get("status") == "SELECTED" and plan_task_id != selected_id:
        violations.append("action_plan.task_id 与 execution_task 不一致")
    if execution.get("status") != "SELECTED" and plan_task_id is not None:
        violations.append("无选中 execution_task 时 action_plan.task_id 必须为 null")
    if status != "NO_ACTION" and len(action_members) > 2:
        violations.append("三只以上动作竞争者无法收敛时必须 NO_ACTION")

    leaf_codes = {leaf.get("thscode") for leaf in (primary, backup) if leaf}
    if not leaf_codes.issubset(action_members):
        violations.append("动作叶子必须来自同一 action_competition_group")
    if leaf_codes & validation_codes:
        violations.append("验证对象不得进入 PRIMARY/BACKUP")
    if status != "NO_ACTION" and not leaf_codes:
        violations.append("可执行计划缺动作叶子")
    if status != "NO_ACTION" and leaf_codes != action_members:
        violations.append("动作竞争组必须完全收敛为 PRIMARY/BACKUP，不得留下盘中临选对象")

    violations.extend(_pair_order_violations(
        action_plan, stage_c.get("pairwise_comparison") or [], task or {}))

    for tier, leaf in (("PRIMARY", primary), ("BACKUP", backup)):
        if not leaf:
            continue
        code = leaf.get("thscode")
        candidate = candidate_by_code.get(code) or {}
        if candidate.get("task_id") != selected_id:
            violations.append(f"{tier} {code}: 不属于选中执行任务")
        if not leaf.get("task_to_complete"):
            violations.append(f"{tier} {code}: 缺独立任务")
        violations.extend(
            f"{tier} {code}: {problem}" for problem in _tail_contract_violations(leaf))
        for text in _condition_text(leaf):
            if _FIXED_THRESHOLD.search(text):
                violations.append(f"{tier} {code}: 动作条件包含固定数字阈值 `{text}`")

    if set(action_plan.get("validation_objects") or []) != validation_codes:
        violations.append("action_plan.validation_objects 与冻结验证池不一致")

    if violations:
        return {"verdict": "NEEDS_REVISION", "violations": violations,
                "executable_plan": None}

    def compile_leaf(tier: str, leaf: dict | None):
        if not leaf:
            return None
        candidate = candidate_by_code.get(leaf["thscode"]) or {}
        return {
            "leaf_id": _leaf_id(selected_id or "NO_TASK", tier, leaf["thscode"]),
            "tier": tier,
            "task_id": selected_id,
            "anchor_date": candidate.get("anchor_date") or (task or {}).get("anchor_date"),
            "role": candidate.get("role"),
            "role_family": candidate.get("role_family"),
            "role_status": candidate.get("role_status"),
            "current_function": candidate.get("observed_function") or leaf.get("task_to_complete"),
            "entry_event": candidate.get("observed_state") or [],
            "exit_conditions": list(dict.fromkeys(
                (candidate.get("cancel_if") or []) + (leaf.get("direct_fail_conditions") or []))),
            **leaf,
        }

    executable = {
        "version": "2.0",
        "plan_date": str(stage_b.get("as_of") or "")[:8],
        "as_of": stage_b.get("as_of"),
        "primary_path": primary_path,
        "execution_task": {**execution, "anchor_date": (task or {}).get("anchor_date")},
        "action_plan": {
            "status": status,
            "task_id": plan_task_id,
            "primary": compile_leaf("PRIMARY", primary),
            "backup": compile_leaf("BACKUP", backup),
            "validation_objects": sorted(validation_codes),
            "rule_ids": action_plan.get("rule_ids") or [],
            "switch_policy": "PRIMARY_DIRECT_FAIL_AND_BACKUP_INDEPENDENT_PASS",
            "no_action_conditions": action_plan.get("no_action_conditions") or [],
        },
        "allowed_action_codes": sorted(leaf_codes),
        "forbidden_new_candidates": True,
        "source_task_pool_status": pool.get("status"),
    }
    return {"verdict": "PASS", "violations": [], "executable_plan": executable}
