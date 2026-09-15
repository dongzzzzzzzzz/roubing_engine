"""Daily state ledger: persist env/mainstream/nodes/roles per trade date and
provide the previous-day ledger for chained walk-forward reasoning.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from roubing_engine.config import PROJECT_ROOT
from roubing_engine.reasoning import contracts

LEDGER_DIR = PROJECT_ROOT / "runs" / "ledger"


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def expected_previous_trade_date(date: str) -> str | None:
    """Return the actual immediately previous trading day from daily bars.

    A ledger is a state transition, so "previous" must mean the adjacent
    trading day rather than merely the most recent file that happens to exist.
    When the trading calendar cannot be proven, callers must treat prior state
    as unavailable instead of guessing from filenames.
    """
    try:
        from roubing_engine.warehouse.daily_loader import DAILY_BAR
        if not DAILY_BAR.exists():
            return None
        frame = pd.read_parquet(
            DAILY_BAR, columns=["trade_date"], filters=[("trade_date", "<", date)])
    except Exception:  # noqa: BLE001 - unavailable calendar is a safe block
        return None
    if frame.empty:
        return None
    dates = [str(value) for value in frame["trade_date"].dropna().unique()
             if str(value) < date]
    return max(dates) if dates else None


def latest_prior_ledger_date(date: str) -> str | None:
    if not LEDGER_DIR.exists():
        return None
    prior = sorted(p.stem for p in LEDGER_DIR.glob("*.json") if p.stem < date)
    return prior[-1] if prior else None


def previous_ledger_status(date: str) -> dict:
    """Describe whether an adjacent approved ledger is actually available."""
    expected = expected_previous_trade_date(date)
    latest = latest_prior_ledger_date(date)
    path = LEDGER_DIR / f"{expected}.json" if expected else None
    available = bool(path and path.exists())
    return {
        "available": available,
        "expected_previous_trade_date": expected,
        "nearest_prior_ledger_date": latest,
        "stale_prior_exists": bool(latest and latest != expected),
        "reason": (None if available else
                   "actual previous trading-day ledger missing" if expected else
                   "trading calendar unavailable; adjacency cannot be verified"),
    }


def save_ledger(date: str, stage_b: dict, stage_c: dict | None = None) -> Path:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    previous = load_prev_ledger(date)
    previous_directions = {
        item.get("theme"): item for item in (
            previous.get("direction_evaluations") or previous.get("mainstream_directions") or [])
    }
    previous_roles = {
        item.get("thscode"): item for item in (previous.get("roles") or [])
    }
    directions = []
    for direction in stage_b.get("direction_evaluations") or []:
        old = previous_directions.get(direction.get("theme"), {})
        directions.append({
            **direction,
            "stage_yesterday": (
                old.get("stage_today")
                or direction.get("stage_yesterday")
                or old.get("stage")
            ),
            "stage_today": direction.get("stage_today"),
            "migration_evidence": direction.get("supporting_fact_ids") or [],
            "counter_evidence": direction.get("counter_fact_ids") or [],
        })

    path_plans = (stage_c or {}).get("path_plans") or []
    if path_plans:
        stage_candidates = [candidate for plan in path_plans
                            for candidate in plan.get("candidates") or []]
        execution_by_task = {
            (plan.get("execution_task") or {}).get("task_id"): plan.get("execution_task")
            for plan in path_plans
        }
    else:
        stage_candidates = (stage_c or {}).get("candidates") or []
        execution_by_task = {
            ((stage_c or {}).get("execution_task") or {}).get("task_id"):
            (stage_c or {}).get("execution_task") or {}
        }
    roles = []
    stock_expectations = []
    author_letter_labels = []
    for candidate in stage_candidates:
        old = previous_roles.get(candidate.get("thscode"), {})
        stock_expectations.append({
            "thscode": candidate.get("thscode"),
            "task_id": candidate.get("task_id"),
            **(candidate.get("stock_expectation") or {}),
        })
        functional_role = candidate.get("functional_role") or {}
        author_letter_labels.append({
            "thscode": candidate.get("thscode"),
            "author_letter_label": (
                functional_role.get("author_letter_label")
                or candidate.get("author_letter_label")
                or candidate.get("letter_carrier")
                or "UNKNOWN"
            ),
            "label_source_date": candidate.get("label_source_date"),
            "label_source_fact": candidate.get("label_source_fact"),
        })
        roles.append({
            "thscode": candidate.get("thscode"),
            "name": candidate.get("name"),
            "theme": candidate.get("theme"),
            "previous_role": old.get("new_role") or old.get("role"),
            "previous_role_status": old.get("new_role_status") or old.get("role_status"),
            "new_role": candidate.get("role"),
            "new_role_status": candidate.get("role_status"),
            "role": candidate.get("role"),
            "role_family": candidate.get("role_family"),
            "role_status": candidate.get("role_status"),
            "task_id": candidate.get("task_id"),
            "execution_task": execution_by_task.get(candidate.get("task_id")),
            "observed_function": candidate.get("observed_function"),
            "task_relation": candidate.get("task_relation"),
            "generator": candidate.get("generator"),
            "anchor_date": candidate.get("anchor_date"),
            "entered_by": candidate.get("observed_state") or [],
            "must_continue_doing": candidate.get("tomorrow_must_do") or [],
            "loses_role_when": candidate.get("failure_signals") or [],
            "cancel_if": candidate.get("cancel_if") or [],
            "competition_group": candidate.get("competition_group"),
            "competitors": candidate.get("competitors") or [],
            "output_tier": candidate.get("output_tier"),
            "evidence": candidate.get("evidence") or [],
            "functional_role": functional_role,
            "stock_expectation": candidate.get("stock_expectation") or {},
        })
    close_reviews = []
    entry = {
        "trade_date": date,
        "as_of": stage_b.get("as_of"),
        "run_id": ((stage_b.get("_provenance") or {}).get("run_id")
                   or (stage_c or {}).get("_provenance", {}).get("run_id")),
        "model_config": {
            "stage_b_backend": (stage_b.get("_provenance") or {}).get("backend"),
            "stage_c_backend": ((stage_c or {}).get("_provenance") or {}).get("backend"),
        },
        "code_version": {
            "pipeline_version": ((stage_b.get("_provenance") or {}).get("pipeline_version")
                                 or ((stage_c or {}).get("_provenance") or {}).get("pipeline_version")),
            "schema_version": ((stage_b.get("_provenance") or {}).get("schema_version")
                               or ((stage_c or {}).get("_provenance") or {}).get("schema_version")),
        },
        "environment": stage_b.get("environment"),
        "environment_transition": {
            "current": stage_b.get("environment"),
            "previous": previous.get("environment"),
            "previous_trade_date": previous.get("trade_date"),
        },
        "environment_hypotheses": stage_b.get("environment_hypotheses") or [],
        "method_trace": stage_b.get("method_trace") or [],
        "generator_applicability": stage_b.get("generator_applicability") or [],
        "direction_evaluations": directions,
        "direction_lifecycle": [{
            "theme": item.get("theme"),
            "direction_fact_id": item.get("direction_fact_id"),
            "first_candidate_date": item.get("first_candidate_date"),
            "current_day_index": item.get("current_day_index"),
            "stage_yesterday": item.get("stage_yesterday"),
            "stage_today": item.get("stage_today"),
            "stage_change": item.get("stage_change"),
            "pioneer_state": item.get("pioneer_state"),
            "capacity_state": item.get("capacity_state"),
            "back_row_feedback": item.get("back_row_feedback"),
            "board_index_state": item.get("board_index_state"),
            "buyer_feedback": item.get("buyer_feedback"),
            "first_divergence_date": item.get("first_divergence_date"),
            "divergence_order": item.get("divergence_order"),
            "repair_history": item.get("repair_history"),
            "repair_quality": item.get("repair_quality"),
            "catalyst_state": item.get("catalyst_state"),
            "regulatory_constraints": item.get("regulatory_constraints"),
            "upgrade_conditions": item.get("upgrade_conditions"),
            "downgrade_conditions": item.get("downgrade_conditions"),
            "tomorrow_validation": item.get("tomorrow_validation"),
            "mainstream_questions": item.get("mainstream_questions") or {},
            "market_relation": item.get("market_relation"),
            "path_status": item.get("path_status"),
            "supporting_fact_ids": item.get("supporting_fact_ids") or [],
            "counter_fact_ids": item.get("counter_fact_ids") or [],
            "data_gaps": item.get("data_gaps") or [],
        } for item in directions],
        "catalyst_state": {
            item.get("theme"): item.get("catalyst_state")
            for item in directions if item.get("theme")
        },
        "divergence_and_repair_history": [{
            "theme": item.get("theme"),
            "first_divergence_date": item.get("first_divergence_date"),
            "divergence_order": item.get("divergence_order"),
            "repair_history": item.get("repair_history"),
            "repair_quality": item.get("repair_quality"),
        } for item in directions],
        "nodes": stage_b.get("nodes"),
        "nodes_and_maturity": stage_b.get("nodes") or [],
        "pending_nodes": [
            node for node in stage_b.get("nodes") or []
            if node.get("action_status") in {"ACTION_READY", "OBSERVATION_ONLY"}
        ],
        "competition_groups": ([plan.get("competition_group") for plan in path_plans]
                               if path_plans else
                               (stage_c or {}).get("competition_groups") or []),
        "roles": roles,
        "author_letter_labels": author_letter_labels,
        "role_migrations": [],
        "stock_expectations": stock_expectations,
        "excluded_candidates": ([candidate for plan in path_plans
                                 for candidate in plan.get("excluded_candidates") or []]
                                if path_plans else
                                (stage_c or {}).get("excluded_candidates") or []),
        "failed_same_period_candidates": ([candidate for plan in path_plans
                                           for candidate in plan.get("excluded_candidates") or []]
                                          if path_plans else
                                          (stage_c or {}).get("excluded_candidates") or []),
        "paths": ({plan.get("path_kind"): plan.get("path_analysis")
                   for plan in path_plans} if path_plans else
                  (stage_c or {}).get("paths") or {}),
        "primary_path": stage_b.get("primary_path") or {},
        "execution_task": next((plan.get("execution_task") for plan in path_plans
                                if plan.get("path_kind") == "PRIMARY"), {})
                          if path_plans else (stage_c or {}).get("execution_task") or {},
        "execution_tasks": list(execution_by_task.values()),
        "unselected_tasks": [
            task_id for task_id, task in execution_by_task.items()
            if not task or task.get("status") != "SELECTED"
        ],
        "action_plan": ((stage_c or {}).get("final_action_plan") or {}
                        if path_plans else (stage_c or {}).get("action_plan") or {}),
        "trade_decision": ((stage_c or {}).get("final_action_plan") or {}
                           if path_plans else (stage_c or {}).get("action_plan") or {}),
        "m4_results": [],
        "m5_results": [],
        "vtail_results": [],
        "holding_reviews": [],
        "exit_reviews": [],
        "close_reviews": close_reviews,
        "unknowns": (stage_c or {}).get("unknowns") or [],
        "data_gaps": list(dict.fromkeys(
            (stage_b.get("data_gaps") or []) + ((stage_c or {}).get("unknowns") or []))),
        "fact_rule_source_levels": {
            "fact_catalog_hash": ((stage_b.get("_provenance") or {}).get("fact_manifest_hash")
                                  or ((stage_c or {}).get("_provenance") or {}).get("fact_manifest_hash")),
            "rule_provenance_kinds": list(contracts.RULE_PROVENANCE_KINDS),
            "evidence_kinds": list(contracts.EVIDENCE_KINDS),
        },
        "stage_b_provenance": stage_b.get("_provenance"),
        "stage_c_provenance": (stage_c or {}).get("_provenance"),
        "approval_status": "APPROVED",
    }
    ledger_problems = contracts.validate_daily_ledger(entry)
    entry["ledger_contract_status"] = {
        "verdict": "PASS" if not ledger_problems else "NEEDS_REVISION",
        "violations": ledger_problems,
    }
    p = LEDGER_DIR / f"{date}.json"
    _write_json_atomic(p, entry)
    return p


def load_prev_ledger(date: str) -> dict:
    """Load only the actual immediately previous trading-day ledger."""
    status = previous_ledger_status(date)
    previous_date = status.get("expected_previous_trade_date")
    if not status.get("available") or not previous_date:
        return {}
    return json.loads((LEDGER_DIR / f"{previous_date}.json").read_text())


def append_followup(plan_date: str, tplus1: str, *, snapshot: str | None = None,
                    result_file: str | None = None, outcome_file: str | None = None,
                    status: str = "RECORDED") -> Path | None:
    """Attach later validation/evaluation references to an approved plan ledger."""
    path = LEDGER_DIR / f"{plan_date}.json"
    if not path.exists():
        return None
    entry = json.loads(path.read_text(encoding="utf-8"))
    followups = entry.setdefault("followups", [])
    record = {
        "tplus1": tplus1,
        "snapshot": snapshot,
        "result_file": result_file,
        "outcome_file": outcome_file,
        "status": status,
    }
    key = (tplus1, snapshot, outcome_file)
    followups = [item for item in followups
                 if (item.get("tplus1"), item.get("snapshot"), item.get("outcome_file")) != key]
    followups.append(record)
    entry["followups"] = followups
    _write_json_atomic(path, entry)
    return path


def apply_close_review(plan_date: str, tplus1: str, close_review: dict,
                       result_file: str | None = None) -> Path | None:
    """Persist M6 review and its proposed next-ledger patch on the plan ledger."""
    path = LEDGER_DIR / f"{plan_date}.json"
    if not path.exists():
        return None
    entry = json.loads(path.read_text(encoding="utf-8"))
    reviews = entry.setdefault("close_reviews", [])
    reviews = [item for item in reviews if item.get("tplus1") != tplus1]
    reviews.append({
        "tplus1": tplus1,
        "result_file": result_file,
        "task_results": close_review.get("task_results") or [],
        "role_migrations": close_review.get("role_migrations") or [],
        "holding_reviews": close_review.get("holding_reviews") or [],
        "exit_reviews": close_review.get("exit_reviews") or [],
        "next_ledger_patch": close_review.get("next_ledger_patch") or {},
        "unknowns": close_review.get("unknowns") or [],
    })
    entry["close_reviews"] = reviews
    entry["latest_close_review"] = reviews[-1]
    entry["holding_reviews"] = close_review.get("holding_reviews") or []
    entry["exit_reviews"] = close_review.get("exit_reviews") or []
    entry["role_migrations"] = close_review.get("role_migrations") or []
    ledger_problems = contracts.validate_daily_ledger(entry)
    entry["ledger_contract_status"] = {
        "verdict": "PASS" if not ledger_problems else "NEEDS_REVISION",
        "violations": ledger_problems,
    }
    _write_json_atomic(path, entry)
    return path
