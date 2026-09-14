"""EOD reasoning orchestrator: factpack -> Stage B -> Stage C -> audit -> battlecard.

Reasoning steps run as codex/cursor sub-agents (no API key). Use --dry-run to
only assemble task packages (deterministic, no agent) for inspection.

  python -m roubing_engine.reasoning.eod_pipeline --date 20260908 --dry-run
  python -m roubing_engine.reasoning.eod_pipeline --date 20260908 --backend cursor
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from roubing_engine.config import PROJECT_ROOT
from roubing_engine.reasoning import prompts, provenance, runner, schemas, task_package
from roubing_engine.reasoning.battlecard import render as render_card
from roubing_engine.reasoning.day_factpack import build as build_factpack
from roubing_engine.rules.retrieve import render_markdown, select
from roubing_engine.rules.evidence_bundle import (
    bundle_for_audit, render_audit_posts, render_bundle,
)

RUNS = PROJECT_ROOT / "runs"


def _invalidate_previous_run_outputs(run_dir: Path, *, keep_stage_b_draft: bool) -> list[str]:
    """Remove exact generated artifacts that could masquerade as this run.

    Market warehouse data and deferred T+1 inputs are outside this list.  A
    verified Stage-B draft may be kept only for the explicit resume path.
    """
    relative_files = [
        "stage_b/output/result.json", "stage_c1/output/result.json",
        "stage_c2/output/result.json", "audit/output/result.json",
        "stage_b_result.json", "stage_c1_result.draft.json",
        "stage_c_result.draft.json", "stage_c_result.json",
        "compiled_plan.draft.json", "executable_plan.json", "audit_result.json",
        "stage_c1_fidelity_result.json", "fidelity_result.json",
    ]
    if not keep_stage_b_draft:
        relative_files.extend([
            "stage_b_result.draft.json", "stage_b_result.raw.json",
            "stage_b_canonicalizations.json", "stage_b_resume.json",
            "stage_b_fidelity_result.json",
        ])
    removed = []
    for relative in relative_files:
        path = run_dir / relative
        if path.exists() and path.is_file():
            path.unlink()
            removed.append(relative)
    for card in run_dir.glob("battlecard_*.md"):
        if card.is_file():
            card.unlink()
            removed.append(card.name)
    return sorted(removed)


def _write_status(run_dir: Path, status: str, **details) -> dict:
    payload = {"status": status, **details}
    (run_dir / "run_status.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _model_error(error: Exception, stage_dir: Path) -> dict:
    """Reference logs without copying the full prompt into run_status.json."""
    return {
        "error_type": type(error).__name__,
        "message": (f"child process exited {error.returncode}"
                    if hasattr(error, "returncode") else str(error).splitlines()[-1][:500]),
        "stdout_log": str(stage_dir / "stdout.log"),
        "stderr_log": str(stage_dir / "stderr.log"),
    }


def _load_prev_state(date: str) -> dict:
    """Previous-day state ledger for chained (walk-forward) reasoning."""
    from roubing_engine.state.ledger import expected_previous_trade_date, load_prev_ledger
    state = load_prev_ledger(date)
    if not isinstance(state, dict):
        return {}
    expected = expected_previous_trade_date(date)
    if not expected or state.get("trade_date") != expected:
        return {}
    # Model-facing historical state must contain trading state only. Runtime
    # provenance carries the wall-clock generation date (which can be months
    # after a historical replay) and is irrelevant to the market inference.
    # Keeping it in yesterday_state.json is not look-ahead market data, but it
    # is avoidable temporal noise and makes the replay harder to audit.
    return {
        key: value for key, value in state.items()
        if key not in {"stage_b_provenance", "stage_c_provenance"}
    }


def _short_hash(path: Path) -> str | None:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:12] if path.exists() else None


def _canonicalize_stage_b_nodes(result: dict) -> tuple[dict, list[dict]]:
    """Enforce the one field implied completely by ``action_status``.

    A model may correctly describe a G8/G9-style *observation* yet leave the
    generator label populated.  The executable contract is unambiguous:
    anything other than ACTION_READY cannot open a generator.  Clear that
    serialization contradiction deterministically, preserve the raw model
    result separately, and record every change.  Missing fields or an invalid
    ACTION_READY node are never repaired here and still fail hard gates.
    """
    canonical = json.loads(json.dumps(result, ensure_ascii=False))
    changes = []
    for index, node in enumerate(canonical.get("nodes") or []):
        if node.get("action_status") != "ACTION_READY" and node.get("generator") is not None:
            changes.append({
                "path": f"nodes[{index}].generator",
                "from": node.get("generator"), "to": None,
                "reason": "非 ACTION_READY 节点在结构上禁止打开任何候选生成器",
            })
            node["generator"] = None
    return canonical, changes


def _load_reusable_stage_b(run_dir: Path, task_dir: Path, facts: dict) -> dict | None:
    """Reuse Stage B only when its exact frozen inputs still match.

    This is an explicit recovery path for a later-stage repair.  It never
    trusts an old narrative merely because a file exists: package hashes,
    schema, as-of and the current Stage-B fidelity gate must all pass.
    """
    if os.environ.get("ROUBING_RESUME_STAGE_B") != "1":
        return None
    draft = run_dir / "stage_b_result.draft.json"
    if not draft.exists():
        return None
    try:
        result = json.loads(draft.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    provenance_data = result.get("_provenance") or {}
    expected = provenance_data.get("input_hashes") or {}
    inputs = ("facts.json", "rules.md", "yesterday_state.json", "schema.json")
    if any(expected.get(name) != _short_hash(task_dir / name) for name in inputs):
        return None
    if provenance_data.get("instructions_hash") != _short_hash(task_dir / "instructions.md"):
        return None
    result, _ = _canonicalize_stage_b_nodes(result)
    problems = runner.validate(result, schemas.STAGE_B_SCHEMA)
    if result.get("as_of") != facts.get("as_of"):
        problems.append("$.as_of: does not match frozen facts")
    from roubing_engine.evaluation.fidelity import check_stage_b
    problems.extend(check_stage_b(result, facts))
    return None if problems else result


def _task_selection_facts(facts: dict) -> dict:
    """C1 receives no stock roster, names, codes, pool sizes or leaf hints."""
    catalog = {
        fact_id: item for fact_id, item in (facts.get("fact_catalog") or {}).items()
        if item.get("scope") != "STOCK"
    }
    return {
        "as_of": facts.get("as_of"), "trade_date": facts.get("trade_date"),
        "fact_catalog": catalog,
        "data_completeness": facts.get("data_completeness") or {},
        "path_comparison_contract": facts.get("path_comparison_contract") or {},
        "theme_hierarchy": facts.get("theme_hierarchy") or [],
        "theme_boundary_contract": facts.get("theme_boundary_contract") or {},
        "note": "Stage C1 input intentionally excludes every stock row/name/code and pool size",
    }


def _stock_plan_facts(facts: dict, selected_pools: list[dict]) -> dict:
    """C2 can inspect only stocks already frozen by C1-selected tasks."""
    allowed_codes = {
        row.get("thscode") for pool in selected_pools
        for field in ("pool", "validation_pool") for row in pool.get(field) or []
        if row.get("thscode")
    }
    result = json.loads(json.dumps(facts, ensure_ascii=False))
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
            feedback["rows"] = [row for row in feedback.get("rows") or []
                                if row.get("thscode") in allowed_codes]
    previous_feedback = result.get("previous_buyer_feedback") or {}
    if "rows" in previous_feedback:
        previous_feedback["rows"] = [row for row in previous_feedback.get("rows") or []
                                     if row.get("thscode") in allowed_codes]
    result["fact_catalog"] = {
        fact_id: item for fact_id, item in (result.get("fact_catalog") or {}).items()
        if item.get("scope") != "STOCK" or item.get("thscode") in allowed_codes
    }
    result["c2_allowed_stock_codes"] = sorted(allowed_codes)
    result["c2_scope_note"] = "Only C1-selected task pools are visible; other stocks are removed"
    return result


def run_pipeline(date: str, backend: str = "codex", dry_run: bool = False,
                 with_daily: bool = True) -> dict:
    run_dir = RUNS / date
    run_dir.mkdir(parents=True, exist_ok=True)
    if not dry_run:
        removed = _invalidate_previous_run_outputs(
            run_dir, keep_stage_b_draft=os.environ.get("ROUBING_RESUME_STAGE_B") == "1")
        (run_dir / "invalidated_previous_outputs.json").write_text(json.dumps({
            "removed": removed,
            "stage_b_draft_preserved": os.environ.get("ROUBING_RESUME_STAGE_B") == "1",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_status(run_dir, "RUNNING", backend=backend)

    # 1) deterministic fact pack
    facts = build_factpack(date, client=None, with_index=with_daily)
    (run_dir / "factpack.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")

    if not facts.get("available"):
        return {"ok": False, "reason": "no facts", "date": date}

    yesterday = _load_prev_state(date)

    # 2) Stage B package (include generator units so nodes can be mapped to G1..G12)
    b_dir = run_dir / "stage_b"
    b_rules = render_markdown(select(
        kinds=["environment", "node", "generator", "discipline"], as_of=date))
    task_package.write_package(b_dir, prompts.stage_b_instructions(), {
        "facts.json": facts,
        "rules.md": b_rules,
        "yesterday_state.json": yesterday,
        "schema.json": schemas.STAGE_B_SCHEMA,
    })

    # 3) Stage C package (stage_b.json filled after B runs; pre-write rules)
    c1_dir = run_dir / "stage_c1"
    c_dir = run_dir / "stage_c2"
    c_rules = render_markdown(select(
        kinds=["generator", "role", "exit", "primitive", "discipline"], as_of=date))

    if dry_run:
        task_package.write_package(c1_dir, prompts.stage_c1_instructions(), {
            "facts.json": _task_selection_facts(facts), "rules.md": c_rules,
            "stage_b.json": {"note": "placeholder (dry-run, Stage B not executed)"},
            "task_summaries.json": {"status": "DRY_RUN_PLACEHOLDER", "tasks": []},
            "schema.json": schemas.STAGE_C1_SCHEMA,
        })
        task_package.write_package(c_dir, prompts.stage_c_instructions(), {
            "facts.json": facts, "rules.md": c_rules,
            "stage_b.json": {"note": "placeholder (dry-run, Stage B not executed)"},
            "c1_decision.json": {"status": "DRY_RUN_PLACEHOLDER"},
            "selected_candidate_pools.json": [],
            "schema.json": schemas.STAGE_C_SCHEMA,
        })
        return {"ok": True, "dry_run": True, "date": date,
                "packages": [str(b_dir), str(c1_dir), str(c_dir)],
                "themes": len(facts.get("themes", [])),
                "observations": len(facts.get("stage_b_observation_universe", []))}

    # 4) run Stage B
    b_result = _load_reusable_stage_b(run_dir, b_dir, facts)
    if b_result is None:
        b_task = runner.AgentTask(task_dir=b_dir, instructions=prompts.stage_b_instructions())
        try:
            b_result = runner.run(b_task, backend=backend)
        except Exception as e:  # noqa: BLE001 - model failures are a pipeline state
            return {"ok": False, "date": date, "backend": backend,
                    **_write_status(run_dir, "BLOCKED_MODEL_STAGE_B",
                                    problems=[_model_error(e, b_dir)])}
        provenance.write(b_result, run_dir / "stage_b_result.raw.json")
        b_result, canonicalizations = _canonicalize_stage_b_nodes(b_result)
        (run_dir / "stage_b_canonicalizations.json").write_text(json.dumps({
            "changes": canonicalizations,
            "status": "CHANGED" if canonicalizations else "UNCHANGED",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        b_result = provenance.stamp(
            b_result, backend, b_dir,
            ["facts.json", "rules.md", "yesterday_state.json", "schema.json"],
        )
    else:
        raw_reused = json.loads(
            (run_dir / "stage_b_result.draft.json").read_text(encoding="utf-8"))
        _, canonicalizations = _canonicalize_stage_b_nodes(raw_reused)
        (run_dir / "stage_b_canonicalizations.json").write_text(json.dumps({
            "changes": canonicalizations,
            "status": "CHANGED" if canonicalizations else "UNCHANGED",
            "source": "verified reusable Stage B draft",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        (run_dir / "stage_b_resume.json").write_text(json.dumps({
            "status": "REUSED_VERIFIED_INPUTS",
            "source": str(run_dir / "stage_b_result.draft.json"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    b_problems = runner.validate(b_result, schemas.STAGE_B_SCHEMA)
    if b_result.get("as_of") != facts.get("as_of"):
        b_problems.append("$.as_of: does not match frozen facts")
    provenance.write(b_result, run_dir / "stage_b_result.draft.json")
    if b_problems:
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_SCHEMA_STAGE_B", problems=b_problems)}

    from roubing_engine.evaluation.fidelity import check_stage_b
    b_fidelity = check_stage_b(b_result, facts)
    (run_dir / "stage_b_fidelity_result.json").write_text(
        json.dumps({"violations": b_fidelity,
                    "verdict": "PASS" if not b_fidelity else "NEEDS_REVISION"},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    if b_fidelity:
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_FIDELITY_STAGE_B", problems=b_fidelity)}

    # 5) convert method nodes + daily relational facts into concrete tasks.
    # This layer is deterministic and cannot hard-code a theme or stock.
    from roubing_engine.reasoning.task_resolver import (
        build_task_pools, resolve, select_task_pools, summarize_tasks,
    )
    task_bundle = resolve(b_result, facts)
    candidate_pools = build_task_pools(task_bundle, facts)
    (run_dir / "task_candidates.json").write_text(
        json.dumps(task_bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "candidate_pools.json").write_text(
        json.dumps(candidate_pools, ensure_ascii=False, indent=2), encoding="utf-8")

    # 5a) C1 sees tasks without stocks/counts and selects by node function only.
    task_summaries = summarize_tasks(task_bundle)
    task_package.write_package(c1_dir, prompts.stage_c1_instructions(), {
        "facts.json": _task_selection_facts(facts), "rules.md": c_rules,
        "stage_b.json": provenance.model_view(b_result),
        "task_summaries.json": task_summaries,
        "schema.json": schemas.STAGE_C1_SCHEMA,
    })
    c1_task = runner.AgentTask(task_dir=c1_dir, instructions=prompts.stage_c1_instructions())
    try:
        c1_result = runner.run(c1_task, backend=backend)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_MODEL_STAGE_C1",
                                problems=[_model_error(e, c1_dir)])}
    c1_result = provenance.stamp(
        c1_result, backend, c1_dir,
        ["facts.json", "rules.md", "stage_b.json", "task_summaries.json", "schema.json"],
    )
    c1_problems = runner.validate(c1_result, schemas.STAGE_C1_SCHEMA)
    if c1_result.get("as_of") != facts.get("as_of"):
        c1_problems.append("$.as_of: does not match frozen facts")
    provenance.write(c1_result, run_dir / "stage_c1_result.draft.json")
    if c1_problems:
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_SCHEMA_STAGE_C1", problems=c1_problems)}
    from roubing_engine.evaluation.fidelity import check_task_selection
    c1_fidelity = check_task_selection(b_result, c1_result, task_bundle, facts)
    (run_dir / "stage_c1_fidelity_result.json").write_text(json.dumps({
        "verdict": "PASS" if not c1_fidelity else "NEEDS_REVISION",
        "violations": c1_fidelity,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    if c1_fidelity:
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_FIDELITY_STAGE_C1",
                                problems=c1_fidelity)}

    selected_pools = select_task_pools(c1_result, candidate_pools)
    task_package.write_package(c_dir, prompts.stage_c_instructions(), {
        "facts.json": _stock_plan_facts(facts, selected_pools),
        "rules.md": c_rules, "stage_b.json": provenance.model_view(b_result),
        "c1_decision.json": provenance.model_view(c1_result),
        "selected_candidate_pools.json": selected_pools,
        "schema.json": schemas.STAGE_C_SCHEMA,
    })
    c_task = runner.AgentTask(task_dir=c_dir, instructions=prompts.stage_c_instructions())
    try:
        c_result = runner.run(c_task, backend=backend)
    except Exception as e:  # noqa: BLE001 - model failures are a pipeline state
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_MODEL_STAGE_C",
                                problems=[_model_error(e, c_dir)])}
    c_result = provenance.stamp(
        c_result, backend, c_dir,
        ["facts.json", "rules.md", "stage_b.json", "c1_decision.json",
         "selected_candidate_pools.json", "schema.json"],
    )
    c_problems = runner.validate(c_result, schemas.STAGE_C_SCHEMA)
    if c_result.get("as_of") != facts.get("as_of"):
        c_problems.append("$.as_of: does not match frozen facts")
    provenance.write(c_result, run_dir / "stage_c_result.draft.json")
    if c_problems:
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_SCHEMA_STAGE_C", problems=c_problems)}

    # Programmatic fidelity is a hard gate, independent of the model audit.
    from roubing_engine.evaluation.fidelity import check_task_plan
    fidelity = check_task_plan(
        b_result, c_result, task_bundle, candidate_pools, facts)
    (run_dir / "fidelity_result.json").write_text(
        json.dumps(fidelity, ensure_ascii=False, indent=2), encoding="utf-8")
    if fidelity.get("verdict") != "PASS":
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_FIDELITY",
                                problems=fidelity.get("violations", []))}

    # Compile the narrative into a closed next-day condition plan.  A model
    # output is not executable merely because it passed JSON Schema.
    from roubing_engine.reasoning.plan_compiler import compile_plan
    compiled = compile_plan(
        b_result, c_result, task_bundle, candidate_pools, facts)
    provenance.write(compiled, run_dir / "compiled_plan.draft.json")
    if compiled.get("verdict") != "PASS":
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_PLAN_COMPILER",
                                problems=compiled.get("violations", []))}

    # 6) audit
    a_dir = run_dir / "audit"
    audit_rules = render_markdown(select(kinds=["discipline"], as_of=date))
    audit_evidence = bundle_for_audit(
        b_result, c_result, task_bundle, compiled, as_of=date)
    combined_rules = (
        "# Stage B 实际规则\n\n" + b_rules
        + "\n\n# Stage C 实际规则\n\n" + c_rules
        + "\n\n# 审计纪律规则\n\n" + audit_rules
    )
    task_package.write_package(a_dir, prompts.audit_instructions(), {
        "facts.json": facts,
        "stage_b.json": provenance.model_view(b_result),
        "stage_c1.json": provenance.model_view(c1_result),
        "stage_c.json": provenance.model_view(c_result),
        "task_candidates.json": task_bundle,
        "candidate_pools.json": candidate_pools,
        "compiled_plan.draft.json": compiled,
        "rules.md": combined_rules,
        "audit_evidence_manifest.json": audit_evidence,
        "audit_evidence_coverage.md": render_bundle(audit_evidence),
        "original_posts.md": render_audit_posts(audit_evidence),
        "schema.json": schemas.AUDIT_SCHEMA,
    })
    a_task = runner.AgentTask(task_dir=a_dir, instructions=prompts.audit_instructions())
    try:
        a_result = runner.run(a_task, backend=backend)
    except Exception as e:  # noqa: BLE001
        a_result = {"verdict": "AUDIT_ERROR", "violations": [str(e)], "counter_arguments": []}
    a_result = provenance.stamp(
        a_result, backend, a_dir,
        ["facts.json", "stage_b.json", "stage_c1.json", "stage_c.json",
         "task_candidates.json", "candidate_pools.json", "compiled_plan.draft.json",
         "rules.md", "audit_evidence_manifest.json", "audit_evidence_coverage.md",
         "original_posts.md", "schema.json"])
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
    provenance.write(compiled["executable_plan"], run_dir / "executable_plan.json")

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
