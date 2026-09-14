"""Resolve method nodes into day-specific execution tasks.

Stage B describes market relationships.  This module performs no stock
selection and no scoring; it enumerates the concrete jobs that the selected
direction could ask stocks to complete on T+1.  Task scopes come only from the
frozen fact pack, so a model cannot roam across the market or inject names.
"""
from __future__ import annotations

import hashlib


TASK_TYPES = {
    "HIGHEST_LADDER_CONTINUATION": "最高身位延续",
    "SAME_LEVEL_PROMOTION": "同板级晋级",
    "SUB_DIRECTION_LEVEL_CONTINUATION": "同细分分支延续",
    "CAPACITY_CARRIER_VALIDATION": "容量承载验证",
    "FIRST_BOARD_DIFFUSION": "首板扩散",
    "BROKEN_BOARD_REPAIR": "炸板修复",
    "DIRECTION_REPAIR": "主流大分歧后的方向修复",
    "CORE_SWITCH": "核心切换",
    "HIGH_LOW_SWITCH": "高低切换与空间迁移",
    "PANIC_REPAIR_LEADER": "恐慌修复主动带动者",
    "FIRST_ACTIVE_DIVERGENCE": "突破后第一次主动分歧验证",
    "CATCH_UP": "补涨",
    "SECOND_WAVE_COMPANION": "二波伴生",
}

GENERATOR_TASK = {
    "G1": "HIGHEST_LADDER_CONTINUATION",
    "G2": "FIRST_BOARD_DIFFUSION",
    "G3": "SECOND_WAVE_COMPANION",
    "G4": "CATCH_UP",
    "G5": "CATCH_UP",
    "G6": "DIRECTION_REPAIR",
    "G7": "CAPACITY_CARRIER_VALIDATION",
    "G8": "SAME_LEVEL_PROMOTION",
    "G9": "CORE_SWITCH",
    "G10": "HIGH_LOW_SWITCH",
    "G11": "PANIC_REPAIR_LEADER",
    "G12": "FIRST_ACTIVE_DIVERGENCE",
}

TASK_RULE_IDS = {
    "HIGHEST_LADDER_CONTINUATION": [
        "G01_SENTIMENT_TURN", "PRIM_RESONANCE", "PRIM_SEPARATION",
        "DISC_NO_HINDSIGHT", "DISC_NO_FIXED_SCORE", "DISC_SNAPSHOT_NOT_THRESHOLD",
    ],
    "SAME_LEVEL_PROMOTION": [
        "G08_UNIQUENESS", "PRIM_RESONANCE", "PRIM_SEPARATION",
        "DISC_NO_HINDSIGHT", "DISC_NO_FIXED_SCORE", "DISC_SNAPSHOT_NOT_THRESHOLD",
    ],
    "SUB_DIRECTION_LEVEL_CONTINUATION": [
        "G08_UNIQUENESS", "PRIM_RESONANCE", "PRIM_SEPARATION",
        "DISC_NO_HINDSIGHT", "DISC_NO_FIXED_SCORE", "DISC_SNAPSHOT_NOT_THRESHOLD",
    ],
    "CAPACITY_CARRIER_VALIDATION": [
        "G07_CAPACITY_CORE", "ROLE_CAPACITY_CORE", "PRIM_RESONANCE",
        "DISC_NO_HINDSIGHT", "DISC_NO_FIXED_SCORE", "DISC_SNAPSHOT_NOT_THRESHOLD",
    ],
    "FIRST_BOARD_DIFFUSION": [
        "G02_COMPANION", "G08_UNIQUENESS", "PRIM_RESONANCE",
        "DISC_NO_HINDSIGHT", "DISC_NO_FIXED_SCORE", "DISC_SNAPSHOT_NOT_THRESHOLD",
    ],
    "BROKEN_BOARD_REPAIR": [
        "G06_DIVERGENCE_REPAIR", "PRIM_RESONANCE", "PRIM_SEPARATION",
        "DISC_NO_HINDSIGHT", "DISC_NO_FIXED_SCORE", "DISC_SNAPSHOT_NOT_THRESHOLD",
    ],
    "DIRECTION_REPAIR": [
        "G06_DIVERGENCE_REPAIR", "PRIM_RESONANCE", "PRIM_SEPARATION",
        "DISC_NO_HINDSIGHT", "DISC_NO_FIXED_SCORE", "DISC_SNAPSHOT_NOT_THRESHOLD",
    ],
    "CORE_SWITCH": [
        "G09_CORE_SWITCH", "PRIM_SEPARATION", "PRIM_RESONANCE",
        "DISC_NO_HINDSIGHT", "DISC_NO_FIXED_SCORE", "DISC_SNAPSHOT_NOT_THRESHOLD",
    ],
    "CATCH_UP": [
        "G04_POST_LEADER_SUPPLEMENT", "PRIM_SEPARATION", "PRIM_RESONANCE",
        "DISC_NO_HINDSIGHT", "DISC_NO_FIXED_SCORE", "DISC_SNAPSHOT_NOT_THRESHOLD",
    ],
    "SECOND_WAVE_COMPANION": [
        "G03_SECOND_WAVE_UPGRADE", "G05_LOW_SYMBIOSIS", "PRIM_RESONANCE",
        "DISC_NO_HINDSIGHT", "DISC_NO_FIXED_SCORE", "DISC_SNAPSHOT_NOT_THRESHOLD",
    ],
    "HIGH_LOW_SWITCH": [
        "G10_HIGH_LOW_SWITCH", "PRIM_SEPARATION", "PRIM_RESONANCE",
        "DISC_NO_HINDSIGHT", "DISC_NO_FIXED_SCORE", "DISC_SNAPSHOT_NOT_THRESHOLD",
    ],
    "PANIC_REPAIR_LEADER": [
        "G11_BOTTOM_ACTIVE", "PRIM_SEPARATION", "PRIM_RESONANCE",
        "DISC_NO_HINDSIGHT", "DISC_NO_FIXED_SCORE", "DISC_SNAPSHOT_NOT_THRESHOLD",
    ],
    "FIRST_ACTIVE_DIVERGENCE": [
        "G12_FIRST_ACTIVE_DIVERGENCE", "PRIM_SEPARATION", "PRIM_RESONANCE",
        "DISC_NO_HINDSIGHT", "DISC_NO_FIXED_SCORE", "DISC_SNAPSHOT_NOT_THRESHOLD",
    ],
}
DEFAULT_TASK_RULE_IDS = [
    "PRIM_SEPARATION", "DISC_NO_HINDSIGHT", "DISC_NO_FIXED_SCORE",
    "DISC_SNAPSHOT_NOT_THRESHOLD",
]


def _task_id(date: str, theme: str, task_type: str,
             candidate_ids: list[str], validation_ids: list[str]) -> str:
    identity = "|".join((date, theme, task_type,
                         ",".join(sorted(candidate_ids)),
                         ",".join(sorted(validation_ids))))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10].upper()
    return f"TASK-{date.replace('-', '')}-{digest}"


def _date(as_of: str | None) -> str:
    raw = str(as_of or "")[:10].replace("-", "")
    if len(raw) >= 8:
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return str(as_of or "")[:10]


def _stock_refs(rows: list[dict]) -> list[str]:
    return list(dict.fromkeys(
        row.get("fact_id") for row in rows if row.get("fact_id")
    ))


TASK_PAIR_EVIDENCE_FAMILIES = {
    "HIGHEST_LADDER_CONTINUATION": [
        "TASK_COMPLETION_PRESTATE", "DIVERGENCE_TOLERANCE", "DIRECTION_RESPONSE"],
    "SAME_LEVEL_PROMOTION": [
        "TASK_COMPLETION_PRESTATE", "INDEPENDENCE_AND_EVENT_ORDER", "DIRECTION_RESPONSE"],
    "SUB_DIRECTION_LEVEL_CONTINUATION": [
        "TASK_COMPLETION_PRESTATE", "DIRECTION_RESPONSE"],
    "CAPACITY_CARRIER_VALIDATION": [
        "CAPACITY_CARRYING", "DIVERGENCE_TOLERANCE", "DIRECTION_RESPONSE"],
    "FIRST_BOARD_DIFFUSION": [
        "TASK_COMPLETION_PRESTATE", "DIRECTION_RESPONSE"],
    "BROKEN_BOARD_REPAIR": [
        "DIVERGENCE_TOLERANCE", "INDEPENDENCE_AND_EVENT_ORDER", "DIRECTION_RESPONSE"],
    "DIRECTION_REPAIR": [
        "DIVERGENCE_TOLERANCE", "INDEPENDENCE_AND_EVENT_ORDER", "DIRECTION_RESPONSE"],
    "CORE_SWITCH": [
        "ROLE_CONTINUITY_OR_MIGRATION", "INDEPENDENCE_AND_EVENT_ORDER", "DIRECTION_RESPONSE"],
    "HIGH_LOW_SWITCH": [
        "ROLE_CONTINUITY_OR_MIGRATION", "INDEPENDENCE_AND_EVENT_ORDER", "DIRECTION_RESPONSE"],
    "PANIC_REPAIR_LEADER": [
        "INDEPENDENCE_AND_EVENT_ORDER", "DIVERGENCE_TOLERANCE", "DIRECTION_RESPONSE"],
    "FIRST_ACTIVE_DIVERGENCE": [
        "INDEPENDENCE_AND_EVENT_ORDER", "DIVERGENCE_TOLERANCE", "DIRECTION_RESPONSE"],
    "CATCH_UP": [
        "TASK_COMPLETION_PRESTATE", "DIRECTION_RESPONSE"],
    "SECOND_WAVE_COMPANION": [
        "ROLE_CONTINUITY_OR_MIGRATION", "TASK_COMPLETION_PRESTATE", "DIRECTION_RESPONSE"],
}


def _pair_preference_contract(task_type: str, candidates: list[dict]) -> dict:
    """Describe legal evidence for C2; never sort stocks with a case formula.

    The old implementation automatically promoted a stock by combining the
    2026-01-05 case fields (opening attitude + turnover percentile) and used
    seal efficiency as a secondary family.  That converted one example into
    a universal ranking rule.  The resolver now freezes no stock order.  C2
    must compare the function demanded by this task and cite the permitted
    evidence families; otherwise the pair remains unresolved and cannot be
    forced into PRIMARY/BACKUP.
    """
    families = TASK_PAIR_EVIDENCE_FAMILIES.get(task_type, [
        "TASK_COMPLETION_PRESTATE", "INDEPENDENCE_AND_EVENT_ORDER",
        "DIRECTION_RESPONSE",
    ])
    if len(candidates) != 2:
        return {
            "status": "NOT_APPLICABLE", "primary_hint": None,
            "backup_hint": None, "reasoning": ["动作竞争者不是恰好两只"],
            "allowed_evidence_families": families,
        }
    return {
        "status": "SYMMETRIC_UNRESOLVED",
        "primary_hint": None,
        "backup_hint": None,
        "allowed_evidence_families": families,
        "reasoning": [
            "程序不使用任何跨任务通用行情字段自动排列 PRIMARY/BACKUP",
            "C2只能围绕本任务缺失功能，引用允许的证据家庭形成逐对关系结论",
            "无法形成单边功能优势时保持对称未决，并输出 NO_ACTION",
        ],
    }


def _role_assignment_contract(candidates: list[dict], validators: list[dict]) -> dict:
    """Freeze which stocks lack evidence for a named roubing role."""
    rows = candidates + validators
    unresolved = sorted({
        row.get("thscode") for row in rows
        if row.get("thscode") and not (row.get("previous_role_task") or {}).get("available")
    })
    return {
        "status": "UNRESOLVED" if unresolved else "PRIOR_STATE_AVAILABLE",
        "required_unknown_codes": unresolved,
        "leader_state": "UNRESOLVED" if unresolved else "REQUIRES_MIGRATION_CHECK",
        "reasoning": [
            "PRIMARY/BACKUP是动作叶子验证顺序，不是核心角色确认",
            "缺前日角色账本及主动带动/承压完成证据时，角色和角色族必须保持UNKNOWN",
            "VALIDATION_ONLY只说明验证功能，不能据板级直接命名为总核心或容量核心",
        ],
    }


def _make_task(*, date: str, theme: str, direction_fact_id: str,
               task_type: str, candidates: list[dict], validators: list[dict],
               node: dict, scope_logic: list[str], required_function: str,
               data_gaps: list[str] | None = None) -> dict:
    candidate_ids = sorted({row.get("thscode") for row in candidates if row.get("thscode")})
    validation_ids = sorted({row.get("thscode") for row in validators
                             if row.get("thscode") and row.get("thscode") not in candidate_ids})
    candidate_anchors = sorted({row.get("event_anchor_date") for row in candidates
                                if row.get("event_anchor_date")})
    task_anchor = node.get("anchor_date") or date
    node_generators = [node.get("generator")] if node.get("generator") else []
    fact_ids = list(dict.fromkeys(
        [direction_fact_id] + (node.get("trigger_fact_ids") or [])
        + _stock_refs(candidates) + _stock_refs(validators)
    ))
    missing_explicit = sorted(set(node.get("candidate_scope", {}).get("candidate_ids") or [])
                              - set(candidate_ids))
    status = "ACTION_READY" if candidate_ids and not missing_explicit else (
        "BLOCKED" if missing_explicit else "EMPTY_VALID")
    return {
        "task_id": _task_id(task_anchor, theme, task_type, candidate_ids, validation_ids),
        "task_type": task_type,
        "task_name": TASK_TYPES[task_type],
        "status": status,
        "theme": theme,
        "direction_fact_id": direction_fact_id,
        "anchor_date": task_anchor,
        "node_id": node.get("node_id"),
        "node_type": node.get("node_type"),
        "node_action_status": node.get("action_status"),
        "path_kind": node.get("path_kind"),
        "anchor_status": ("VERIFIED_COMMON" if len(candidate_anchors) == 1
                          and candidate_anchors[0] == task_anchor else "NODE_ANCHORED"),
        "candidate_anchor_dates": candidate_anchors,
        "candidate_start_dates": {
            row.get("thscode"): row.get("event_anchor_date")
            for row in candidates if row.get("thscode")
        },
        "validation_anchor_dates": {
            row.get("thscode"): row.get("event_anchor_date")
            for row in validators if row.get("thscode")
        },
        "method_node_types": [node.get("node_type")] if node.get("node_type") else [],
        "method_generators": node_generators,
        "required_function": required_function,
        "required_rule_ids": list(dict.fromkeys(
            (node.get("rule_ids") or [])
            + TASK_RULE_IDS.get(task_type, DEFAULT_TASK_RULE_IDS))),
        "scope_logic": scope_logic,
        "candidate_ids": candidate_ids,
        "validation_ids": validation_ids,
        "eligibility_fact_ids": fact_ids,
        "comparison_dimensions": [
            "竞价是否完成各自盘后任务，而不是比较固定高开数值",
            "同任务对象谁先主动增强、谁只是跟随",
            "开盘后是否承受分歧并维持价格重心",
            "对象增强时方向和验证对象是否响应",
        ],
        "pair_preference_contract": _pair_preference_contract(task_type, candidates),
        "role_assignment_contract": _role_assignment_contract(candidates, validators),
        "completion_signals": [
            "候选独立完成该任务且同任务对手未同时占优",
            "方向或验证对象对候选行为产生同步响应",
        ],
        "failure_signals": [
            "候选没有完成任务，或强度只能由同组其他对象解释",
            "方向与验证对象不响应，任务关系被证伪",
        ],
        "data_gaps": list(data_gaps or []) + (
            [f"节点明确候选未在冻结事实范围内找到: {missing_explicit}"]
            if missing_explicit else []),
    }


def _direction_by_theme(stage_b: dict) -> dict[str, dict]:
    return {
        item.get("theme"): item for item in stage_b.get("direction_evaluations") or []
        if item.get("theme")
    }


def _no_action_rule_ids(stage_b: dict) -> list[str]:
    """Rules that justify declining to open an execution task."""
    values = list((stage_b.get("primary_path") or {}).get("rule_ids") or [])
    for node in stage_b.get("nodes") or []:
        if node.get("action_status") != "ACTION_READY":
            values.extend(node.get("rule_ids") or [])
    return list(dict.fromkeys(values))


def _scope_rows(node: dict, rows: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
    """Apply the exact Stage-B node scope without broadening it.

    Empty filters mean "all rows in this already frozen direction" only for a
    direction-wide method node.  Explicit candidate/validation IDs are never
    replaced by similarly shaped stocks.
    """
    scope = node.get("candidate_scope") or {}
    explicit = list(dict.fromkeys(
        (scope.get("candidate_ids") or []) + (node.get("candidate_ids") or [])))
    validation_ids = list(dict.fromkeys(scope.get("validation_ids") or []))
    event_statuses = set(scope.get("event_statuses") or [])
    board_levels = {int(value) for value in scope.get("board_levels") or []}
    sub_directions = set(scope.get("sub_directions") or [])
    by_code = {row.get("thscode"): row for row in rows if row.get("thscode")}

    if explicit:
        candidates = [by_code[code] for code in explicit if code in by_code]
    else:
        candidates = []
        for row in rows:
            status = row.get("event_status") or row.get("status")
            if event_statuses and status not in event_statuses:
                continue
            if board_levels and int(row.get("board_level") or -1) not in board_levels:
                continue
            if sub_directions and row.get("sub_direction") not in sub_directions:
                continue
            if node.get("generator") == "G8" and row.get("event_anchor_date") != node.get("anchor_date"):
                continue
            candidates.append(row)

    candidate_codes = {row.get("thscode") for row in candidates}
    validators = [by_code[code] for code in validation_ids
                  if code in by_code and code not in candidate_codes]
    gaps = []
    missing_validation = sorted(set(validation_ids) - set(by_code))
    if missing_validation:
        gaps.append(f"节点验证对象未在冻结事实范围内找到: {missing_validation}")
    return candidates, validators, gaps


def resolve(stage_b: dict, facts: dict) -> dict:
    """Return tasks opened by legal Stage-B nodes, never by board geometry."""
    path = stage_b.get("primary_path") or {}
    date = _date(stage_b.get("as_of") or facts.get("trade_date"))
    if path.get("status") != "SELECTED" or not path.get("theme"):
        return {
            "as_of": stage_b.get("as_of"),
            "status": "NO_PRIMARY_PATH" if path.get("status") == "NONE" else "BLOCKED_DATA",
            "primary_theme": None,
            "primary_direction_fact_id": None,
            "task_candidates": [],
            "no_action_rule_ids": _no_action_rule_ids(stage_b),
            "reason": "没有已确认的动态主路径，禁止生成股票执行任务",
        }

    primary_theme = path["theme"]
    directions = _direction_by_theme(stage_b)
    all_rows = facts.get("stage_b_observation_universe") or []
    tasks: list[dict] = []
    observed_nodes: list[dict] = []

    for raw_node in stage_b.get("nodes") or []:
        node = dict(raw_node)
        theme = node.get("theme")
        direction = directions.get(theme) or {}
        direction_fact_id = direction.get("direction_fact_id")
        if theme == primary_theme:
            direction_fact_id = path.get("direction_fact_id") or direction_fact_id
            node["path_kind"] = "PRIMARY"
        elif direction.get("path_status") == "COMPETITOR":
            node["path_kind"] = "ALTERNATIVE"
        else:
            node["path_kind"] = "OBSERVATION"

        generator = node.get("generator")
        action_status = node.get("action_status")
        if action_status != "ACTION_READY" or not generator:
            observed_nodes.append({
                "node_id": node.get("node_id"), "theme": theme,
                "action_status": action_status, "generator": generator,
                "path_kind": node.get("path_kind"),
                "reason": "节点未同时满足 ACTION_READY 且 generator 非空，不得产生执行任务",
            })
            continue
        task_type = GENERATOR_TASK.get(generator)
        if not task_type or not node.get("node_id") or not theme or not direction_fact_id:
            observed_nodes.append({
                "node_id": node.get("node_id"), "theme": theme,
                "action_status": "BLOCKED", "generator": generator,
                "path_kind": node.get("path_kind"),
                "reason": "动作节点缺 task mapping、node_id、theme 或 direction_fact_id",
            })
            continue

        rows = [row for row in all_rows
                if row.get("direction_fact_id") == direction_fact_id]
        candidates, validators, gaps = _scope_rows(node, rows)
        scope = node.get("candidate_scope") or {}
        task = _make_task(
            date=date, theme=theme, direction_fact_id=direction_fact_id,
            task_type=task_type, candidates=candidates, validators=validators,
            node=node,
            required_function=(node.get("required_function") or
                               (node.get("method_reasoning") or [TASK_TYPES[task_type]])[-1]),
            scope_logic=[scope.get("scope_reason") or "严格使用节点冻结候选范围"],
            data_gaps=gaps,
        )
        tasks.append(task)

    unique: dict[str, dict] = {}
    for task in tasks:
        unique.setdefault(task["task_id"], task)
    return {
        "as_of": stage_b.get("as_of"),
        "status": "ACTION_READY" if any(
            task.get("status") == "ACTION_READY" for task in unique.values()) else "NO_ACTION_TASK",
        "primary_theme": primary_theme,
        "primary_direction_fact_id": path.get("direction_fact_id"),
        "task_candidates": list(unique.values()),
        "no_action_rule_ids": _no_action_rule_ids(stage_b),
        "observed_nodes": observed_nodes,
        "reason": "任务只由 ACTION_READY 方法节点打开；板位、池大小和炸板本身不能造任务",
    }


def build_task_pools(task_bundle: dict, facts: dict) -> list[dict]:
    """Materialize exact per-task candidate/validation pools from fact IDs."""
    rows = {row.get("thscode"): row
            for row in facts.get("stage_b_observation_universe") or []}
    pools = []
    for task in task_bundle.get("task_candidates") or []:
        missing = [code for code in task.get("candidate_ids") or [] if code not in rows]
        pool = [dict(rows[code]) for code in task.get("candidate_ids") or [] if code in rows]
        validation_pool = [dict(rows[code]) for code in task.get("validation_ids") or []
                           if code in rows]
        for row in pool:
            row["required_anchor_date"] = task.get("anchor_date")
            row["required_node_id"] = task.get("node_id")
            row["required_stock_start_date"] = row.get("event_anchor_date")
        for row in validation_pool:
            row["required_anchor_date"] = task.get("anchor_date")
            row["required_node_id"] = task.get("node_id")
            row["required_stock_start_date"] = row.get("event_anchor_date")
        blocks = list(task.get("data_gaps") or [])
        if missing:
            blocks.append(f"任务候选未在事实观察集中找到: {missing}")
        if task.get("node_action_status") != "ACTION_READY":
            blocks.append("来源节点不是 ACTION_READY")
        if not task.get("method_generators"):
            blocks.append("来源节点没有生成器")
        status = (
            "ACTION_READY" if pool and not missing and not blocks
            and task.get("status") == "ACTION_READY" else
            "BLOCKED" if missing or blocks or task.get("status") == "BLOCKED" else
            "EMPTY_VALID"
        )
        pools.append({
            "task_id": task.get("task_id"),
            "task_type": task.get("task_type"),
            "task_name": task.get("task_name"),
            "theme": task.get("theme"),
            "anchor_date": task.get("anchor_date"),
            "node_id": task.get("node_id"),
            "node_action_status": task.get("node_action_status"),
            "path_kind": task.get("path_kind"),
            "method_generators": task.get("method_generators") or [],
            "required_function": task.get("required_function"),
            "required_rule_ids": task.get("required_rule_ids") or [],
            "pair_preference_contract": task.get("pair_preference_contract") or {},
            "role_assignment_contract": task.get("role_assignment_contract") or {},
            "status": status,
            "pool": pool,
            "pool_size": len(pool),
            "validation_pool": validation_pool,
            "validation_pool_size": len(validation_pool),
            "data_blocks": blocks,
        })
    return pools


def summarize_tasks(task_bundle: dict) -> dict:
    """Remove every stock/count/easy-convergence hint before Stage C1."""
    allowed = (
        "task_id", "task_type", "task_name", "status", "path_kind", "theme",
        "direction_fact_id", "node_id", "node_type", "node_action_status",
        "anchor_date", "required_function", "required_rule_ids", "scope_logic",
        "completion_signals", "failure_signals", "data_gaps", "eligibility_fact_ids",
    )
    return {
        "as_of": task_bundle.get("as_of"),
        "status": task_bundle.get("status"),
        "tasks": [{key: task.get(key) for key in allowed}
                  for task in task_bundle.get("task_candidates") or []],
        "no_action_rule_ids": task_bundle.get("no_action_rule_ids") or [],
        "discipline": [
            "本文件故意不包含候选代码、候选数量、池大小或盘后叶子顺序",
            "任务必须由节点当前缺失功能决定，不能由是否容易选出股票决定",
        ],
    }


def select_task_pools(c1_decision: dict, candidate_pools: list[dict]) -> list[dict]:
    """Expose to Stage C2 only pools whose task IDs were frozen by Stage C1."""
    selected_ids = {
        (c1_decision.get(key) or {}).get("task_id")
        for key in ("primary_task", "alternative_task")
        if (c1_decision.get(key) or {}).get("status") == "SELECTED"
    }
    return [pool for pool in candidate_pools if pool.get("task_id") in selected_ids]
