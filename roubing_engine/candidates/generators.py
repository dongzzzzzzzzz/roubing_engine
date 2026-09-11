"""Map Stage-B nodes to node-specific deterministic observation pools."""
from __future__ import annotations

from roubing_engine.candidates import pools


def _g1(node, as_of):
    return pools.emotion_breakout_pool(node.get("anchor_date") or as_of)


def _first(node, as_of):
    return pools.first_board_pool(node.get("anchor_date") or as_of, node.get("theme"))


def _single(node, as_of):
    return pools.explicit_candidates(node, as_of)


def _direction(node, as_of):
    return pools.direction_role_pool(as_of, node.get("theme")) if node.get("theme") else []


def _cohort(node, as_of):
    return pools.starting_cohort_pool(
        node.get("anchor_date") or as_of, as_of, node.get("theme"))


def _g10(node, as_of):
    return pools._dedupe(_first(node, as_of) + _direction(node, as_of))


def _g11(node, as_of):
    if node.get("candidate_ids"):
        return pools.explicit_candidates(node, as_of)
    if node.get("theme"):
        return pools.panic_divergence_pool(as_of, node.get("theme"))
    return []


GENERATOR_POOLS = {
    "G1": (_g1, "实际越过此前已捕获情绪高度的候选"),
    "G2": (_first, "情绪转折形成日的同日首板池"),
    "G3": (_single, "已有伴飞地位且由节点明确指定的二波升级股票"),
    "G4": (_first, "总龙第一次断板日首板池"),
    "G5": (_first, "二波第一次放量分歧日首板池"),
    "G6": (_direction, "原核心/容量/历史方向成员/分歧抗跌者观察全集，不要求今日涨停"),
    "G7": (_direction, "方向历史成员与已有角色全集，附当日成交事实，不以涨停为前提"),
    "G8": (_cohort, "同一起算日完整队列，保留后续失败者，不以后来赢家反筛"),
    "G9": (_direction, "方向内旧角色与新候选全集，供事件顺序比较"),
    "G10": (_g10, "切换日低位首板与方向内容量/旧角色候选并集"),
    "G11": (_g11, "未继续跟跌或守住前低的全量事实观察池；主动带动仍由AI验证"),
    "G12": (_single, "突破后首次分歧的已知核心，必须由节点明确股票代码"),
}


def build_pools_from_nodes(nodes: list[dict], as_of: str) -> list[dict]:
    out = []
    for node in nodes or []:
        gid = node.get("generator")
        entry = {
            "generator": gid,
            "node_type": node.get("node_type"),
            "anchor_date": node.get("anchor_date"),
            "theme": node.get("theme"),
        }
        if not gid:
            entry.update({
                "status": "OBSERVATION_ONLY", "pool": [], "pool_size": 0,
                "data_blocks": [],
                "note": "该节点未打开候选生成器，因此不得产生可执行候选",
            })
            out.append(entry)
            continue
        if gid not in GENERATOR_POOLS:
            entry.update({
                "status": "BLOCKED_METHOD", "pool": [], "pool_size": 0,
                "data_blocks": [f"未知生成器 {gid}"], "note": "未定义的生成器",
            })
            out.append(entry)
            continue
        builder, note = GENERATOR_POOLS[gid]
        pool = pools.attach_context(builder(node, as_of), as_of)
        blocks = []
        partial = False
        if gid in {"G3", "G12"} and not node.get("candidate_ids"):
            blocks.append("单票生成器缺少 Stage B 明确 candidate_ids")
        if gid in {"G6", "G7", "G9", "G10"} and not node.get("theme"):
            blocks.append("方向型生成器缺少 theme，不能构造真实方向成员")
        if gid == "G1" and not pool:
            blocks.append("未发现超过此前已捕获高度的候选，或历史高度数据不足")
        if gid == "G11" and not node.get("theme") and not node.get("candidate_ids"):
            blocks.append(
                "全市场G11缺少历史逐笔主动大单/板块关系；必须由Stage B给出方向或明确候选，不能从数千只抗跌股任意截断")
        if gid in {"G1", "G6", "G7", "G9", "G10", "G11"}:
            coverage = pools.recent_universe_coverage(as_of)
            if not coverage.get("continuous_recent"):
                blocks.append(
                    "逐日universe不连续："
                    f"需要{coverage.get('expected_previous_trade_date')}，"
                    f"现有最近前序为{coverage.get('captured_previous_trade_date')}")
                partial = bool(pool)
        if gid == "G10":
            from roubing_engine.rules.regulatory import active_rules
            regulatory = active_rules(as_of)
            if not regulatory.get("available"):
                blocks.append("监管空间不可计算：缺当时有效且已核验的官方规则版本")
                partial = True
        status = ("PARTIAL_DATA" if partial and pool else "BLOCKED_DATA" if blocks
                  else "READY" if pool else "EMPTY_VALID")
        entry.update({
            "status": status, "pool": pool, "pool_size": len(pool),
            "data_blocks": blocks, "note": note,
        })
        out.append(entry)
    return out
