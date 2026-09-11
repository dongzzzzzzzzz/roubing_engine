"""Daily state ledger: persist env/mainstream/nodes/roles per trade date and
provide the previous-day ledger for chained walk-forward reasoning.
"""
from __future__ import annotations

import json
from pathlib import Path

from roubing_engine.config import PROJECT_ROOT

LEDGER_DIR = PROJECT_ROOT / "runs" / "ledger"


def save_ledger(date: str, stage_b: dict, stage_c: dict | None = None) -> Path:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    previous = load_prev_ledger(date)
    previous_directions = {
        item.get("theme"): item for item in (previous.get("mainstream_directions") or [])
    }
    previous_roles = {
        item.get("thscode"): item for item in (previous.get("roles") or [])
    }
    directions = []
    for direction in stage_b.get("mainstream_directions") or []:
        old = previous_directions.get(direction.get("theme"), {})
        directions.append({
            **direction,
            "stage_yesterday": old.get("stage_today") or old.get("stage"),
            "stage_today": direction.get("stage"),
            "migration_evidence": direction.get("supporting") or [],
            "counter_evidence": direction.get("counter") or [],
        })

    roles = []
    for candidate in ((stage_c or {}).get("candidates") or []):
        old = previous_roles.get(candidate.get("thscode"), {})
        roles.append({
            "thscode": candidate.get("thscode"),
            "name": candidate.get("name"),
            "theme": candidate.get("theme"),
            "previous_role": old.get("new_role") or old.get("role"),
            "new_role": candidate.get("role"),
            "role": candidate.get("role"),
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
        "mainstream_directions": directions,
        "nodes": stage_b.get("nodes"),
        "competition_groups": (stage_c or {}).get("competition_groups") or [],
        "roles": roles,
        "excluded_candidates": (stage_c or {}).get("excluded_candidates") or [],
        "paths": (stage_c or {}).get("paths") or {},
        "unknowns": (stage_c or {}).get("unknowns") or [],
        "stage_b_provenance": stage_b.get("_provenance"),
        "stage_c_provenance": (stage_c or {}).get("_provenance"),
        "approval_status": "APPROVED",
    }
    p = LEDGER_DIR / f"{date}.json"
    p.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def load_prev_ledger(date: str) -> dict:
    """Most recent ledger strictly before `date` (YYYYMMDD)."""
    if not LEDGER_DIR.exists():
        return {}
    prior = sorted(p.stem for p in LEDGER_DIR.glob("*.json") if p.stem < date)
    if not prior:
        return {}
    return json.loads((LEDGER_DIR / f"{prior[-1]}.json").read_text())


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
