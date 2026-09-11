"""Method-fidelity + time-discipline checks (plan §27.1-2). Deterministic audit
run over a stage_b/stage_c plan; complements the reasoning-side critic.
"""
from __future__ import annotations

from roubing_engine.warehouse import as_of as _asof


def check_plan(stage_b: dict, stage_c: dict, candidate_pools: list[dict] | None = None) -> dict:
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
    pools = candidate_pools or []
    pool_by_key = {
        (entry.get("generator"), entry.get("anchor_date")): entry for entry in pools
    }
    allowed = {
        (entry.get("generator"), entry.get("anchor_date"), stock.get("thscode"))
        for entry in pools for stock in (entry.get("pool") or [])
    }
    eligible = {
        (entry.get("generator"), entry.get("anchor_date"), stock.get("thscode"))
        for entry in pools if entry.get("status") in {"READY", "PARTIAL_DATA"}
        for stock in (entry.get("pool") or [])
    }
    allowed_codes = {code for _, _, code in allowed}
    node_keys = {
        (node.get("generator"), node.get("anchor_date"))
        for node in (stage_b.get("nodes") or []) if node.get("generator")
    }
    groups = {g.get("group_id"): g for g in stage_c.get("competition_groups", [])}
    for group_id, group in groups.items():
        for member in group.get("members", []):
            if member not in allowed_codes:
                v.append(f"竞争组 {group_id}: 成员 {member} 不在任何已打开候选池")
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
        key = (c.get("generator"), c.get("anchor_date"))
        if key not in node_keys:
            v.append(f"{code}: generator/anchor 未由 Stage B 节点打开")
        if (c.get("generator"), c.get("anchor_date"), code) not in allowed:
            v.append(f"{code}: 不在对应 generator/anchor 的确定性候选池")
        pool_entry = pool_by_key.get(key, {})
        if pool_entry.get("status") == "PARTIAL_DATA" and c.get("output_tier") == "主候选":
            v.append(f"{code}: 候选池为 PARTIAL_DATA，不得升级为主候选")
        if c.get("letter_carrier") != "UNKNOWN":
            v.append(f"{code}: 当前知识合同不允许自动赋予 A/B/C/D")
    selected = {
        (candidate.get("generator"), candidate.get("anchor_date"), candidate.get("thscode"))
        for candidate in stage_c.get("candidates", [])
    }
    excluded = {
        (candidate.get("generator"), candidate.get("anchor_date"), candidate.get("thscode"))
        for candidate in stage_c.get("excluded_candidates", [])
    }
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
    return {"n_violations": len(v), "violations": v,
            "verdict": "PASS" if not v else "NEEDS_REVISION"}


def check_time_discipline(input_dates: list[str], as_of_date: str) -> dict:
    return _asof.audit_reasoning_inputs(input_dates, as_of_date)
