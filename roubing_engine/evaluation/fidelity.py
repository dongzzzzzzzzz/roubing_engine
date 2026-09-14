"""Method-fidelity + time-discipline checks (plan §27.1-2). Deterministic audit
run over a stage_b/stage_c plan; complements the reasoning-side critic.
"""
from __future__ import annotations

from roubing_engine.warehouse import as_of as _asof
from roubing_engine.reasoning.schemas import ROLE_TO_FAMILY


GENERATOR_RULE = {
    "G1": "G01_SENTIMENT_TURN", "G2": "G02_COMPANION",
    "G3": "G03_SECOND_WAVE_UPGRADE", "G4": "G04_POST_LEADER_SUPPLEMENT",
    "G5": "G05_LOW_SYMBIOSIS", "G6": "G06_DIVERGENCE_REPAIR",
    "G7": "G07_CAPACITY_CORE", "G8": "G08_UNIQUENESS",
    "G9": "G09_CORE_SWITCH", "G10": "G10_HIGH_LOW_SWITCH",
    "G11": "G11_BOTTOM_ACTIVE", "G12": "G12_FIRST_ACTIVE_DIVERGENCE",
}

FORBIDDEN_IRREVERSIBLE_PATH_TEXT = (
    "后续不能反转", "不抹掉既有高度优势", "不抹掉已由最高高度",
    "最高板先建立永久优势", "高度建立的相对优先级", "高度不可逆",
    "前一层已拉开",
)


def _date_text(value) -> str | None:
    text = str(value or "").strip()
    digits = text[:8]
    if len(digits) == 8 and digits.isdigit():
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    return text[:10] or None


def check_stage_b(stage_b: dict, facts: dict | None = None) -> list[str]:
    """Verify full direction coverage and fact-grounded path selection."""
    if not facts:
        return []
    violations: list[str] = []
    catalog = facts.get("fact_catalog") or {}

    def check_refs(label: str, refs: list[str] | None, allowed_scope: set[str] | None = None):
        for ref in refs or []:
            if ref not in catalog:
                violations.append(f"{label}: 引用了不存在的 fact_id {ref}")
            elif allowed_scope and catalog[ref].get("scope") not in allowed_scope:
                violations.append(f"{label}: fact_id {ref} 的证据层级不匹配")

    environment = stage_b.get("environment") or {}
    check_refs("environment.supporting_fact_ids", environment.get("supporting_fact_ids"),
               {"ENVIRONMENT", "DIRECTION", "DIRECTION_FEEDBACK", "CONTEXT"})
    check_refs("environment.counter_fact_ids", environment.get("counter_fact_ids"),
               {"ENVIRONMENT", "DIRECTION", "DIRECTION_FEEDBACK", "CONTEXT"})
    if not (environment.get("supporting_fact_ids") or environment.get("counter_fact_ids")):
        violations.append("environment: 缺少任何可追溯 fact_id")
    if not environment.get("rule_ids"):
        violations.append("environment: 缺少方法 rule_ids")
    previous_state = facts.get("previous_state_summary") or {}
    previous_buyer = facts.get("previous_buyer_feedback") or {}
    historical_environment_available = bool(
        previous_state.get("available") or previous_buyer.get("available")
    )
    if not historical_environment_available and environment.get("status") != "DATA_INSUFFICIENT":
        violations.append(
            "environment: 缺前日账本和昨日买方反馈时不得确认轮动/退潮/切换/历史主流，"
            "必须降级为 DATA_INSUFFICIENT")
    if not previous_state.get("available") and environment.get("migrated_from") is not None:
        violations.append("environment.migrated_from: 无前日账本时必须为 null")

    source_directions = {
        item.get("theme"): item for item in (facts.get("direction_state_facts") or [])
    }
    evaluations = stage_b.get("direction_evaluations") or []
    output_themes = [item.get("theme") for item in evaluations]
    if len(output_themes) != len(set(output_themes)):
        violations.append("direction_evaluations: 同一方向重复输出")
    missing = sorted(set(source_directions) - set(output_themes))
    extra = sorted(set(output_themes) - set(source_directions))
    if missing:
        violations.append(f"direction_evaluations: 遗漏方向 {missing}")
    if extra:
        violations.append(f"direction_evaluations: 输出了事实包不存在的方向 {extra}")
    for item in evaluations:
        theme = item.get("theme")
        source = source_directions.get(theme)
        if source and item.get("direction_fact_id") != source.get("fact_id"):
            violations.append(f"方向 {theme}: direction_fact_id 与事实包不一致")
        if source and source.get("fact_id") not in set(
                (item.get("supporting_fact_ids") or [])
                + (item.get("counter_fact_ids") or [])):
            violations.append(f"方向 {theme}: 未引用自身 direction fact_id")
        check_refs(f"方向 {theme}.supporting_fact_ids", item.get("supporting_fact_ids"))
        check_refs(f"方向 {theme}.counter_fact_ids", item.get("counter_fact_ids"))
        if not item.get("rule_ids"):
            violations.append(f"方向 {theme}: 缺少方法 rule_ids")

    retained = [item for item in evaluations
                if item.get("path_status") in {"PRIMARY", "COMPETITOR"}]
    retained_themes = {item.get("theme") for item in retained if item.get("theme")}
    comparisons = stage_b.get("direction_comparisons") or []
    comparison_by_pair: dict[frozenset[str], dict] = {}
    for index, item in enumerate(comparisons):
        left, right = item.get("left_theme"), item.get("right_theme")
        if left == right:
            violations.append(f"direction_comparisons[{index}]: 左右方向不得相同")
            continue
        if left not in source_directions or right not in source_directions:
            violations.append(f"direction_comparisons[{index}]: 包含事实包不存在的方向")
        key = frozenset((left, right))
        if key in comparison_by_pair:
            violations.append(f"direction_comparisons[{index}]: 方向对重复比较")
        comparison_by_pair[key] = item
        if len(item.get("dimensions") or []) < 2:
            violations.append(f"direction_comparisons[{index}]: 至少比较两个真实维度")
        if not item.get("rule_ids"):
            violations.append(f"direction_comparisons[{index}]: 缺少方法 rule_ids")
        check_refs(f"direction_comparisons[{index}].supporting_fact_ids",
                   item.get("supporting_fact_ids"))
        check_refs(f"direction_comparisons[{index}].counter_fact_ids",
                   item.get("counter_fact_ids"))
    retained_list = sorted(retained_themes)
    for offset, left in enumerate(retained_list):
        for right in retained_list[offset + 1:]:
            if frozenset((left, right)) not in comparison_by_pair:
                violations.append(f"direction_comparisons: 缺少保留方向 {left} 与 {right} 的直接比较")

    path = stage_b.get("primary_path") or {}
    check_refs("primary_path.supporting_fact_ids", path.get("supporting_fact_ids"))
    check_refs("primary_path.counter_fact_ids", path.get("counter_fact_ids"))
    primary_rows = [item for item in evaluations if item.get("path_status") == "PRIMARY"]
    comparison = facts.get("path_comparison_contract") or {}
    if path.get("status") == "BLOCKED_DATA" \
            and comparison.get("cross_section_comparison_available"):
        violations.append(
            "primary_path: 当日方向事件数和梯队具备最低横向比较条件时不得仅因历史/扩散/"
            "分时缺失写 BLOCKED_DATA；无差异用 NONE，有逐层淘汰优势用 SELECTED")
    if path.get("status") == "SELECTED":
        if len(primary_rows) != 1:
            violations.append("primary_path=SELECTED 时 direction_evaluations 必须恰有一个 PRIMARY")
        elif path.get("theme") != primary_rows[0].get("theme"):
            violations.append("primary_path.theme 与 PRIMARY 方向不一致")
        source = source_directions.get(path.get("theme"))
        if not source or path.get("direction_fact_id") != source.get("fact_id"):
            violations.append("primary_path.direction_fact_id 与选中方向事实不一致")
        if source and source.get("fact_id") not in set(path.get("supporting_fact_ids") or []):
            violations.append("primary_path: 选中主路径未引用自身方向事实")
        if not path.get("rule_ids"):
            violations.append("primary_path: 缺少方法 rule_ids")
        primary_theme = path.get("theme")
        for competitor in sorted(retained_themes - {primary_theme}):
            relation = comparison_by_pair.get(frozenset((primary_theme, competitor))) or {}
            expected = ("LEFT_DOMINATES" if relation.get("left_theme") == primary_theme
                        else "RIGHT_DOMINATES")
            if relation.get("relation") != expected:
                violations.append(
                    f"primary_path: {primary_theme} 未在多维直接比较中支配 {competitor}，"
                    "不得强行 SELECTED，应输出 NONE")
    else:
        if primary_rows:
            violations.append("primary_path 未选中时不得存在 PRIMARY 方向")
        if path.get("theme") is not None or path.get("direction_fact_id") is not None:
            violations.append("primary_path 未选中时 theme/direction_fact_id 必须为 null")

    observation_codes = {
        item.get("thscode") for item in facts.get("stage_b_observation_universe") or []
    }
    observations = facts.get("stage_b_observation_universe") or []
    direction_fact_by_theme = {
        theme: source.get("fact_id") for theme, source in source_directions.items()
    }
    node_ids: set[str] = set()
    for index, node in enumerate(stage_b.get("nodes") or []):
        node_id = node.get("node_id")
        if node_id in node_ids:
            violations.append(f"nodes[{index}]: node_id 重复")
        if node_id:
            node_ids.add(node_id)
        check_refs(f"nodes[{index}].trigger_fact_ids", node.get("trigger_fact_ids"))
        if node.get("trigger_facts") and not node.get("trigger_fact_ids"):
            violations.append(f"nodes[{index}]: 有触发叙述但无 trigger_fact_ids")
        if node.get("theme") and node.get("theme") not in source_directions:
            violations.append(f"nodes[{index}]: theme 不在方向事实中")
        if not node.get("rule_ids"):
            violations.append(f"nodes[{index}]: 缺少方法 rule_ids")
        action_status = node.get("action_status")
        generator = node.get("generator")
        if action_status == "ACTION_READY" and not generator:
            violations.append(f"nodes[{index}]: ACTION_READY 必须有 generator")
        if action_status != "ACTION_READY" and generator:
            violations.append(
                f"nodes[{index}]: 非 ACTION_READY 节点不得保留 generator 形成隐性动作池")
        if generator and GENERATOR_RULE.get(generator) not in set(node.get("rule_ids") or []):
            violations.append(f"nodes[{index}]: generator {generator} 未引用对应生成规则")
        node_type = str(node.get("node_type") or "").upper()
        trigger_text = " ".join(node.get("trigger_facts") or [])
        if generator == "G6":
            if not ({"DIVERGENCE", "REPAIR"} & set(node_type.split("_"))) or \
                    "分歧" not in trigger_text or not any(
                        marker in trigger_text for marker in ("此前主流", "原主流", "强分支")):
                violations.append(
                    f"nodes[{index}]: G6 必须明确此前主流/强分支、板块级大分歧和修复节点前态")
        if generator == "G7":
            if "CAPACITY" not in node_type or not all((
                    any(marker in trigger_text for marker in ("大分歧", "放量分歧")),
                    any(marker in trigger_text for marker in ("修复", "反包", "继续推进")),
                    any(marker in trigger_text for marker in ("带动", "板块响应", "共振")),
            )):
                violations.append(
                    f"nodes[{index}]: G7 不能由成交额或板位推出，必须有分歧后推进和板块带动事实")
        if generator == "G8":
            if "UNIQUENESS" not in node_type or not any(
                    marker in trigger_text for marker in
                    ("共同首板", "同日起步", "共同起步", "同一起算日")):
                violations.append(f"nodes[{index}]: G8 必须有明确同一起算日和同功能队列")
            if node.get("anchor_date") == _date_text(stage_b.get("as_of")) \
                    and action_status == "ACTION_READY":
                violations.append(
                    f"nodes[{index}]: G8 起算日当天只能建立唯一性观察组，"
                    "不得 ACTION_READY 或生成次日动作任务")
        if generator in {"G3", "G12"} and not (node.get("candidate_ids") or []):
            violations.append(f"nodes[{index}]: {generator} 单票/既有角色节点必须明确 candidate_ids")
        scope = node.get("candidate_scope") or {}
        scope_ids = set(scope.get("candidate_ids") or [])
        validation_ids = set(scope.get("validation_ids") or [])
        if scope_ids & validation_ids:
            violations.append(f"nodes[{index}]: 动作候选与验证对象不得重叠")
        if action_status == "ACTION_READY" and not any((
                scope.get("event_statuses"), scope.get("board_levels"),
                scope.get("sub_directions"), scope_ids)):
            violations.append(f"nodes[{index}]: ACTION_READY 缺少可执行 candidate_scope")
        if not scope.get("scope_reason"):
            violations.append(f"nodes[{index}]: candidate_scope 缺 scope_reason")
        explicit_node_ids = set(node.get("candidate_ids") or [])
        if generator in {"G3", "G12"} and explicit_node_ids != scope_ids:
            violations.append(f"nodes[{index}]: G3/G12 的明确候选必须与 candidate_scope 一致")
        if generator not in {"G3", "G12"} and explicit_node_ids:
            violations.append(f"nodes[{index}]: 非单票节点不得在顶层 candidate_ids 预选赢家")
        theme_fact = direction_fact_by_theme.get(node.get("theme"))
        valid_theme_codes = {
            row.get("thscode") for row in observations
            if row.get("direction_fact_id") == theme_fact
        }
        for code in explicit_node_ids | scope_ids | validation_ids:
            if code not in observation_codes:
                violations.append(f"nodes[{index}]: candidate_id {code} 不在事实观察集")
            elif code not in valid_theme_codes:
                violations.append(f"nodes[{index}]: candidate_id {code} 不属于节点方向")

    stage_text = str(stage_b)
    for marker in FORBIDDEN_IRREVERSIBLE_PATH_TEXT:
        if marker in stage_text:
            violations.append(f"Stage B 使用了高度/前层不可逆优先级措辞: {marker}")
    return violations


FORBIDDEN_TASK_SELECTION_TEXT = (
    "候选只有", "候选更少", "候选少于", "容易收敛", "容易输出",
    "更容易选", "其他任务太多", "股票太多", "难比较", "池只有",
    "pool_size", "SINGLE更容易", "PAIR更容易",
)


def check_task_selection(stage_b: dict, decision: dict, task_bundle: dict,
                         facts: dict) -> list[str]:
    """Validate C1 without ever using candidate rows or pool sizes."""
    violations: list[str] = []
    tasks = {item.get("task_id"): item
             for item in task_bundle.get("task_candidates") or []}
    catalog = facts.get("fact_catalog") or {}
    primary_theme = (stage_b.get("primary_path") or {}).get("theme")
    no_action_rules = set(task_bundle.get("no_action_rule_ids") or [])

    for field, path_kind in (("primary_task", "PRIMARY"),
                             ("alternative_task", "ALTERNATIVE")):
        selected = decision.get(field) or {}
        if selected.get("path_kind") != path_kind:
            violations.append(f"{field}.path_kind 必须为 {path_kind}")
        same_path_ids = {
            task_id for task_id, task in tasks.items()
            if task.get("path_kind") == path_kind and task.get("status") == "ACTION_READY"
        }
        task_id = selected.get("task_id")
        status = selected.get("status")
        if status == "SELECTED":
            task = tasks.get(task_id)
            if not task:
                violations.append(f"{field}: task_id 不在冻结任务摘要")
                continue
            if task.get("status") != "ACTION_READY":
                violations.append(f"{field}: 非 ACTION_READY 任务不得选择")
            if task.get("path_kind") != path_kind:
                violations.append(f"{field}: 任务不属于 {path_kind} 路径")
            for key in ("task_type", "theme", "node_id"):
                if selected.get(key) != task.get(key):
                    violations.append(f"{field}.{key} 与冻结任务不一致")
            if path_kind == "PRIMARY" and task.get("theme") != primary_theme:
                violations.append("primary_task: 方向与 Stage B 主路径不一致")
            refs = set(selected.get("supporting_fact_ids") or [])
            if not refs or not refs.intersection(task.get("eligibility_fact_ids") or []):
                violations.append(f"{field}: 未引用节点/方向冻结资格事实")
            for ref in refs:
                if ref not in catalog:
                    violations.append(f"{field}: fact_id {ref} 不存在")
            required_rules = set(task.get("required_rule_ids") or [])
            if not required_rules.issubset(set(selected.get("rule_ids") or [])):
                violations.append(f"{field}: 未完整引用任务 required_rule_ids")
            expected_rejected = same_path_ids - {task_id}
        else:
            if task_id is not None or selected.get("task_type") is not None \
                    or selected.get("theme") is not None or selected.get("node_id") is not None:
                violations.append(f"{field}: 未选中时任务身份字段必须为 null")
            expected_rejected = same_path_ids
            cited_rules = set(selected.get("rule_ids") or [])
            if not no_action_rules:
                violations.append(f"{field}: 系统缺少可追溯的不行动规则合同")
            elif not no_action_rules.issubset(cited_rules):
                violations.append(f"{field}: NONE/BLOCKED_DATA 未完整引用 no_action_rule_ids")
        if set(selected.get("rejected_task_ids") or []) != expected_rejected:
            violations.append(f"{field}.rejected_task_ids 未完整覆盖同路径其他动作任务")
        selection_text = " ".join(selected.get("selection_logic") or [])
        for marker in FORBIDDEN_TASK_SELECTION_TEXT:
            if marker in selection_text:
                violations.append(f"{field}: 使用了按候选数量/易收敛度选任务的非法理由 `{marker}`")
        if not selected.get("missing_function"):
            violations.append(f"{field}: 必须先写节点当前缺失功能")
    return violations


def check_role_relation(candidate: dict, source: dict, task_id: str) -> list[str]:
    """Keep independence, pushed-by-reference and role replacement distinct."""
    violations: list[str] = []
    code = candidate.get("thscode")
    agency = candidate.get("agency_event_model") or {}
    relation_state = agency.get("relation_state")
    role = candidate.get("role")
    role_status = candidate.get("role_status")
    previous_role = source.get("previous_role_task") or {}
    if role == "UNKNOWN" and role_status not in {"CANDIDATE", "UNKNOWN", "CANCELLED"}:
        violations.append(
            f"{task_id}/{code}: role=UNKNOWN 时 role_status 只能 CANDIDATE/UNKNOWN/CANCELLED")
    if role not in {None, "UNKNOWN"} and role_status in {"CANDIDATE", "UNKNOWN"}:
        violations.append(
            f"{task_id}/{code}: 已命名角色不能仍标为 CANDIDATE/UNKNOWN")
    if role_status == "CONFIRMED" and not previous_role.get("available"):
        violations.append(f"{task_id}/{code}: 缺旧角色前态不得确认 role_status=CONFIRMED")
    if role_status == "REPLACED" and relation_state != "ROLE_REPLACED":
        violations.append(f"{task_id}/{code}: role_status=REPLACED 缺 ROLE_REPLACED 事件链")
    if role_status == "CANCELLED" and candidate.get("output_tier") != "取消或不行动":
        violations.append(f"{task_id}/{code}: role_status=CANCELLED 必须同步取消动作资格")
    if relation_state == "ROLE_REPLACED":
        if agency.get("reference_task_id") != task_id:
            violations.append(f"{task_id}/{code}: 不同任务对象不得确认 ROLE_REPLACED")
        if not agency.get("role_replacement_basis"):
            violations.append(f"{task_id}/{code}: ROLE_REPLACED 缺功能迁移证据链")
        if not (source.get("previous_role_task") or {}).get("available"):
            violations.append(f"{task_id}/{code}: 缺旧角色前态不得确认 ROLE_REPLACED")
        if role_status != "REPLACED":
            violations.append(f"{task_id}/{code}: ROLE_REPLACED 必须同步 role_status=REPLACED")
    if relation_state == "PUSHED_BY_REFERENCE" and agency.get("conclusion") == "ACTIVE":
        violations.append(f"{task_id}/{code}: 被反推不能同时写主动")
    if relation_state == "INDEPENDENCE_NOT_CONFIRMED" and agency.get("conclusion") == "ACTIVE":
        violations.append(f"{task_id}/{code}: 独立性未确认不能同时写主动")
    return violations


def _new_task_plan_violations(stage_b: dict, stage_c: dict, task_bundle: dict,
                              candidate_pools: list[dict], facts: dict) -> list[str]:
    violations = check_stage_b(stage_b, facts)
    decision = stage_c.get("task_selection") or {}
    violations.extend(check_task_selection(stage_b, decision, task_bundle, facts))
    tasks = {item.get("task_id"): item
             for item in task_bundle.get("task_candidates") or []}
    pools = {item.get("task_id"): item for item in candidate_pools}
    selected_by_kind = {
        kind: (decision.get(field) or {})
        for kind, field in (("PRIMARY", "primary_task"),
                            ("ALTERNATIVE", "alternative_task"))
    }
    expected_ids = {
        item.get("task_id") for item in selected_by_kind.values()
        if item.get("status") == "SELECTED"
    }
    path_plans = stage_c.get("path_plans") or []
    plan_by_id = {(item.get("execution_task") or {}).get("task_id"): item
                  for item in path_plans}
    if set(plan_by_id) != expected_ids or len(plan_by_id) != len(path_plans):
        violations.append("path_plans 必须精确等于 C1 选中的任务，且不得重复")

    all_leaf_keys: set[tuple[str, str, str]] = set()
    path_leaf_keys: dict[str, list[tuple[str, str, str]]] = {}
    for task_id, path_plan in plan_by_id.items():
        task = tasks.get(task_id) or {}
        pool = pools.get(task_id) or {}
        execution = path_plan.get("execution_task") or {}
        path_kind = path_plan.get("path_kind")
        if path_kind != task.get("path_kind"):
            violations.append(f"{task_id}: path_kind 与冻结任务不一致")
        selected = selected_by_kind.get(path_kind) or {}
        for key in ("task_id", "task_type", "theme", "missing_function",
                    "selection_logic", "supporting_fact_ids", "rule_ids",
                    "rejected_task_ids"):
            if execution.get(key) != selected.get(key):
                violations.append(f"{task_id}: execution_task.{key} 未原样抄 C1")
        if pool.get("status") != "ACTION_READY":
            violations.append(f"{task_id}: 选中任务池不是 ACTION_READY")

        pool_rows = {row.get("thscode"): row for row in pool.get("pool") or []}
        validation_rows = {row.get("thscode"): row
                           for row in pool.get("validation_pool") or []}
        candidates = {row.get("thscode"): row
                      for row in path_plan.get("candidates") or []}
        excluded = {row.get("thscode"): row
                    for row in path_plan.get("excluded_candidates") or []}
        if set(pool_rows) != ((set(candidates) | set(excluded)) - set(validation_rows)):
            violations.append(f"{task_id}: pool 未被 candidates/excluded 完整唯一覆盖")
        if set(candidates) & set(excluded):
            violations.append(f"{task_id}: 同一股票同时保留和排除")
        if not set(validation_rows).issubset(candidates):
            violations.append(f"{task_id}: validation_pool 必须完整保留")

        required_rules = set(task.get("required_rule_ids") or [])
        action_members = set()
        for code, candidate in candidates.items():
            source = pool_rows.get(code) or validation_rows.get(code)
            if not source:
                violations.append(f"{task_id}/{code}: 不在冻结池")
                continue
            for key in ("name", "theme"):
                if candidate.get(key) != source.get(key):
                    violations.append(f"{task_id}/{code}: {key} 与冻结事实不一致")
            if candidate.get("task_id") != task_id:
                violations.append(f"{task_id}/{code}: task_id 不一致")
            if source.get("required_anchor_date") is not None and \
                    candidate.get("anchor_date") != source.get("required_anchor_date"):
                violations.append(f"{task_id}/{code}: 混淆节点起算日与股票启动日")
            if source.get("required_node_id") is not None and \
                    candidate.get("node_id") != source.get("required_node_id"):
                violations.append(f"{task_id}/{code}: node_id 与冻结节点不一致")
            if candidate.get("stock_start_date") != source.get("required_stock_start_date"):
                violations.append(f"{task_id}/{code}: stock_start_date 未原样抄股票自身启动日")
            relation = candidate.get("task_relation")
            if code in validation_rows and relation != "VALIDATION_ONLY":
                violations.append(f"{task_id}/{code}: 验证对象只能 VALIDATION_ONLY")
            if relation == "ACTION_COMPETITOR":
                action_members.add(code)
            violations.extend(check_role_relation(candidate, source, task_id))
            if candidate.get("letter_carrier") != "UNKNOWN":
                violations.append(f"{task_id}/{code}: 不得自动赋予 A/B/C/D")
            expected_family = ROLE_TO_FAMILY.get(candidate.get("role"))
            if expected_family and candidate.get("role_family") != expected_family:
                violations.append(f"{task_id}/{code}: role_family 与 role 不一致")
            evidence = set(candidate.get("evidence") or [])
            if source.get("fact_id") and source.get("fact_id") not in evidence:
                violations.append(f"{task_id}/{code}: 未引用自身事实")
            if required_rules and not required_rules.intersection(evidence):
                violations.append(f"{task_id}/{code}: 未引用任务规则")

        group = path_plan.get("competition_group") or {}
        if set(group.get("members") or []) != action_members:
            violations.append(f"{task_id}: competition_group 必须等于 ACTION_COMPETITOR 全集")
        if group.get("anchor_date") != task.get("anchor_date"):
            violations.append(f"{task_id}: competition_group 使用了错误节点起算日")
        if group.get("theme") != task.get("theme"):
            violations.append(f"{task_id}: competition_group.theme 与冻结任务不一致")
        expected_generator = (task.get("method_generators") or [None])[0]
        if group.get("generator") != expected_generator:
            violations.append(f"{task_id}: competition_group.generator 与冻结节点不一致")
        if required_rules and not required_rules.issubset(set(group.get("rule_ids") or [])):
            violations.append(f"{task_id}: competition_group 未完整引用任务规则")
        for code in action_members:
            candidate = candidates.get(code) or {}
            if not set(candidate.get("competitors") or []).issubset(action_members - {code}):
                violations.append(f"{task_id}/{code}: competitors 包含验证对象或不同任务股票")

        action = path_plan.get("action_plan") or {}
        status = action.get("status")
        primary, backup = action.get("primary"), action.get("backup")
        if status == "NO_ACTION":
            if primary is not None or backup is not None or action.get("task_id") is not None:
                violations.append(f"{task_id}: NO_ACTION 必须清空叶子和 task_id")
        elif status == "SINGLE":
            if not primary or backup is not None:
                violations.append(f"{task_id}: SINGLE 必须只有 primary")
        elif status == "CONDITIONAL_PAIR":
            if not primary or not backup:
                violations.append(f"{task_id}: CONDITIONAL_PAIR 必须有两只叶子")
        if status != "NO_ACTION" and len(action_members) > 2:
            violations.append(f"{task_id}: 三只以上同任务对象未决时必须 NO_ACTION")
        if status != "NO_ACTION" and action.get("task_id") != task_id:
            violations.append(f"{task_id}: action_plan.task_id 不一致")
        if set(action.get("validation_objects") or []) != set(validation_rows):
            violations.append(f"{task_id}: action_plan.validation_objects 未完整抄冻结验证池")
        if required_rules and not required_rules.issubset(set(action.get("rule_ids") or [])):
            violations.append(f"{task_id}: action_plan 未完整引用任务规则")
        leaf_codes = {leaf.get("thscode") for leaf in (primary, backup) if leaf}
        if status != "NO_ACTION" and leaf_codes != action_members:
            violations.append(f"{task_id}: 动作组必须完整收敛为叶子，不得盘中再选")
        for leaf in (primary, backup):
            if not leaf:
                continue
            if leaf.get("task_id") != task_id or leaf.get("path_kind") != path_kind:
                violations.append(f"{task_id}/{leaf.get('thscode')}: 叶子任务或路径不一致")
            key = (path_kind, task_id, leaf.get("thscode"))
            all_leaf_keys.add(key)
            path_leaf_keys.setdefault(path_kind, []).append(key)

        pairwise_rows = path_plan.get("pairwise_comparison") or []
        pair_contract = task.get("pair_preference_contract") or {}
        allowed_families = set(pair_contract.get("allowed_evidence_families") or [])
        for index, relation in enumerate(pairwise_rows):
            if relation.get("left_thscode") not in action_members or \
                    relation.get("right_thscode") not in action_members:
                violations.append(f"{task_id}: pairwise_comparison[{index}] 比较了组外对象")
            if required_rules and not required_rules.issubset(
                    set(relation.get("rule_ids") or [])):
                violations.append(f"{task_id}: pairwise_comparison[{index}] 未引用任务规则")
            for ref in relation.get("fact_ids") or []:
                if ref not in (facts.get("fact_catalog") or {}):
                    violations.append(f"{task_id}: pairwise_comparison[{index}] fact_id 不存在")
            families = set(relation.get("evidence_families") or [])
            if not families:
                violations.append(f"{task_id}: pairwise_comparison[{index}] 缺任务证据家庭")
            if allowed_families and not families.issubset(allowed_families):
                violations.append(
                    f"{task_id}: pairwise_comparison[{index}] 使用了任务合同之外的证据家庭")

        if status == "CONDITIONAL_PAIR" and pair_contract.get("status") == "SYMMETRIC_UNRESOLVED":
            primary_code = (primary or {}).get("thscode")
            backup_code = (backup or {}).get("thscode")
            decisive = [row for row in pairwise_rows
                        if {row.get("left_thscode"), row.get("right_thscode")} ==
                        {primary_code, backup_code}]
            if len(decisive) != 1:
                violations.append(
                    f"{task_id}: 对称未决两只若要排列主备，必须有且仅有一条直接逐对关系")
            else:
                relation = decisive[0]
                expected = ("LEFT_PRIMARY" if relation.get("left_thscode") == primary_code
                            else "RIGHT_PRIMARY")
                if relation.get("conclusion") != expected:
                    violations.append(
                        f"{task_id}: 对称未决合同没有形成支持 PRIMARY 的单边功能结论")
                primary_advantages = (relation.get("left_advantages") if expected == "LEFT_PRIMARY"
                                      else relation.get("right_advantages")) or []
                if not primary_advantages or not relation.get("fact_ids"):
                    violations.append(
                        f"{task_id}: PRIMARY 顺序缺功能优势或逐字段事实，不得强排")

        role_contract = task.get("role_assignment_contract") or {}
        if role_contract.get("leader_state") == "UNRESOLVED":
            leader = group.get("leader_state") or {}
            if leader.get("status") != "UNRESOLVED" or leader.get("thscode") is not None:
                violations.append(f"{task_id}: 角色前态不足时不得确认竞争组 leader")
            if group.get("uniqueness_status") != "UNRESOLVED":
                violations.append(f"{task_id}: 角色前态不足时唯一性必须 UNRESOLVED")
        for code in set(role_contract.get("required_unknown_codes") or []):
            candidate = candidates.get(code) or {}
            if candidate.get("role") != "UNKNOWN" or candidate.get("role_family") != "UNKNOWN":
                violations.append(f"{task_id}/{code}: 缺角色前态必须保持 UNKNOWN")
            if candidate.get("role_status") not in {"CANDIDATE", "UNKNOWN"}:
                violations.append(
                    f"{task_id}/{code}: 缺角色前态时 role_status 只能 CANDIDATE/UNKNOWN")

        if task.get("method_generators") == ["G8"] and task.get("anchor_date") == _date_text(
                stage_c.get("as_of")):
            if excluded:
                violations.append(f"{task_id}: G8 起算日不得排除同期候选")
            if action.get("status") != "NO_ACTION" and len(pool_rows) > 2:
                violations.append(f"{task_id}: G8 首日三只以上未形成唯一性，必须 NO_ACTION")
            for code, candidate in candidates.items():
                agency = candidate.get("agency_event_model") or {}
                if candidate.get("role") != "UNKNOWN" or candidate.get("role_family") != "UNKNOWN":
                    violations.append(f"{task_id}/{code}: G8 起算日不得提前确认角色")
                if candidate.get("role_status") not in {"CANDIDATE", "UNKNOWN"}:
                    violations.append(
                        f"{task_id}/{code}: G8 起算日 role_status 只能 CANDIDATE/UNKNOWN")
                if agency.get("conclusion") != "UNKNOWN" or agency.get("relation_state") not in {
                        "UNKNOWN", "INDEPENDENCE_NOT_CONFIRMED"}:
                    violations.append(f"{task_id}/{code}: G8 起算日不得确认主动、被反推或替代")
                if candidate.get("output_tier") != "待验证候选":
                    violations.append(f"{task_id}/{code}: G8 起算日只能是待验证候选")

    final = stage_c.get("final_action_plan") or {}
    refs = [final.get("primary_ref"), final.get("backup_ref")]
    ref_keys = {(ref.get("path_kind"), ref.get("task_id"), ref.get("thscode"))
                for ref in refs if ref}
    if not ref_keys.issubset(all_leaf_keys):
        violations.append("final_action_plan 引用了路径计划之外的动作叶子")
    status = final.get("status")
    if status == "NO_ACTION" and any(refs):
        violations.append("final_action_plan.NO_ACTION 必须无叶子")
    if status == "SINGLE" and (not refs[0] or refs[1]):
        violations.append("final_action_plan.SINGLE 必须只有 primary_ref")
    if status == "CONDITIONAL_PAIR" and (not refs[0] or not refs[1]):
        violations.append("final_action_plan.CONDITIONAL_PAIR 必须有两只叶子")
    if len(ref_keys) > 2:
        violations.append("最终计划最多两只冻结叶子")
    primary_path_leafs = path_leaf_keys.get("PRIMARY", [])
    alternative_leafs = path_leaf_keys.get("ALTERNATIVE", [])
    if len(primary_path_leafs) == 2 and alternative_leafs and any(
            ref and ref.get("path_kind") == "ALTERNATIVE" for ref in refs):
        violations.append("主路径内部已条件唯二时，不得再加入第三条替代动作叶子")
    if refs[1] and refs[1].get("path_kind") == "ALTERNATIVE":
        switch_text = final.get("switch_rule") or ""
        if "直接失败" not in switch_text or "独立" not in switch_text:
            violations.append("跨方向 BACKUP 必须要求主叶子直接失败且替代路径独立成立")
    stage_text = str(stage_c)
    for marker in FORBIDDEN_TASK_SELECTION_TEXT:
        if marker in stage_text:
            violations.append(f"Stage C 使用候选数量/易收敛度倒推任务: {marker}")
    return violations


def check_task_plan(stage_b: dict, stage_c: dict, task_bundle: dict,
                    candidate_pools: list[dict], facts: dict) -> dict:
    """Fidelity gate for the dynamic execution-task architecture."""
    if "path_plans" in stage_c:
        violations = _new_task_plan_violations(
            stage_b, stage_c, task_bundle, candidate_pools, facts)
        return {"n_violations": len(violations), "violations": violations,
                "verdict": "PASS" if not violations else "NEEDS_REVISION"}
    violations = check_stage_b(stage_b, facts)
    forbidden_keys = {
        "score", "total_score", "weighted_score", "probability", "win_rate",
        "position", "position_size", "allocation", "仓位",
    }

    def scan(value, path="$"):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in forbidden_keys:
                    violations.append(f"{path}.{key}: 禁止固定打分/概率/仓位输出")
                scan(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                scan(child, f"{path}[{index}]")

    scan(stage_c, "stage_c")
    tasks = {item.get("task_id"): item
             for item in task_bundle.get("task_candidates") or []}
    pools = {item.get("task_id"): item for item in candidate_pools}
    execution = stage_c.get("execution_task") or {}
    selected_id = execution.get("task_id")
    if execution.get("status") == "SELECTED":
        task = tasks.get(selected_id)
        pool = pools.get(selected_id)
        if not task or not pool:
            violations.append("execution_task: 选中的 task_id 不在冻结任务池")
        else:
            if execution.get("task_type") != task.get("task_type"):
                violations.append("execution_task.task_type 与 task_candidates 不一致")
            if execution.get("theme") != task.get("theme"):
                violations.append("execution_task.theme 与 task_candidates 不一致")
            if pool.get("status") != "READY":
                violations.append("execution_task: 候选池非 READY，不得选为执行任务")
            refs = set(execution.get("supporting_fact_ids") or [])
            if not refs:
                violations.append("execution_task: 选中任务缺 supporting_fact_ids")
            elif not refs.intersection(task.get("eligibility_fact_ids") or []):
                violations.append("execution_task: 未引用选中任务的冻结资格事实")
    elif selected_id is not None:
        violations.append("execution_task 未选中时 task_id 必须为 null")

    rejected = set(execution.get("rejected_task_ids") or [])
    expected_rejected = set(tasks) - ({selected_id} if selected_id else set())
    if rejected != expected_rejected:
        violations.append("execution_task.rejected_task_ids 未完整记录其他动态任务")

    selected_pool = pools.get(selected_id) or {}
    selected_task = tasks.get(selected_id) or {}
    required_rules = set(selected_task.get("required_rule_ids") or [])
    pool_rows = {row.get("thscode"): row for row in selected_pool.get("pool") or []}
    validation_rows = {row.get("thscode"): row
                       for row in selected_pool.get("validation_pool") or []}
    candidates = {row.get("thscode"): row for row in stage_c.get("candidates") or []}
    excluded = {row.get("thscode"): row
                for row in stage_c.get("excluded_candidates") or []}
    if selected_id:
        if set(pool_rows) != (set(candidates) | set(excluded)) - set(validation_rows):
            violations.append("选中任务 pool 未被 candidates/excluded 完整且唯一覆盖")
        if set(candidates) & set(excluded):
            violations.append("同一任务股票同时出现在 candidates 和 excluded_candidates")
        if not set(validation_rows).issubset(candidates):
            violations.append("validation_pool 对象必须保留为 candidates")
    elif candidates or excluded:
        violations.append("未选择 execution_task 时不得输出股票候选")

    for code, candidate in candidates.items():
        source = pool_rows.get(code) or validation_rows.get(code)
        if not source:
            violations.append(f"{code}: 不在选中任务的候选池或验证池")
            continue
        if candidate.get("task_id") != selected_id:
            violations.append(f"{code}: task_id 与 execution_task 不一致")
        if candidate.get("name") != source.get("name"):
            violations.append(f"{code}: name 与冻结事实不一致")
        if candidate.get("theme") != source.get("theme"):
            violations.append(f"{code}: theme 与冻结事实不一致")
        if (source.get("required_anchor_date") is not None and
                candidate.get("anchor_date") != source.get("required_anchor_date")):
            violations.append(f"{code}: anchor_date 与冻结事实的真实起算日不一致")
        if source.get("fact_id") and source.get("fact_id") not in set(candidate.get("evidence") or []):
            violations.append(f"{code}: evidence 未引用自己的股票 fact_id")
        if required_rules and not required_rules.intersection(candidate.get("evidence") or []):
            violations.append(f"{code}: evidence 未同时引用选中任务规则")
        if code in validation_rows and candidate.get("task_relation") != "VALIDATION_ONLY":
            violations.append(f"{code}: validation_pool 对象只能是 VALIDATION_ONLY")
        if candidate.get("letter_carrier") != "UNKNOWN":
            violations.append(f"{code}: 当前知识合同不允许自动赋予 A/B/C/D")
        expected_family = ROLE_TO_FAMILY.get(candidate.get("role"))
        if expected_family and candidate.get("role_family") != expected_family:
            violations.append(f"{code}: role_family 与 role 不一致")

    group = stage_c.get("action_competition_group") or {}
    action_members = {code for code, row in candidates.items()
                      if row.get("task_relation") == "ACTION_COMPETITOR"}
    if set(group.get("members") or []) != action_members:
        violations.append("action_competition_group.members 必须等于 ACTION_COMPETITOR 集合")
    if set(group.get("validation_objects") or []) != set(validation_rows):
        violations.append("action_competition_group.validation_objects 与冻结验证池不一致")
    if required_rules:
        rule_sections = {
            "execution_task": execution.get("rule_ids") or [],
            "action_competition_group": group.get("rule_ids") or [],
            "action_plan": (stage_c.get("action_plan") or {}).get("rule_ids") or [],
        }
        for label, values in rule_sections.items():
            if not required_rules.issubset(set(values)):
                violations.append(f"{label}: 未完整引用选中任务 required_rule_ids")
    pair_contract = (selected_task.get("pair_preference_contract") or
                     selected_pool.get("pair_preference_contract") or {})
    if pair_contract.get("status") == "SYMMETRIC_UNRESOLVED" and \
            (stage_c.get("action_plan") or {}).get("status") == "CONDITIONAL_PAIR":
        action_plan = stage_c.get("action_plan") or {}
        primary = (action_plan.get("primary") or {}).get("thscode")
        backup = (action_plan.get("backup") or {}).get("thscode")
        direct = [row for row in stage_c.get("pairwise_comparison") or []
                  if {row.get("left_thscode"), row.get("right_thscode")} ==
                  {primary, backup}]
        if len(direct) != 1:
            violations.append("对称未决两只缺唯一直接逐对关系，不能强排主备")
        else:
            relation = direct[0]
            expected = ("LEFT_PRIMARY" if relation.get("left_thscode") == primary
                        else "RIGHT_PRIMARY")
            if relation.get("conclusion") != expected:
                violations.append("逐对结论未形成支持 PRIMARY 的单边任务功能优势")
            families = set(relation.get("evidence_families") or [])
            allowed = set(pair_contract.get("allowed_evidence_families") or [])
            if not families or (allowed and not families.issubset(allowed)):
                violations.append("逐对排序缺任务允许的 evidence_families")
    matching_groups = [item for item in stage_c.get("competition_groups") or []
                       if set(item.get("members") or []) == action_members]
    if selected_task.get("anchor_date") and (not matching_groups or any(
            item.get("anchor_date") != selected_task.get("anchor_date")
            for item in matching_groups)):
        violations.append("动作竞争组未使用冻结任务的真实共同起算日")
    if required_rules:
        for item in matching_groups:
            if not required_rules.issubset(set(item.get("rule_ids") or [])):
                violations.append("competition_group: 未完整引用选中任务 required_rule_ids")
    role_contract = (selected_task.get("role_assignment_contract") or
                     selected_pool.get("role_assignment_contract") or {})
    required_unknown = set(role_contract.get("required_unknown_codes") or [])
    for code in required_unknown:
        candidate = candidates.get(code) or {}
        if candidate.get("role") != "UNKNOWN" or candidate.get("role_family") != "UNKNOWN":
            violations.append(f"{code}: 缺角色确认事实时 role/role_family 必须保持 UNKNOWN")
        if candidate.get("role_status") not in {"CANDIDATE", "UNKNOWN"}:
            violations.append(f"{code}: 缺角色确认事实时 role_status 只能 CANDIDATE/UNKNOWN")
    if role_contract.get("leader_state") == "UNRESOLVED":
        for item in matching_groups:
            leader = item.get("leader_state") or {}
            if leader.get("status") != "UNRESOLVED" or leader.get("thscode") is not None:
                violations.append("唯一性未确认时竞争组不得暂定或确认 leader")
            if item.get("uniqueness_status") != "UNRESOLVED":
                violations.append("角色未确认时竞争组 uniqueness_status 必须为 UNRESOLVED")
    for index, relation in enumerate(stage_c.get("pairwise_comparison") or []):
        left = relation.get("left_thscode")
        right = relation.get("right_thscode")
        if left not in action_members or right not in action_members:
            violations.append(f"pairwise_comparison[{index}]: 只能比较同任务动作竞争者")
        for ref in relation.get("fact_ids") or []:
            if ref not in (facts.get("fact_catalog") or {}):
                violations.append(f"pairwise_comparison[{index}]: fact_id {ref} 不存在")
        if required_rules and not required_rules.issubset(set(relation.get("rule_ids") or [])):
            violations.append(f"pairwise_comparison[{index}]: 未完整引用选中任务规则")
    return {"n_violations": len(violations), "violations": violations,
            "verdict": "PASS" if not violations else "NEEDS_REVISION"}


def check_plan(stage_b: dict, stage_c: dict, candidate_pools: list[dict] | None = None,
               facts: dict | None = None) -> dict:
    v = []
    forbidden_keys = {
        "score", "total_score", "weighted_score", "probability", "win_rate",
        "position", "position_size", "allocation", "仓位",
    }

    def scan(value, path="$" ):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in forbidden_keys:
                    v.append(f"{path}.{key}: 禁止固定打分/概率/仓位输出")
                scan(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                scan(child, f"{path}[{index}]")

    scan(stage_b, "stage_b")
    scan(stage_c, "stage_c")
    if not stage_b.get("environment"):
        v.append("缺市场环境判断(直接给个股?)")
    v.extend(check_stage_b(stage_b, facts))
    pools = candidate_pools or []
    pool_by_key = {
        (entry.get("generator"), entry.get("anchor_date"), entry.get("theme")): entry
        for entry in pools
    }
    allowed = {
        (entry.get("generator"), entry.get("anchor_date"), entry.get("theme"),
         stock.get("thscode"))
        for entry in pools for stock in (entry.get("pool") or [])
    }
    pool_rows = {
        (entry.get("generator"), entry.get("anchor_date"), entry.get("theme"),
         stock.get("thscode")): stock
        for entry in pools for stock in (entry.get("pool") or [])
    }
    eligible = {
        (entry.get("generator"), entry.get("anchor_date"), entry.get("theme"),
         stock.get("thscode"))
        for entry in pools if entry.get("status") in {"READY", "PARTIAL_DATA"}
        for stock in (entry.get("pool") or [])
    }
    node_keys = {
        (node.get("generator"), node.get("anchor_date"), node.get("theme"))
        for node in (stage_b.get("nodes") or []) if node.get("generator")
    }
    groups = {g.get("group_id"): g for g in stage_c.get("competition_groups", [])}
    reasoning_date = _date_text(stage_c.get("as_of"))
    for group_id, group in groups.items():
        group_key = (group.get("generator"), group.get("anchor_date"), group.get("theme"))
        group_pool = pool_by_key.get(group_key)
        if group_pool is None:
            v.append(f"竞争组 {group_id}: generator/anchor/theme 不对应唯一候选池")
            continue
        group_rows = {stock.get("thscode"): stock for stock in group_pool.get("pool") or []}
        for member in group.get("members", []):
            if member not in group_rows:
                v.append(f"竞争组 {group_id}: 成员 {member} 不在该组对应候选池")
        leader = group.get("leader_state") or {}
        if leader.get("thscode") is not None and leader.get("thscode") not in group.get("members", []):
            v.append(f"竞争组 {group_id}: leader {leader.get('thscode')} 不在组内")
        if group.get("generator") == "G8" and group.get("anchor_date") == reasoning_date:
            if leader.get("status") != "UNRESOLVED" or leader.get("thscode") is not None:
                v.append(f"竞争组 {group_id}: G8起算日当天不得确认或暂定leader")
            if group.get("uniqueness_status") != "UNRESOLVED":
                v.append(f"竞争组 {group_id}: G8起算日当天唯一性必须保持UNRESOLVED")
        for index, relation in enumerate(group.get("pairwise_relations") or []):
            left = relation.get("left_thscode")
            right = relation.get("right_thscode")
            if left not in group.get("members", []) or right not in group.get("members", []):
                v.append(f"竞争组 {group_id}: pairwise_relations[{index}] 引用了组外代码")
                continue
            left_fact = group_rows.get(left, {})
            right_fact = group_rows.get(right, {})
            left_time = left_fact.get("limit_time")
            right_time = right_fact.get("limit_time")
            if relation.get("left_event_time") != left_time:
                v.append(f"竞争组 {group_id}: {left} 事件时间与候选池不一致")
            if relation.get("right_event_time") != right_time:
                v.append(f"竞争组 {group_id}: {right} 事件时间与候选池不一致")
            expected = "UNRESOLVED"
            if left_time and right_time:
                expected = ("LEFT_EARLIER" if left_time < right_time else
                            "RIGHT_EARLIER" if right_time < left_time else "SAME_TIME")
            if relation.get("relation") not in {expected, "NOT_COMPARABLE"}:
                v.append(
                    f"竞争组 {group_id}: {left}/{right} 先后关系写反，事实应为 {expected}")
    for c in stage_c.get("candidates", []):
        code = c.get("thscode", "?")
        if not c.get("node"):
            v.append(f"{code}: 候选无节点/起算日")
        if not c.get("cancel_if") and not c.get("failure_signals"):
            v.append(f"{code}: 无取消条件")
        if not c.get("competition_group"):
            v.append(f"{code}: 无竞争组")
        elif c.get("competition_group") not in groups:
            v.append(f"{code}: competition_group 未定义为领域实体")
        else:
            group = groups[c.get("competition_group")]
            if code not in group.get("members", []):
                v.append(f"{code}: 不在其竞争组 members 中")
            for competitor in c.get("competitors", []):
                if competitor not in group.get("members", []):
                    v.append(f"{code}: 对手 {competitor} 不在同一竞争组")
        key = (c.get("generator"), c.get("anchor_date"), c.get("theme"))
        if c.get("competition_group") in groups:
            group = groups[c.get("competition_group")]
            if (group.get("generator"), group.get("anchor_date"), group.get("theme")) != key:
                v.append(f"{code}: competition_group 与候选 generator/anchor/theme 不一致")
        if key not in node_keys:
            v.append(f"{code}: generator/anchor/theme 未由 Stage B 节点打开")
        full_key = (*key, code)
        if full_key not in allowed:
            same_source = next((stock for (generator, anchor, _theme, stock_code), stock
                                in pool_rows.items()
                                if generator == c.get("generator")
                                and anchor == c.get("anchor_date")
                                and stock_code == code), None)
            if same_source and same_source.get("theme") != c.get("theme"):
                v.append(
                    f"{code}: theme 与候选池事实不一致"
                    f"（{c.get('theme')} != {same_source.get('theme')}）")
            else:
                v.append(f"{code}: 不在对应 generator/anchor/theme 的确定性候选池")
        else:
            source = pool_rows[full_key]
            if c.get("name") != source.get("name"):
                v.append(f"{code}: name 与候选池事实不一致（{c.get('name')} != {source.get('name')}）")
            if source.get("theme") and c.get("theme") != source.get("theme"):
                v.append(f"{code}: theme 与候选池事实不一致（{c.get('theme')} != {source.get('theme')}）")
            if not c.get("evidence"):
                v.append(f"{code}: 缺少逐字段事实证据")
            v.extend(check_role_relation(c, source, c.get("task_id") or "LEGACY_TASK"))
        pool_entry = pool_by_key.get(key, {})
        if pool_entry.get("status") == "PARTIAL_DATA" and c.get("output_tier") == "主候选":
            v.append(f"{code}: 候选池为 PARTIAL_DATA，不得升级为主候选")
        if c.get("letter_carrier") != "UNKNOWN":
            v.append(f"{code}: 当前知识合同不允许自动赋予 A/B/C/D")
        if c.get("generator") == "G8" and c.get("anchor_date") == reasoning_date:
            if c.get("role") != "UNKNOWN" or c.get("role_family") != "UNKNOWN":
                v.append(f"{code}: G8起算日当天不得提前确认角色")
            if c.get("role_status") not in {"CANDIDATE", "UNKNOWN"}:
                v.append(f"{code}: G8起算日当天 role_status 只能 CANDIDATE/UNKNOWN")
            agency = c.get("agency_event_model") or {}
            if agency.get("data_sufficiency") == "SUFFICIENT" or agency.get("conclusion") != "UNKNOWN":
                v.append(f"{code}: G8起算日当天只有日线/封板时点，不足以确认主动或被动")
            if c.get("output_tier") != "待验证候选":
                v.append(f"{code}: G8起算日当天只能输出待验证候选")
        expected_family = ROLE_TO_FAMILY.get(c.get("role"))
        if expected_family and c.get("role_family") != expected_family:
            v.append(f"{code}: role_family={c.get('role_family')} 与 role={c.get('role')} 不一致")
    selected = {
        (candidate.get("generator"), candidate.get("anchor_date"), candidate.get("theme"),
         candidate.get("thscode"))
        for candidate in stage_c.get("candidates", [])
    }
    excluded = {
        (candidate.get("generator"), candidate.get("anchor_date"), candidate.get("theme"),
         candidate.get("thscode"))
        for candidate in stage_c.get("excluded_candidates", [])
    }
    for candidate in stage_c.get("excluded_candidates", []):
        key = (candidate.get("generator"), candidate.get("anchor_date"),
               candidate.get("theme"), candidate.get("thscode"))
        source = pool_rows.get(key)
        if source and candidate.get("name") != source.get("name"):
            v.append(f"{candidate.get('thscode')}: 排除项 name 与候选池事实不一致")
        if candidate.get("generator") == "G8" and candidate.get("anchor_date") == reasoning_date:
            v.append(f"{candidate.get('thscode')}: G8起算日当天不得排除同期成员，必须留待次日竞争")
    for key in sorted(eligible - selected - excluded, key=str):
        v.append(f"候选池成员未保留选择/排除决定: {key}")
    for key in sorted((selected | excluded) - eligible, key=str):
        v.append(f"选择/排除记录不属于 READY/PARTIAL_DATA 候选池: {key}")
    for key in sorted(selected & excluded, key=str):
        v.append(f"同一候选同时被选择和排除: {key}")
    paths = stage_c.get("paths", {})
    for k in ("primary", "alternative", "no_action"):
        if k not in paths:
            v.append(f"缺路径:{k}")
    completeness = (facts or {}).get("data_completeness") or {}
    tick_available = bool((completeness.get("trade_tick") or {}).get("available"))
    buyer_feedback_available = bool(
        ((facts or {}).get("previous_buyer_feedback") or {}).get("available"))
    for path_name in ("primary", "alternative"):
        path = paths.get(path_name) or {}
        for claim_name in ("capital_source", "buyer", "seller", "destination_layer", "successor"):
            claim = path.get(claim_name) or {}
            if claim.get("status") == "SUPPORTED" and not claim.get("evidence"):
                v.append(f"路径 {path_name}.{claim_name}: SUPPORTED 必须有直接证据")
        if not tick_available or not buyer_feedback_available:
            for claim_name in ("capital_source", "buyer", "seller"):
                if (path.get(claim_name) or {}).get("status") == "SUPPORTED":
                    v.append(
                        f"路径 {path_name}.{claim_name}: 缺逐笔或昨日买方反馈，"
                        "只能写HYPOTHESIS/UNKNOWN")
    return {"n_violations": len(v), "violations": v,
            "verdict": "PASS" if not v else "NEEDS_REVISION"}


def check_time_discipline(input_dates: list[str], as_of_date: str) -> dict:
    return _asof.audit_reasoning_inputs(input_dates, as_of_date)
