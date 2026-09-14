"""Build deterministic rule/case coverage for the independent audit.

The daily Stage B/C agents reason from compiled rules and frozen facts.  Raw
posts are supplied only to the final adversarial audit.  Audit retrieval must
follow the actual nodes/tasks/claims produced that day; a fixed list of broad
keywords can silently miss the exact method being used.
"""
from __future__ import annotations

from .corpus_index import search


REQUIREMENTS = {
    "MAINSTREAM": {
        "rule_tags": ["MAIN_TREND"],
        "case_keywords": ["主流", "板块", "共振"],
    },
    "CONTINUATION": {
        "rule_tags": ["MAIN_TREND"],
        "case_keywords": ["延续", "晋级", "承接"],
    },
    "REPAIR": {
        "rule_tags": ["REPAIR"],
        "case_keywords": ["大分歧", "修复", "反包"],
    },
    "BREAKOUT": {
        "rule_tags": ["BREAKOUT", "ACTIVE_DIVERGENCE"],
        "case_keywords": ["突破", "平台", "第一次分歧"],
    },
    "UNIQUENESS": {
        "rule_tags": ["UNIQUENESS"],
        "case_keywords": ["唯一性", "起算日", "竞争"],
    },
    "CAPACITY": {
        "rule_tags": ["CAPACITY"],
        "case_keywords": ["容量", "大成交", "带动"],
    },
    "CORE_SWITCH": {
        "rule_tags": ["CORE_SWITCH", "HIGH_LOW"],
        "case_keywords": ["核心切换", "旧核心", "新核心"],
    },
    "HIGH_LOW": {
        "rule_tags": ["HIGH_LOW"],
        "case_keywords": ["高低切", "低位", "空间"],
    },
    "SECOND_WAVE": {
        "rule_tags": ["SECOND_WAVE", "SYMBIOSIS"],
        "case_keywords": ["二波", "伴生", "反抽"],
    },
    "SUPPLEMENT": {
        "rule_tags": ["SUPPLEMENT", "COMPANION"],
        "case_keywords": ["补涨", "伴飞", "助攻"],
    },
    "BOTTOM_REPAIR": {
        "rule_tags": ["BOTTOM_REPAIR"],
        "case_keywords": ["恐慌", "底背离", "主动带动"],
    },
    "ACTIVE_DIVERGENCE": {
        "rule_tags": ["ACTIVE_DIVERGENCE"],
        "case_keywords": ["主动分歧", "被动", "弱转强"],
    },
    "ROLE": {
        "rule_tags": ["ROLE"],
        "case_keywords": ["核心", "容量", "跟风"],
    },
    "AGENCY": {
        "rule_tags": ["PRIMITIVE"],
        "case_keywords": ["主动", "被动", "带动"],
    },
    "ROLE_REPLACEMENT": {
        "rule_tags": ["CORE_SWITCH", "EXIT"],
        "case_keywords": ["替代", "被取代", "核心切换"],
    },
    "EXIT": {
        "rule_tags": ["EXIT", "CONFLICT"],
        "case_keywords": ["该强不强", "取消", "结构破坏"],
    },
    "ALTERNATIVE": {
        "rule_tags": ["REGIME_SWITCH", "MAIN_TREND"],
        "case_keywords": ["切换", "新方向", "放弃"],
    },
}


NODE_MARKERS = (
    ("FIRST_ACTIVE_DIVERGENCE", "ACTIVE_DIVERGENCE"),
    ("ACTIVE_DIVERGENCE", "ACTIVE_DIVERGENCE"),
    ("CORE_SWITCH", "CORE_SWITCH"),
    ("HIGH_LOW", "HIGH_LOW"),
    ("BOTTOM_REPAIR", "BOTTOM_REPAIR"),
    ("SECOND_WAVE", "SECOND_WAVE"),
    ("UNIQUENESS", "UNIQUENESS"),
    ("CAPACITY", "CAPACITY"),
    ("BREAKOUT", "BREAKOUT"),
    ("DIVERGENCE", "REPAIR"),
    ("REPAIR", "REPAIR"),
    ("CONTINUATION", "CONTINUATION"),
    ("MAINSTREAM", "MAINSTREAM"),
)

TASK_REQUIREMENTS = {
    "HIGHEST_LADDER_CONTINUATION": "CONTINUATION",
    "SAME_LEVEL_PROMOTION": "UNIQUENESS",
    "SUB_DIRECTION_LEVEL_CONTINUATION": "CONTINUATION",
    "CAPACITY_CARRIER_VALIDATION": "CAPACITY",
    "FIRST_BOARD_DIFFUSION": "SUPPLEMENT",
    "BROKEN_BOARD_REPAIR": "REPAIR",
    "DIRECTION_REPAIR": "REPAIR",
    "CORE_SWITCH": "CORE_SWITCH",
    "HIGH_LOW_SWITCH": "HIGH_LOW",
    "PANIC_REPAIR_LEADER": "BOTTOM_REPAIR",
    "FIRST_ACTIVE_DIVERGENCE": "ACTIVE_DIVERGENCE",
    "CATCH_UP": "SUPPLEMENT",
    "SECOND_WAVE_COMPANION": "SECOND_WAVE",
}

GENERATOR_REQUIREMENTS = {
    "G1": "CONTINUATION", "G2": "SUPPLEMENT", "G3": "SECOND_WAVE",
    "G4": "SUPPLEMENT", "G5": "SECOND_WAVE", "G6": "REPAIR",
    "G7": "CAPACITY", "G8": "UNIQUENESS", "G9": "CORE_SWITCH",
    "G10": "HIGH_LOW", "G11": "BOTTOM_REPAIR", "G12": "ACTIVE_DIVERGENCE",
}


def _node_requirement(node_type: str | None) -> str:
    text = (node_type or "").upper()
    return next((kind for marker, kind in NODE_MARKERS if marker in text), "MAINSTREAM")


def _manifest_entry(source_type: str, source_id: str | None,
                    requirement: str) -> dict:
    spec = REQUIREMENTS[requirement]
    return {
        "source_type": source_type,
        "source_id": source_id,
        "requirement": requirement,
        "rule_tags": list(spec["rule_tags"]),
        "case_keywords": list(spec["case_keywords"]),
    }


def _collect_manifest(*, nodes: list[dict] | None = None,
                      tasks: list[dict] | None = None,
                      stage_c: dict | None = None,
                      compiled_plan: dict | None = None) -> list[dict]:
    manifest: list[dict] = []
    for node in nodes or []:
        manifest.append(_manifest_entry(
            "NODE", node.get("node_id") or node.get("node_type"),
            _node_requirement(node.get("node_type"))))
        generator = node.get("generator")
        if generator in GENERATOR_REQUIREMENTS:
            manifest.append(_manifest_entry(
                "GENERATOR", generator, GENERATOR_REQUIREMENTS[generator]))
    for task in tasks or []:
        task_type = task.get("task_type")
        if task_type in TASK_REQUIREMENTS:
            manifest.append(_manifest_entry(
                "TASK", task.get("task_id") or task_type,
                TASK_REQUIREMENTS[task_type]))

    candidates = [candidate for path in (stage_c or {}).get("path_plans") or []
                  for candidate in path.get("candidates") or []]
    if not candidates:
        candidates = (stage_c or {}).get("candidates") or []
    role_values = {candidate.get("role") for candidate in candidates}
    role_states = {candidate.get("role_status") for candidate in candidates}
    if (role_values - {None, "UNKNOWN"}) or (role_states - {None, "UNKNOWN"}):
        manifest.append(_manifest_entry("ROLE_STATE", "candidate_roles", "ROLE"))
    agency_states = {
        (candidate.get("agency_event_model") or {}).get("relation_state")
        for candidate in candidates
    }
    if agency_states - {None, "UNKNOWN", "INDEPENDENCE_NOT_CONFIRMED"}:
        manifest.append(_manifest_entry("AGENCY_STATE", "candidate_agency", "AGENCY"))
    if "ROLE_REPLACED" in agency_states or "REPLACED" in role_states:
        manifest.append(_manifest_entry(
            "ROLE_STATE", "role_replacement", "ROLE_REPLACEMENT"))

    final = (stage_c or {}).get("final_action_plan") or {}
    executable = (compiled_plan or {}).get("executable_plan") or compiled_plan or {}
    action = executable.get("action_plan") or final
    has_exit_contract = bool(
        action.get("no_action_conditions")
        or any((leaf or {}).get("direct_fail_conditions")
               for leaf in (action.get("primary"), action.get("backup"))))
    if has_exit_contract:
        manifest.append(_manifest_entry("ACTION_PLAN", "exit_contract", "EXIT"))
    path_kinds = {path.get("path_kind") for path in (stage_c or {}).get("path_plans") or []}
    if "ALTERNATIVE" in path_kinds or (final.get("backup_ref") or {}).get("path_kind") == "ALTERNATIVE":
        manifest.append(_manifest_entry(
            "ACTION_PLAN", "cross_path_alternative", "ALTERNATIVE"))

    # Deduplicate exact requirements while preserving every source mapping in
    # the manifest.  Source mappings make audit coverage explainable.
    seen = set()
    output = []
    for item in manifest:
        key = (item["source_type"], item["source_id"], item["requirement"])
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output


def _build_bundle(manifest: list[dict], *, per_requirement_limit: int,
                  as_of: str | None) -> dict:
    from .retrieve import select

    units = select(as_of=as_of)
    requirements = sorted({item["requirement"] for item in manifest})
    case_cards: list[dict] = []
    coverage = []
    seen_hashes: set[str] = set()
    required_rule_ids: set[str] = set()
    all_keywords: set[str] = set()
    for requirement in requirements:
        spec = REQUIREMENTS[requirement]
        rule_ids = [unit["id"] for unit in units
                    if set(spec["rule_tags"]) & set(unit.get("tags") or [])]
        hits = search(spec["case_keywords"], limit=per_requirement_limit, as_of=as_of)
        for hit in hits:
            if hit.get("hash") not in seen_hashes:
                seen_hashes.add(hit.get("hash"))
                case_cards.append(hit)
        required_rule_ids.update(rule_ids)
        all_keywords.update(spec["case_keywords"])
        coverage.append({
            "requirement": requirement,
            "rule_ids": rule_ids,
            "case_keywords": list(spec["case_keywords"]),
            "matched_case_hashes": [hit.get("hash") for hit in hits if hit.get("hash")],
            "status": "READY" if rule_ids and hits else "PARTIAL_DATA",
        })
    return {
        "required_rule_ids": sorted(required_rule_ids),
        "required_case_keywords": sorted(all_keywords),
        "matched_case_hashes": [item.get("hash") for item in case_cards if item.get("hash")],
        "matched_case_count": len(case_cards),
        "case_cards": case_cards,
        "knowledge_cutoff": as_of,
        "per_requirement_limit": per_requirement_limit,
        "status": ("READY" if coverage and all(item["status"] == "READY" for item in coverage)
                   else "PARTIAL_DATA"),
        "coverage": coverage,
        "manifest": manifest,
        "note": "原帖只供独立审计；召回项由本次实际节点、任务、角色、主动性、退出与替代结构动态生成",
    }


def bundle_for_nodes(nodes: list[dict] | None, *, limit: int = 4,
                     as_of: str | None = None) -> dict:
    """Compatibility wrapper used by focused node-coverage tests."""
    manifest = _collect_manifest(nodes=nodes)
    bundle = _build_bundle(manifest, per_requirement_limit=limit, as_of=as_of)
    bundle["nodes"] = [item for item in manifest if item["source_type"] == "NODE"]
    return bundle


def bundle_for_audit(stage_b: dict, stage_c: dict, task_bundle: dict,
                     compiled_plan: dict, *, as_of: str | None = None,
                     per_requirement_limit: int = 4) -> dict:
    manifest = _collect_manifest(
        nodes=stage_b.get("nodes") or [],
        tasks=task_bundle.get("task_candidates") or [],
        stage_c=stage_c,
        compiled_plan=compiled_plan,
    )
    return _build_bundle(
        manifest, per_requirement_limit=per_requirement_limit, as_of=as_of)


def render_bundle(bundle: dict) -> str:
    lines = [
        "# 规则/案例覆盖清单", "", f"- 状态：{bundle.get('status')}",
        f"- 知识截止日：{bundle.get('knowledge_cutoff') or '未限制'}",
        f"- 动态需求数：{len(bundle.get('coverage') or [])}",
        f"- 命中案例数：{bundle.get('matched_case_count') or 0}", "",
    ]
    for item in bundle.get("coverage") or []:
        lines += [
            f"## {item.get('requirement')}",
            f"- 状态：{item.get('status')}",
            f"- 规则：{', '.join(item.get('rule_ids') or ['无'])}",
            f"- 关键词：{', '.join(item.get('case_keywords') or ['无'])}",
            f"- 原帖：{', '.join(item.get('matched_case_hashes') or ['无'])}", "",
        ]
    return "\n".join(lines)


def render_audit_posts(bundle: dict) -> str:
    lines = [
        "# 离线审计反方原帖证据", "",
        "这些原帖只供独立审计检查规则编译是否漏掉语境；不得把帖子里的股票、方向或个案数字抄入每日正式推理。",
        "",
    ]
    for item in bundle.get("case_cards") or []:
        lines += [
            f"## {item.get('date') or '日期未知'}｜{item.get('title') or '无标题'}",
            f"- source_hash: {item.get('hash')}",
            f"- source_url: {item.get('url') or '无'}", "",
            item.get("excerpt") or item.get("snippet") or "", "",
        ]
    return "\n".join(lines)
