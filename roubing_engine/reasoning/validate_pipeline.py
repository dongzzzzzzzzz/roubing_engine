"""Stage D orchestrator: validate a T-day plan against T+1 reality via sub-agent.

  python -m roubing_engine.reasoning.validate_pipeline --plan-date 20260908 --tplus1 2026-09-09
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from roubing_engine.config import PROJECT_ROOT
from roubing_engine.reasoning import prompts, provenance, runner, schemas, task_package
from roubing_engine.reasoning.validation_factpack import build as build_vfacts
from roubing_engine.rules.retrieve import render_markdown, select
from roubing_engine.rules.corpus_index import render_search

RUNS = PROJECT_ROOT / "runs"


def run_validation(plan_date: str, tplus1: str, backend: str = "codex",
                   dry_run: bool = False, snapshot: str = "OPEN_0935") -> dict:
    run_dir = RUNS / plan_date
    status_path = run_dir / "run_status.json"
    if not status_path.exists() or json.loads(status_path.read_text()).get("status") != "APPROVED":
        raise RuntimeError("Stage D requires an APPROVED EOD plan; schema/audit drafts are not executable")
    plan_path = run_dir / "stage_c_result.json"
    if not plan_path.exists():
        raise SystemExit(f"no plan at {plan_path}; run eod_pipeline first")
    plan = json.loads(plan_path.read_text())

    vfacts = build_vfacts(plan.get("candidates", []), tplus1, snapshot=snapshot)
    suffix = snapshot.lower()
    facts_path = run_dir / f"validation_facts_{tplus1}_{suffix}.json"
    facts_path.write_text(
        json.dumps(vfacts, ensure_ascii=False, indent=2), encoding="utf-8")

    d_dir = run_dir / f"stage_d_{tplus1}_{suffix}"
    d_rules = render_markdown(select(kinds=["primitive", "exit", "discipline"]))
    task_package.write_package(d_dir, prompts.stage_d_instructions(), {
        "plan.json": {"candidates": plan.get("candidates", []), "paths": plan.get("paths", {})},
        "validation_facts.json": vfacts,
        "rules.md": d_rules,
        "original_posts.md": render_search(
            ["竞价", "开盘五分钟", "承接", "弱转强", "主动", "被动"], limit=10),
        "schema.json": schemas.STAGE_D_SCHEMA,
    })

    if dry_run:
        return {"ok": True, "dry_run": True, "package": str(d_dir),
                "n_candidates": len(vfacts.get("candidates", []))}

    task = runner.AgentTask(task_dir=d_dir, instructions=prompts.stage_d_instructions())
    result = runner.run(task, backend=backend)
    result = provenance.stamp(
        result, backend, d_dir,
        ["plan.json", "validation_facts.json", "rules.md", "original_posts.md", "schema.json"],
    )
    problems = runner.validate(result, schemas.STAGE_D_SCHEMA)
    if result.get("tplus1") != tplus1:
        problems.append("$.tplus1: does not match validation facts")
    if result.get("snapshot") != snapshot:
        problems.append("$.snapshot: does not match validation facts")
    if result.get("as_of") != vfacts.get("as_of"):
        problems.append("$.as_of: does not match validation facts")
    plan_codes = {c.get("thscode") for c in plan.get("candidates", [])}
    result_codes = {c.get("thscode") for c in result.get("candidate_results", [])}
    if result_codes != plan_codes:
        problems.append(
            f"$.candidate_results: codes differ from frozen plan; expected={sorted(plan_codes)} "
            f"got={sorted(result_codes)}")
    if snapshot == "AUCTION_0925":
        for index, candidate in enumerate(result.get("candidate_results", [])):
            if candidate.get("open5m_conclusion") != "DATA_INSUFFICIENT":
                problems.append(
                    f"$.candidate_results[{index}].open5m_conclusion: "
                    "09:25 snapshot has no open-five-minute facts")
    if not vfacts.get("market_check_data", {}).get("available"):
        if result.get("market_check", {}).get("index_held") is not None:
            problems.append("$.market_check.index_held: must be null when snapshot market data is absent")
    draft_path = run_dir / f"stage_d_result_{tplus1}_{suffix}.draft.json"
    provenance.write(result, draft_path)
    if problems:
        raise RuntimeError(f"Stage D schema invalid: {'; '.join(problems)}")
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
