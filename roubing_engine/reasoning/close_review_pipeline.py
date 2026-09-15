"""M6 close-review orchestrator for V2 walk-forward closure."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from roubing_engine.config import PROJECT_ROOT
from roubing_engine.reasoning import prompts, protocols, provenance, runner, schemas, task_package
from roubing_engine.rules.retrieve import render_markdown, select
from roubing_engine.features.stock_features import features_for
from roubing_engine.state.ledger import append_followup, apply_close_review

RUNS = PROJECT_ROOT / "runs"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _review_facts(plan: dict, validation_results: dict, tplus1: str) -> dict:
    leaves = [
        leaf for leaf in (
            (plan.get("action_plan") or {}).get("primary"),
            (plan.get("action_plan") or {}).get("backup"),
        ) if leaf
    ]
    validation_codes = list((plan.get("action_plan") or {}).get("validation_objects") or [])
    action_codes = [leaf.get("thscode") for leaf in leaves if leaf.get("thscode")]
    codes = list(dict.fromkeys(action_codes + validation_codes))
    close_features = features_for(codes, tplus1) if codes else {}
    triggered_code = None
    open_result = validation_results.get("open_0935") or validation_results.get("m5") or {}
    if open_result.get("decision") == "BUY":
        triggered_code = open_result.get("current_action_candidate")
    elif (open_result.get("action_trigger") or {}).get("method") in {
        "LOW_ABSORB", "BREAKOUT_FOLLOW", "RESEAL",
    }:
        triggered_code = (open_result.get("action_trigger") or {}).get("thscode")
    return {
        "plan_date": plan.get("plan_date"),
        "as_of": plan.get("as_of"),
        "tplus1": tplus1,
        "frozen_action_leaves": leaves,
        "validation_objects": validation_codes,
        "validation_results": validation_results,
        "triggered_action_code": triggered_code,
        "close_features": close_features,
        "close_fact_boundary": {
            "available": bool(close_features),
            "reason": (
                "daily close features loaded for frozen action and validation objects"
                if close_features else
                "daily warehouse has no close features for frozen action/validation objects"
            ),
            "missing_intraday_detail": [
                "M6 daily features do not prove intraday active order flow",
                "role replacement still requires event order and board response from validation_results",
            ],
        },
    }


def run_close_review(plan_date: str, tplus1: str, backend: str = "codex",
                     dry_run: bool = False) -> dict:
    run_dir = RUNS / plan_date
    plan_path = run_dir / "executable_plan.json"
    if not plan_path.exists():
        raise RuntimeError(f"missing executable plan: {plan_path}")
    plan = _load_json(plan_path)
    validation_results = {}
    for name in ("m4_auction_result", "m5_open_action_result"):
        path = run_dir / f"{name}_{tplus1}.json"
        if path.exists():
            validation_results["m4" if name.startswith("m4") else "m5"] = _load_json(path)
    for suffix in ("auction_0925", "open_0935"):
        path = run_dir / f"stage_d_result_{tplus1}_{suffix}.json"
        if path.exists():
            validation_results[suffix] = _load_json(path)
    facts = _review_facts(plan, validation_results, tplus1)
    m6_dir = run_dir / f"m6_close_{tplus1}"
    rules = render_markdown(select(kinds=["role", "exit", "primitive", "discipline"],
                                   as_of=plan_date))
    task_package.write_package(m6_dir, prompts.m6_close_review_instructions(), {
        "close_review_facts.json": facts,
        "executable_plan.json": plan,
        "validation_results.json": validation_results,
        "rules.md": rules,
        "protocol.json": {"pack": protocols.PACKS["M6"].__dict__},
        "schema.json": schemas.CLOSE_REVIEW_SCHEMA,
    })
    if dry_run:
        return {"ok": True, "dry_run": True, "package": str(m6_dir)}

    task = runner.AgentTask(
        task_dir=m6_dir,
        instructions=prompts.m6_close_review_instructions(),
        reasoning_effort=protocols.PACKS["M6"].core_reasoning_effort,
    )
    result = runner.run(task, backend=backend)
    result = provenance.stamp(
        result, backend, m6_dir,
        ["close_review_facts.json", "executable_plan.json",
         "validation_results.json", "rules.md", "protocol.json", "schema.json"],
    )
    problems = runner.validate(result, schemas.CLOSE_REVIEW_SCHEMA)
    if result.get("plan_date") != str(plan.get("plan_date")):
        problems.append("$.plan_date: does not match executable plan")
    if result.get("tplus1") != tplus1:
        problems.append("$.tplus1: does not match requested close review date")
    draft_path = run_dir / f"close_review_{tplus1}.draft.json"
    provenance.write(result, draft_path)
    if problems:
        raise RuntimeError("M6 close review invalid: " + "; ".join(problems))
    result_path = run_dir / f"close_review_{tplus1}.json"
    provenance.write(result, result_path)
    append_followup(plan_date, tplus1, snapshot="CLOSE", result_file=str(result_path),
                    status="M6_CLOSE_REVIEW")
    apply_close_review(plan_date, tplus1, result, result_file=str(result_path))
    return {"ok": True, "plan_date": plan_date, "tplus1": tplus1,
            "backend": backend, "result_file": str(result_path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-date", required=True, help="T day YYYYMMDD")
    parser.add_argument("--tplus1", required=True, help="T+1 YYYY-MM-DD")
    parser.add_argument("--backend", default="codex", choices=["codex", "cursor"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    out = run_close_review(args.plan_date, args.tplus1, backend=args.backend,
                           dry_run=args.dry_run)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
