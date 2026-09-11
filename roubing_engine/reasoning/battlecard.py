"""Render the human-executable 次日作战卡 from Stage B + Stage C outputs.

The morning is mechanical: observe -> match -> execute/skip. Each candidate
card lists 竞价/开盘 confirm & cancel conditions in observable terms.
"""
from __future__ import annotations


def _bullets(items, indent="  "):
    if not items:
        return f"{indent}- （无）"
    return "\n".join(f"{indent}- {x}" for x in items)


def render(trade_date: str, stage_b: dict, stage_c: dict) -> str:
    env = stage_b.get("environment", {})
    L = [f"# {trade_date} 次日作战卡（盘前定案，盘中只对照执行）", ""]

    L += ["## 0. 信息边界与数据缺口",
          f"- as_of：{stage_b.get('as_of')}",
          f"- 数据缺口：{'；'.join(stage_b.get('data_gaps', []) or ['无'])}", ""]

    L += ["## 1. 市场环境",
          f"- 环境候选：{env.get('candidate')}（昨日：{env.get('migrated_from')}）",
          "- 支持：", _bullets(env.get("supporting"), "  "),
          "- 反证：", _bullets(env.get("counter"), "  "),
          "- 明日验证：", _bullets(env.get("tomorrow_checks"), "  "), ""]

    L += ["## 2. 主流方向"]
    for d in stage_b.get("mainstream_directions", []):
        L += [f"### {d.get('theme')} — 阶段：{d.get('stage')}",
              "- 支持：", _bullets(d.get("supporting"), "  "),
              "- 反证：", _bullets(d.get("counter"), "  "),
              f"- 竞争方向：{'、'.join(d.get('competitors', []) or ['无'])}", ""]

    L += ["## 3. 今日节点"]
    for n in stage_b.get("nodes", []):
        L += [f"- [{n.get('generator')}] {n.get('node_type')}（起算 {n.get('anchor_date')}）",
              "  - 触发：", _bullets(n.get("trigger_facts"), "    "),
              "  - 确认：", _bullets(n.get("confirm"), "    "),
              "  - 取消：", _bullets(n.get("cancel"), "    ")]
    L += [""]

    paths = stage_c.get("paths", {})
    L += ["## 4. 三路径（先定资金路径，再谈股票）",
          f"- 主路径：{paths.get('primary', {}).get('desc')}",
          "  - 确认：", _bullets(paths.get("primary", {}).get("confirm"), "  "),
          "  - 取消：", _bullets(paths.get("primary", {}).get("cancel"), "  "),
          f"- 替代路径：{paths.get('alternative', {}).get('desc')}",
          "  - 触发：", _bullets(paths.get("alternative", {}).get("trigger"), "  "),
          "  - 取消：", _bullets(paths.get("alternative", {}).get("cancel"), "  "),
          "- 不行动触发：", _bullets(paths.get("no_action", {}).get("trigger"), "  "), ""]

    L += ["## 5. 真实竞争组"]
    for group in stage_c.get("competition_groups", []):
        L += [f"### {group.get('group_id')} — {group.get('leader_state')}",
              f"- 可比依据：{'；'.join(group.get('comparison_basis', []) or ['无'])}",
              f"- 成员：{'、'.join(group.get('members', []) or ['无'])}",
              "- 两两关系：", _bullets(group.get("pairwise_relations"), "  "),
              "- 次日确认：", _bullets(group.get("next_confirmation"), "  "), ""]

    L += ["## 6. 候选作战卡"]
    tier_order = {"主候选": 0, "待验证候选": 1, "替代候选": 2, "取消或不行动": 3}
    cands = sorted(stage_c.get("candidates", []),
                   key=lambda c: tier_order.get(c.get("output_tier"), 9))
    for c in cands:
        L += [f"### [{c.get('output_tier')}] {c.get('thscode')} — {c.get('role')} @ {c.get('theme')}",
              f"- 节点/起算：{c.get('node')}  | 竞争组：{c.get('competition_group')}"
              f"  | 对手：{'、'.join(c.get('competitors', []) or ['无'])}"
              f"  | 字母载体：{c.get('letter_carrier', 'UNKNOWN')}",
              "- 今日状态：", _bullets(c.get("observed_state")),
              "- 次日必须完成：", _bullets(c.get("tomorrow_must_do")),
              "- 可接受变体：", _bullets(c.get("acceptable_variants")),
              "- 失败信号（出现即降级/取消）：", _bullets(c.get("failure_signals")),
              "- 直接取消：", _bullets(c.get("cancel_if")),
              f"- 依据：{'、'.join(c.get('evidence', []) or [])}", ""]

    L += ["## 7. 同期排除候选（保留负样本）"]
    for candidate in stage_c.get("excluded_candidates", []):
        L.append(
            f"- {candidate.get('thscode')} [{candidate.get('generator')}/"
            f"{candidate.get('anchor_date')}]：{candidate.get('reason')}")
    if not stage_c.get("excluded_candidates"):
        L.append("- （无）")
    L.append("")

    L += ["## 8. 未知与方法缺口", _bullets(stage_c.get("unknowns")), ""]
    return "\n".join(L)
