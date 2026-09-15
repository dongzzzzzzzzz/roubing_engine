"""Compact model-facing fact projections for the V2 reasoning packs."""
from __future__ import annotations

import json
from collections.abc import Iterable


def _copy(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def _fact_catalog_subset(facts: dict, fact_ids: Iterable[str]) -> dict:
    catalog = facts.get("fact_catalog") or {}
    wanted = {item for item in fact_ids if item}
    return {key: catalog[key] for key in wanted if key in catalog}


def _ids_from_rows(rows: Iterable[dict]) -> list[str]:
    out: list[str] = []
    for row in rows:
        for key in ("fact_id", "direction_fact_id"):
            value = row.get(key)
            if value and value not in out:
                out.append(value)
        for value in row.get("fact_ids") or []:
            if value and value not in out:
                out.append(value)
    return out


def project_macro_facts(facts: dict, yesterday: dict | None) -> dict:
    """Facts for M1: market environment and direction lifecycle only.

    M1 deliberately receives no stock roster.  Direction-level aggregates keep
    enough evidence for environment, lifecycle and cross-direction comparison.
    """
    direction_rows = _copy(facts.get("direction_state_facts") or [])
    for row in direction_rows:
        row.pop("stock_fact_ids", None)
    kept_ids = _ids_from_rows(direction_rows)
    for container in (
        facts.get("environment_facts") or {},
        facts.get("context_facts") or {},
        facts.get("data_completeness") or {},
    ):
        if isinstance(container, dict):
            for value in container.values():
                if isinstance(value, str) and value.startswith("F-") and value not in kept_ids:
                    kept_ids.append(value)
                elif isinstance(value, dict):
                    fact_id = value.get("fact_id")
                    if fact_id and fact_id not in kept_ids:
                        kept_ids.append(fact_id)
    return {
        "as_of": facts.get("as_of"),
        "trade_date": facts.get("trade_date"),
        "data_completeness": _copy(facts.get("data_completeness") or {}),
        "previous_state_summary": _copy(facts.get("previous_state_summary") or {}),
        "yesterday_state": _copy(yesterday or {}),
        "environment_facts": _copy(facts.get("environment_facts") or {}),
        "context_facts": _copy(facts.get("context_facts") or {}),
        "direction_state_facts": direction_rows,
        "theme_hierarchy": _copy(facts.get("theme_hierarchy") or []),
        "path_comparison_contract": _copy(facts.get("path_comparison_contract") or {}),
        "fact_catalog": _fact_catalog_subset(facts, kept_ids),
        "projection_note": "M1 excludes all stock rows and candidate-pool content.",
    }


def project_node_facts(facts: dict, macro_result: dict, yesterday: dict | None) -> dict:
    """Facts for M2: retained directions, pending nodes and related events."""
    retained = {
        row.get("theme") for row in macro_result.get("direction_evaluations") or []
        if row.get("path_status") in {"PRIMARY", "COMPETITOR", "OBSERVATION"}
    }
    direction_ids = {
        row.get("direction_fact_id") for row in macro_result.get("direction_evaluations") or []
        if row.get("theme") in retained
    }
    stock_rows = [
        _copy(row) for row in facts.get("stage_b_observation_universe") or []
        if row.get("direction_fact_id") in direction_ids or row.get("theme") in retained
    ]
    fact_ids = _ids_from_rows(stock_rows)
    for row in macro_result.get("direction_evaluations") or []:
        if row.get("theme") in retained:
            fact_ids.extend(row.get("supporting_fact_ids") or [])
            fact_ids.extend(row.get("counter_fact_ids") or [])
            if row.get("direction_fact_id"):
                fact_ids.append(row["direction_fact_id"])
    pending_nodes = []
    for node in (yesterday or {}).get("nodes") or []:
        if node.get("action_status") in {"ACTION_READY", "OBSERVATION_ONLY"}:
            pending_nodes.append(node)
    return {
        "as_of": facts.get("as_of"),
        "trade_date": facts.get("trade_date"),
        "environment": _copy(macro_result.get("environment") or {}),
        "primary_path": _copy(macro_result.get("primary_path") or {}),
        "direction_evaluations": [
            _copy(row) for row in macro_result.get("direction_evaluations") or []
            if row.get("theme") in retained
        ],
        "pending_nodes": _copy(pending_nodes),
        "related_event_rows": stock_rows,
        "fact_catalog": _fact_catalog_subset(facts, fact_ids),
        "projection_note": "M2 sees only retained directions plus pending nodes; it must output all G1-G12 applicability rows before any candidate pool is expanded.",
    }


def project_plan_facts(facts: dict, selected_pools: list[dict]) -> dict:
    """Facts for M3: only stocks inside audited ACTION_READY task pools."""
    allowed_codes = {
        row.get("thscode") for pool in selected_pools
        for field in ("pool", "validation_pool") for row in pool.get(field) or []
        if row.get("thscode")
    }
    result = _copy(facts)
    result["stage_b_observation_universe"] = [
        row for row in result.get("stage_b_observation_universe") or []
        if row.get("thscode") in allowed_codes
    ]
    result["failed_observations"] = [
        row for row in result.get("failed_observations") or []
        if row.get("thscode") in allowed_codes
    ]
    result["themes"] = []
    result["direction_facts"] = []
    for direction in result.get("direction_state_facts") or []:
        direction.pop("stock_fact_ids", None)
        feedback = direction.get("previous_buyer_feedback") or {}
        if "rows" in feedback:
            feedback["rows"] = [
                row for row in feedback.get("rows") or []
                if row.get("thscode") in allowed_codes
            ]
    result["fact_catalog"] = {
        fact_id: item for fact_id, item in (result.get("fact_catalog") or {}).items()
        if item.get("scope") != "STOCK" or item.get("thscode") in allowed_codes
    }
    result["m3_allowed_stock_codes"] = sorted(allowed_codes)
    result["projection_note"] = "M3 can inspect only audited node task pools; stocks outside those pools are removed."
    return result
