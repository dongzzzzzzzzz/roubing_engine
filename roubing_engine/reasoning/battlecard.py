"""Render the human-executable 次日作战卡 from Stage B + Stage C outputs.

The morning is mechanical: observe -> match -> execute/skip. Each candidate
card lists 竞价/开盘 confirm & cancel conditions in observable terms.
"""
from __future__ import annotations


def _bullets(items, indent="  "):
    if not items:
        return f"{indent}- （无）"
    return "\n".join(f"{indent}- {x}" for x in items)


def _claim(label: str, value: dict | None) -> str:
    item = value or {}
    evidence = "；".join(item.get("evidence") or ["无直接证据"])
    return f"  - {label} [{item.get('status')}]: {item.get('statement')}（依据：{evidence}）"


def _pairwise(items: list[dict] | None) -> list[str]:
    return [
        f"{item.get('left_thscode')}({item.get('left_event_time')}) / "
        f"{item.get('right_thscode')}({item.get('right_event_time')}): "
        f"{item.get('relation')}"
        for item in (items or [])
    ]


def render(trade_date: str, stage_b: dict, stage_c: dict) -> str:
    env = stage_b.get("environment", {})
    path_plans = stage_c.get("path_plans") or []
    if path_plans:
        paths = {plan.get("path_kind", "").lower(): plan.get("path_analysis") or {}
                 for plan in path_plans}
        paths["no_action"] = {
            "observed_facts": ["盘后已冻结正式不行动分支"],
            "ai_inferences": [], "unknowns": stage_c.get("unknowns") or [],
            "trigger": (stage_c.get("final_action_plan") or {}).get("no_action_conditions") or [],
        }
        groups = [plan.get("competition_group") or {} for plan in path_plans]
        candidates = [row for plan in path_plans for row in plan.get("candidates") or []]
        excluded_candidates = [row for plan in path_plans
                               for row in plan.get("excluded_candidates") or []]
    else:
        paths = stage_c.get("paths", {})
        groups = stage_c.get("competition_groups", [])
        candidates = stage_c.get("candidates", [])
        excluded_candidates = stage_c.get("excluded_candidates", [])
    L = [f"# {trade_date} 次日作战卡（盘前定案，盘中只对照执行）", ""]

    L += ["## 0. 信息边界与数据缺口",
          f"- as_of：{stage_b.get('as_of')}",
          f"- 数据缺口：{'；'.join(stage_b.get('data_gaps', []) or ['无'])}", ""]

    L += ["## 1. 市场环境",
          f"- 环境状态：{env.get('status', env.get('candidate'))}（昨日：{env.get('migrated_from')}）",
          "- 推演：", _bullets(env.get("reasoning"), "  "),
          f"- 支持事实ID：{'、'.join(env.get('supporting_fact_ids', []) or ['无'])}",
          f"- 反证事实ID：{'、'.join(env.get('counter_fact_ids', []) or ['无'])}",
          "- 明日验证：", _bullets(env.get("tomorrow_checks"), "  "), ""]

    primary = stage_b.get("primary_path") or {}
    L += ["## 2. 动态主路径",
          f"- 状态：{primary.get('status')} / {primary.get('theme')}",
          "- 选择逻辑：", _bullets(primary.get("selection_logic"), "  "),
          f"- 竞争方向：{'、'.join(primary.get('competitor_themes', []) or ['无'])}", "",
          "## 2.1 全部方向比较"]
    for d in stage_b.get("direction_evaluations", []):
        L += [f"### {d.get('theme')} — {d.get('path_status')} / {d.get('stage')}",
              f"- 市场关系：{d.get('market_relation')}",
              "- 已观察：", _bullets(d.get("observed_facts"), "  "),
              "- 推断：", _bullets(d.get("inferences"), "  "),
              f"- 竞争方向：{'、'.join(d.get('competitors', []) or ['无'])}", ""]

    L += ["## 3. 今日节点"]
    for n in stage_b.get("nodes", []):
        L += [f"- [{n.get('generator')}] {n.get('node_type')}（起算 {n.get('anchor_date')}）",
              "  - 触发：", _bullets(n.get("trigger_facts"), "    "),
              "  - 确认：", _bullets(n.get("confirm"), "    "),
              "  - 取消：", _bullets(n.get("cancel"), "    ")]
    L += [""]

    primary = paths.get("primary", {})
    alternative = paths.get("alternative", {})
    no_action = paths.get("no_action", {})
    L += ["## 4. 三路径（事实、推断和未知分离）",
          "### 主路径",
          "- 已观察事实：", _bullets(primary.get("observed_facts"), "  "),
          "- AI推断：", _bullets(primary.get("ai_inferences"), "  "),
          "- 未知：", _bullets(primary.get("unknowns"), "  "),
          _claim("资金来源", primary.get("capital_source")),
          _claim("潜在买方", primary.get("buyer")),
          _claim("潜在卖方", primary.get("seller")),
          _claim("可能落点", primary.get("destination_layer")),
          _claim("可能接棒者", primary.get("successor")),
          "  - 确认：", _bullets(paths.get("primary", {}).get("confirm"), "  "),
          "  - 取消：", _bullets(paths.get("primary", {}).get("cancel"), "  "),
          "### 替代路径",
          "- 已观察事实：", _bullets(alternative.get("observed_facts"), "  "),
          "- AI推断：", _bullets(alternative.get("ai_inferences"), "  "),
          "- 未知：", _bullets(alternative.get("unknowns"), "  "),
          _claim("资金来源", alternative.get("capital_source")),
          _claim("潜在买方", alternative.get("buyer")),
          _claim("潜在卖方", alternative.get("seller")),
          _claim("可能落点", alternative.get("destination_layer")),
          _claim("可能接棒者", alternative.get("successor")),
          "  - 触发：", _bullets(paths.get("alternative", {}).get("trigger"), "  "),
          "  - 取消：", _bullets(paths.get("alternative", {}).get("cancel"), "  "),
          "### 不行动",
          "- 已观察事实：", _bullets(no_action.get("observed_facts"), "  "),
          "- AI推断：", _bullets(no_action.get("ai_inferences"), "  "),
          "- 未知：", _bullets(no_action.get("unknowns"), "  "),
          "- 不行动触发：", _bullets(no_action.get("trigger"), "  "), ""]

    L += ["## 5. 真实竞争组"]
    for group in groups:
        leader = group.get("leader_state") or {}
        L += [f"### {group.get('group_id')} — {leader.get('status')} / {leader.get('thscode')}",
              f"- 可比依据：{'；'.join(group.get('comparison_basis', []) or ['无'])}",
              f"- 成员：{'、'.join(group.get('members', []) or ['无'])}",
              "- 两两关系：", _bullets(_pairwise(group.get("pairwise_relations")), "  "),
              "- 次日确认：", _bullets(group.get("next_confirmation"), "  "), ""]

    if path_plans:
        action = stage_c.get("final_action_plan") or {}
        L += ["## 6. 主/替代执行任务与封闭动作计划"]
        for plan in path_plans:
            execution = plan.get("execution_task") or {}
            L += [f"- {plan.get('path_kind')}：{execution.get('task_type')} / {execution.get('task_id')}",
                  f"  - 缺失功能：{execution.get('missing_function')}",
                  "  - 任务选择逻辑：", _bullets(execution.get("selection_logic"), "    ")]
        L += [f"- 最终动作计划：{action.get('status')}",
              f"- PRIMARY：{(action.get('primary_ref') or {}).get('thscode')}",
              f"- BACKUP：{(action.get('backup_ref') or {}).get('thscode')}",
              f"- 切换规则：{action.get('switch_rule')}",
              "- 放弃条件：", _bullets(action.get("no_action_conditions"), "  "), ""]
    else:
        execution = stage_c.get("execution_task") or {}
        action = stage_c.get("action_plan") or {}
        L += ["## 6. 明日唯一执行任务与封闭动作计划",
              f"- 执行任务：{execution.get('status')} / {execution.get('task_type')} / {execution.get('task_id')}",
              f"- 主路径缺少功能：{execution.get('missing_function')}",
              "- 任务选择逻辑：", _bullets(execution.get("selection_logic"), "  "),
              f"- 动作计划：{action.get('status')}",
              f"- PRIMARY：{(action.get('primary') or {}).get('thscode')}",
              f"- BACKUP：{(action.get('backup') or {}).get('thscode')}",
              f"- 验证对象（不可买）：{'、'.join(action.get('validation_objects', []) or ['无'])}",
              f"- 切换规则：{action.get('switch_rule')}",
              "- 放弃条件：", _bullets(action.get("no_action_conditions"), "  "), ""]

    L += ["## 7. 候选功能与任务卡"]
    tier_order = {"主候选": 0, "待验证候选": 1, "替代候选": 2, "取消或不行动": 3}
    cands = sorted(candidates,
                   key=lambda c: tier_order.get(c.get("output_tier"), 9))
    for c in cands:
        L += [f"### [{c.get('task_relation')}] {c.get('thscode')} {c.get('name')} — {c.get('observed_function')} @ {c.get('theme')}",
              f"- 节点/起算：{c.get('node')}  | 竞争组：{c.get('competition_group')}"
              f"  | 对手：{'、'.join(c.get('competitors', []) or ['无'])}"
              f"  | 字母载体：{c.get('letter_carrier', 'UNKNOWN')}",
              "- 今日状态：", _bullets(c.get("observed_state")),
              "- 次日必须完成：", _bullets(c.get("tomorrow_must_do")),
              "- 可接受变体：", _bullets(c.get("acceptable_variants")),
              "- 失败信号（出现即降级/取消）：", _bullets(c.get("failure_signals")),
              "- 直接取消：", _bullets(c.get("cancel_if")),
              f"- 依据：{'、'.join(c.get('evidence', []) or [])}", ""]

    L += ["## 8. 同任务排除候选（保留负样本）"]
    for candidate in excluded_candidates:
        L.append(
            f"- {candidate.get('thscode')} {candidate.get('name')} [{candidate.get('generator')}/"
            f"{candidate.get('anchor_date')}]：{candidate.get('reason')}")
    if not excluded_candidates:
        L.append("- （无）")
    L.append("")

    L += ["## 9. 未知与方法缺口", _bullets(stage_c.get("unknowns")), ""]
    return "\n".join(L)
