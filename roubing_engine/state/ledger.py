"""Daily state ledger: persist env/mainstream/nodes/roles per trade date and
provide the previous-day ledger for chained walk-forward reasoning.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from roubing_engine.config import PROJECT_ROOT

LEDGER_DIR = PROJECT_ROOT / "runs" / "ledger"


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
            "stage_yesterday": old.get("stage_today") or old.get("stage"),
            "stage_today": direction.get("stage"),
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
    for candidate in stage_candidates:
        old = previous_roles.get(candidate.get("thscode"), {})
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
        })
    entry = {
        "trade_date": date,
        "as_of": stage_b.get("as_of"),
        "environment": stage_b.get("environment"),
        "direction_evaluations": directions,
        "nodes": stage_b.get("nodes"),
        "competition_groups": ([plan.get("competition_group") for plan in path_plans]
                               if path_plans else
                               (stage_c or {}).get("competition_groups") or []),
        "roles": roles,
        "excluded_candidates": ([candidate for plan in path_plans
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
        "action_plan": ((stage_c or {}).get("final_action_plan") or {}
                        if path_plans else (stage_c or {}).get("action_plan") or {}),
        "unknowns": (stage_c or {}).get("unknowns") or [],
        "stage_b_provenance": stage_b.get("_provenance"),
        "stage_c_provenance": (stage_c or {}).get("_provenance"),
        "approval_status": "APPROVED",
    }
    p = LEDGER_DIR / f"{date}.json"
    p.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
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
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
