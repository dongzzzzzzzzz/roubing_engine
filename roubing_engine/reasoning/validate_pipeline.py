"""Stage D orchestrator: validate a T-day plan against T+1 reality via sub-agent.

  python -m roubing_engine.reasoning.validate_pipeline --plan-date 20260908 --tplus1 2026-09-09
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from roubing_engine.config import PROJECT_ROOT
from roubing_engine.reasoning import prompts, provenance, runner, schemas, task_package
from roubing_engine.reasoning.validation_factpack import (
    build as build_vfacts, validate_stage_d_result,
)
from roubing_engine.rules.retrieve import render_markdown, select

RUNS = PROJECT_ROOT / "runs"


def run_validation(plan_date: str, tplus1: str, backend: str = "codex",
                   dry_run: bool = False, snapshot: str = "OPEN_0935") -> dict:
    run_dir = RUNS / plan_date
    status_path = run_dir / "run_status.json"
    if not status_path.exists() or json.loads(status_path.read_text()).get("status") != "APPROVED":
        raise RuntimeError("Stage D requires an APPROVED EOD plan; schema/audit drafts are not executable")
    plan_path = run_dir / "executable_plan.json"
    if not plan_path.exists():
        raise SystemExit(f"no plan at {plan_path}; run eod_pipeline first")
    plan = json.loads(plan_path.read_text())

    suffix = snapshot.lower()
    prior_result = None
    if snapshot == "OPEN_0935":
        prior_path = run_dir / f"stage_d_result_{tplus1}_auction_0925.json"
        if not prior_path.exists():
            raise RuntimeError("OPEN_0935 requires the canonical AUCTION_0925 condition result")
        prior_result = json.loads(prior_path.read_text(encoding="utf-8"))
    vfacts = build_vfacts(
        plan, tplus1, snapshot=snapshot, prior_result=prior_result)
    facts_path = run_dir / f"validation_facts_{tplus1}_{suffix}.json"
    facts_path.write_text(
        json.dumps(vfacts, ensure_ascii=False, indent=2), encoding="utf-8")

    d_dir = run_dir / f"stage_d_{tplus1}_{suffix}"
    # Freeze methodological knowledge at T-day close.  A T+1 intraday replay
    # must not consume posts published later on T+1 or after the validation day.
    d_rules = render_markdown(select(
        kinds=["primitive", "exit", "discipline"], as_of=plan_date))
    task_package.write_package(d_dir, prompts.stage_d_instructions(), {
        "executable_plan.json": plan,
        "validation_facts.json": vfacts,
        "rules.md": d_rules,
        "schema.json": schemas.STAGE_D_SCHEMA,
    })

    if dry_run:
        return {"ok": True, "dry_run": True, "package": str(d_dir),
                "n_candidates": len(vfacts.get("action_leaf_facts", []))}

    prior_has_candidate = bool((prior_result or {}).get("current_action_candidate"))
    if snapshot == "OPEN_0935" and not prior_has_candidate:
        from roubing_engine.reasoning.condition_tree import terminal_no_action_result
        result = terminal_no_action_result(vfacts)
    else:
        task = runner.AgentTask(task_dir=d_dir, instructions=prompts.stage_d_instructions())
        result = runner.run(task, backend=backend)
    result = provenance.stamp(
        result, backend, d_dir,
        ["executable_plan.json", "validation_facts.json", "rules.md", "schema.json"],
    )
    problems = runner.validate(result, schemas.STAGE_D_SCHEMA)
    if result.get("tplus1") != tplus1:
        problems.append("$.tplus1: does not match validation facts")
    if result.get("snapshot") != snapshot:
        problems.append("$.snapshot: does not match validation facts")
    if result.get("as_of") != vfacts.get("as_of"):
        problems.append("$.as_of: does not match validation facts")
    plan_codes = {c.get("thscode") for c in vfacts.get("action_leaf_facts", [])}
    result_codes = {c.get("thscode") for c in result.get("leaf_results", [])}
    if result_codes != plan_codes:
        problems.append(
            f"$.leaf_results: codes differ from frozen snapshot plan; expected={sorted(plan_codes)} "
            f"got={sorted(result_codes)}")
    if not vfacts.get("market_check_data", {}).get("available"):
        if result.get("market_check", {}).get("index_held") is not None:
            problems.append("$.market_check.index_held: must be null when snapshot market data is absent")
    problems.extend(validate_stage_d_result(result, vfacts))
    from roubing_engine.reasoning.condition_tree import validate_result as validate_tree
    problems.extend(validate_tree(result, plan, vfacts, prior_result))
    draft_path = run_dir / f"stage_d_result_{tplus1}_{suffix}.draft.json"
    provenance.write(result, draft_path)
    if problems:
        raise RuntimeError(f"Stage D schema invalid: {'; '.join(problems)}")

    # Independent second pass: it receives the frozen facts and the proposed
    # result, and cannot repair or reinterpret missing observations.
    audit_dir = run_dir / f"stage_d_audit_{tplus1}_{suffix}"
    task_package.write_package(audit_dir, prompts.stage_d_audit_instructions(), {
        "stage_d_result.json": provenance.model_view(result),
        "validation_facts.json": vfacts,
        "executable_plan.json": plan,
        "rules.md": d_rules,
        "schema.json": schemas.AUDIT_SCHEMA,
    })
    audit_task = runner.AgentTask(task_dir=audit_dir,
                                  instructions=prompts.stage_d_audit_instructions())
    audit_result = runner.run(audit_task, backend=backend)
    audit_result = provenance.stamp(
        audit_result, backend, audit_dir,
        ["stage_d_result.json", "validation_facts.json", "executable_plan.json",
         "rules.md", "schema.json"],
    )
    audit_problems = runner.validate(audit_result, schemas.AUDIT_SCHEMA)
    if audit_result.get("verdict") == "PASS" and audit_result.get("violations"):
        audit_problems.append("$.violations: PASS audit must have an empty violations list")
    audit_path = run_dir / f"stage_d_audit_result_{tplus1}_{suffix}.json"
    provenance.write(audit_result, audit_path)
    if audit_problems or audit_result.get("verdict") != "PASS":
        raise RuntimeError("Stage D independent audit failed: " + "; ".join(
            audit_problems or audit_result.get("violations", [])))
    result_path = run_dir / f"stage_d_result_{tplus1}_{suffix}.json"
    provenance.write(result, result_path)

    return {"ok": True, "plan_date": plan_date, "tplus1": tplus1, "backend": backend,
            "snapshot": snapshot, "schema_problems": problems,
            "result_file": str(result_path)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--plan-date", required=True, help="T day YYYYMMDD (has stage_c_result)")
    p.add_argument("--tplus1", required=True, help="T+1 YYYY-MM-DD")
    p.add_argument("--backend", default="codex", choices=["codex", "cursor"])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--snapshot", default="OPEN_0935",
                   choices=["AUCTION_0925", "OPEN_0935"])
    args = p.parse_args()
    out = run_validation(args.plan_date, args.tplus1, backend=args.backend,
                         dry_run=args.dry_run, snapshot=args.snapshot)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
