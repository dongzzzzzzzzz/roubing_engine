"""EOD reasoning orchestrator: factpack -> Stage B -> Stage C -> audit -> battlecard.

Reasoning steps run as codex/cursor sub-agents (no API key). Use --dry-run to
only assemble task packages (deterministic, no agent) for inspection.

  python -m roubing_engine.reasoning.eod_pipeline --date 20260908 --dry-run
  python -m roubing_engine.reasoning.eod_pipeline --date 20260908 --backend cursor
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from roubing_engine.config import PROJECT_ROOT
from roubing_engine.reasoning import prompts, provenance, runner, schemas, task_package
from roubing_engine.reasoning.battlecard import render as render_card
from roubing_engine.reasoning.day_factpack import build as build_factpack
from roubing_engine.rules.retrieve import render_markdown, select
from roubing_engine.rules.corpus_index import render_search

RUNS = PROJECT_ROOT / "runs"


def _write_status(run_dir: Path, status: str, **details) -> dict:
    payload = {"status": status, **details}
    (run_dir / "run_status.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _load_prev_state(date: str) -> dict:
    """Previous-day state ledger for chained (walk-forward) reasoning."""
    from roubing_engine.state.ledger import load_prev_ledger
    return load_prev_ledger(date)


def run_pipeline(date: str, backend: str = "codex", dry_run: bool = False,
                 with_daily: bool = True) -> dict:
    run_dir = RUNS / date
    run_dir.mkdir(parents=True, exist_ok=True)

    # 1) deterministic fact pack
    facts = build_factpack(date, client=None, with_index=with_daily)
    (run_dir / "factpack.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")

    if not facts.get("available"):
        return {"ok": False, "reason": "no facts", "date": date}

    yesterday = _load_prev_state(date)

    # 2) Stage B package (include generator units so nodes can be mapped to G1..G12)
    b_dir = run_dir / "stage_b"
    b_rules = render_markdown(select(kinds=["environment", "node", "generator", "discipline"]))
    b_originals = render_search(["主流", "分歧", "修复", "节点", "退潮", "轮动"], limit=10)
    task_package.write_package(b_dir, prompts.stage_b_instructions(), {
        "facts.json": facts,
        "rules.md": b_rules,
        "original_posts.md": b_originals,
        "yesterday_state.json": yesterday,
        "schema.json": schemas.STAGE_B_SCHEMA,
    })

    # 3) Stage C package (stage_b.json filled after B runs; pre-write rules)
    c_dir = run_dir / "stage_c"
    c_rules = render_markdown(select(
        kinds=["generator", "role", "exit", "primitive", "discipline"]))

    if dry_run:
        # assemble C with a placeholder so the package is inspectable
        task_package.write_package(c_dir, prompts.stage_c_instructions(), {
            "facts.json": facts, "rules.md": c_rules,
            "stage_b.json": {"note": "placeholder (dry-run, Stage B not executed)"},
            "candidate_pools.json": [],
            "original_posts.md": render_search(
                ["核心", "容量", "补涨", "伴飞", "二波", "唯一性", "强弱切换"],
                limit=12),
            "schema.json": schemas.STAGE_C_SCHEMA,
        })
        return {"ok": True, "dry_run": True, "date": date,
                "packages": [str(b_dir), str(c_dir)],
                "themes": len(facts.get("themes", [])),
                "observations": len(facts.get("stage_b_observation_universe", []))}

    # 4) run Stage B
    b_task = runner.AgentTask(task_dir=b_dir, instructions=prompts.stage_b_instructions())
    b_result = runner.run(b_task, backend=backend)
    b_result = provenance.stamp(
        b_result, backend, b_dir,
        ["facts.json", "rules.md", "original_posts.md", "yesterday_state.json", "schema.json"],
    )
    b_problems = runner.validate(b_result, schemas.STAGE_B_SCHEMA)
    if b_result.get("as_of") != facts.get("as_of"):
        b_problems.append("$.as_of: does not match frozen facts")
    provenance.write(b_result, run_dir / "stage_b_result.draft.json")
    if b_problems:
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_SCHEMA_STAGE_B", problems=b_problems)}

    # 5) build deterministic candidate pools from Stage B nodes, feed Stage C
    from roubing_engine.candidates.generators import build_pools_from_nodes
    as_of_dash = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    candidate_pools = build_pools_from_nodes(b_result.get("nodes", []), as_of_dash)
    (run_dir / "candidate_pools.json").write_text(
        json.dumps(candidate_pools, ensure_ascii=False, indent=2), encoding="utf-8")
    c_originals = render_search(
        ["核心", "容量", "补涨", "伴飞", "二波", "唯一性", "强弱切换", "该强不强"],
        limit=12,
    )
    task_package.write_package(c_dir, prompts.stage_c_instructions(), {
        "facts.json": facts, "rules.md": c_rules, "stage_b.json": b_result,
        "candidate_pools.json": candidate_pools,
        "original_posts.md": c_originals,
        "schema.json": schemas.STAGE_C_SCHEMA,
    })
    c_task = runner.AgentTask(task_dir=c_dir, instructions=prompts.stage_c_instructions())
    c_result = runner.run(c_task, backend=backend)
    c_result = provenance.stamp(
        c_result, backend, c_dir,
        ["facts.json", "rules.md", "original_posts.md", "stage_b.json",
         "candidate_pools.json", "schema.json"],
    )
    c_problems = runner.validate(c_result, schemas.STAGE_C_SCHEMA)
    if c_result.get("as_of") != facts.get("as_of"):
        c_problems.append("$.as_of: does not match frozen facts")
    provenance.write(c_result, run_dir / "stage_c_result.draft.json")
    if c_problems:
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_SCHEMA_STAGE_C", problems=c_problems)}

    # Programmatic fidelity is a hard gate, independent of the model audit.
    from roubing_engine.evaluation.fidelity import check_plan
    fidelity = check_plan(b_result, c_result, candidate_pools)
    (run_dir / "fidelity_result.json").write_text(
        json.dumps(fidelity, ensure_ascii=False, indent=2), encoding="utf-8")
    if fidelity.get("verdict") != "PASS":
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_FIDELITY",
                                problems=fidelity.get("violations", []))}

    # 6) audit
    a_dir = run_dir / "audit"
    task_package.write_package(a_dir, prompts.audit_instructions(), {
        "stage_b.json": b_result, "stage_c.json": c_result,
        "rules.md": render_markdown(select(kinds=["discipline"])),
        "original_posts.md": render_search(
            ["跟风", "一日游", "主动", "被动", "分歧", "弱转强", "核心"], limit=10),
        "schema.json": schemas.AUDIT_SCHEMA,
    })
    a_task = runner.AgentTask(task_dir=a_dir, instructions=prompts.audit_instructions())
    try:
        a_result = runner.run(a_task, backend=backend)
    except Exception as e:  # noqa: BLE001
        a_result = {"verdict": "AUDIT_ERROR", "violations": [str(e)], "counter_arguments": []}
    a_result = provenance.stamp(
        a_result, backend, a_dir,
        ["stage_b.json", "stage_c.json", "rules.md", "original_posts.md", "schema.json"])
    a_problems = runner.validate(a_result, schemas.AUDIT_SCHEMA)
    if a_result.get("verdict") == "PASS" and a_result.get("violations"):
        a_problems.append("$.violations: PASS audit must have an empty violations list")
    provenance.write(a_result, run_dir / "audit_result.json")
    if a_problems:
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_SCHEMA_AUDIT", problems=a_problems)}
    if a_result.get("verdict") != "PASS":
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_AUDIT",
                                problems=a_result.get("violations", []))}

    # Only audited plans become canonical inputs to Stage D / future ledgers.
    provenance.write(b_result, run_dir / "stage_b_result.json")
    provenance.write(c_result, run_dir / "stage_c_result.json")

    # 7) persist state ledger for next-day chaining
    from roubing_engine.state.ledger import save_ledger
    save_ledger(date, b_result, c_result)

    # 8) battlecard
    card = render_card(date, b_result, c_result)
    card_path = run_dir / f"battlecard_{backend}.md"
    card_path.write_text(card, encoding="utf-8")

    status = _write_status(run_dir, "APPROVED", audit_verdict="PASS")
    return {"ok": True, "date": date, "backend": backend, "status": status["status"],
            "schema_problems": {"stage_b": b_problems, "stage_c": c_problems},
            "audit_verdict": a_result.get("verdict"),
            "battlecard": str(card_path)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True, help="YYYYMMDD")
    p.add_argument("--backend", default="codex", choices=["codex", "cursor"])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-daily", action="store_true",
                   help="skip external index-context fetch; local daily facts remain available")
    args = p.parse_args()
    out = run_pipeline(args.date, backend=args.backend, dry_run=args.dry_run,
                       with_daily=not args.no_daily)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
