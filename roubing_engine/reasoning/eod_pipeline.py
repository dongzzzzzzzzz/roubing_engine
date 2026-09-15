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
from roubing_engine.reasoning import (
    prompts, protocols, projections, provenance, runner, schemas, semantic_audit,
    task_package,
)
from roubing_engine.reasoning.battlecard import render as render_card
from roubing_engine.reasoning.day_factpack import build as build_factpack
from roubing_engine.rules.retrieve import render_markdown, select
from roubing_engine.rules.evidence_bundle import bundle_for_audit, render_bundle

RUNS = PROJECT_ROOT / "runs"


def _invalidate_previous_run_outputs(run_dir: Path, *, keep_stage_b_draft: bool) -> list[str]:
    """Remove exact generated artifacts that could masquerade as this run.

    Market warehouse data and deferred T+1 inputs are outside this list.  A
    verified Stage-B draft may be kept only for the explicit resume path.
    """
    relative_files = [
        "m1_macro/output/result.json", "m2_nodes/output/result.json",
        "m3_plan/output/result.json", "m1_macro_audit_1/output/result.json",
        "m2_nodes_audit_1/output/result.json", "m3_plan_audit_1/output/result.json",
        "stage_b/output/result.json", "stage_c1/output/result.json",
        "stage_c2/output/result.json", "audit/output/result.json",
        "audit/original_posts.md",
        "macro_result.json", "node_result.json", "macro_result.draft.json",
        "node_result.draft.json", "stage_b_result.json", "stage_c1_result.draft.json",
        "stage_c_result.draft.json", "stage_c_result.json",
        "compiled_plan.draft.json", "executable_plan.json", "audit_result.json",
        "stage_c1_fidelity_result.json", "fidelity_result.json", "token_report.json",
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
    for generated in list(run_dir.glob("m*_audit_result_*.json")) + list(run_dir.glob("m*_retry_*/output/result.json")):
        if generated.is_file():
            generated.unlink()
            removed.append(str(generated.relative_to(run_dir)))
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


def _canonicalize_stage_c1_tasks(result: dict) -> tuple[dict, list[dict]]:
    """Clear task identity fields when C1 deliberately selects no task."""
    canonical = json.loads(json.dumps(result, ensure_ascii=False))
    changes = []
    for field in ("primary_task", "alternative_task"):
        task = canonical.get(field) or {}
        if task.get("status") == "SELECTED":
            continue
        for key in ("task_id", "task_type", "theme", "node_id"):
            if task.get(key) is not None:
                changes.append({
                    "path": f"{field}.{key}",
                    "from": task.get(key), "to": None,
                    "reason": "C1 未选中任务时任务身份字段必须为空；理由保留在 selection_logic",
                })
                task[key] = None
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


def _protocol_payload(pack_id: str) -> dict:
    return {
        "pack": protocols.PACKS[pack_id].__dict__,
        "stage1_observations": protocols.STAGE1_OBSERVATIONS,
        "environment_hypotheses": protocols.ENVIRONMENT_HYPOTHESES,
        "lifecycle_stages": protocols.LIFECYCLE_STAGES,
        "generators": protocols.GENERATORS,
        "node_question_fields": protocols.NODE_QUESTION_FIELDS,
        "trace_statuses": protocols.TRACE_STATUSES,
    }


def _read_token_usage(stage_dir: Path) -> dict:
    path = stage_dir / "token_usage.json"
    if not path.exists():
        return {"status": "UNAVAILABLE", "stage_dir": str(stage_dir)}
    data = json.loads(path.read_text(encoding="utf-8"))
    data["stage_dir"] = str(stage_dir)
    return data


def _write_token_report(run_dir: Path, stage_dirs: list[Path]) -> dict:
    stages = {stage_dir.name: _read_token_usage(stage_dir) for stage_dir in stage_dirs}
    totals = {
        "input_tokens": 0, "cached_input_tokens": 0,
        "output_tokens": 0, "reasoning_tokens": 0, "total_tokens": 0,
    }
    unavailable = []
    for name, usage in stages.items():
        if usage.get("status") != "AVAILABLE":
            unavailable.append(name)
            continue
        for key in totals:
            totals[key] += int(usage.get(key) or 0)
    report = {
        "status": "PARTIAL" if unavailable else "AVAILABLE",
        "stages": stages,
        "totals": totals,
        "unavailable_stages": unavailable,
    }
    (run_dir / "token_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _audit_and_retry_pack(*, pack_id: str, run_dir: Path, stage_dir: Path,
                          facts_file: str, facts_payload: dict, result: dict,
                          result_schema: dict, rules: str, backend: str,
                          program_problems: list[str],
                          max_retries: int = 2) -> tuple[dict, dict, list[Path]]:
    """Run program coverage plus medium semantic audit, with targeted retries."""
    pack = protocols.PACKS[pack_id]
    audit_dirs: list[Path] = []
    current = result
    audit_result = {
        "verdict": "PASS" if not program_problems else "NEEDS_REVISION",
        "violations": list(program_problems),
        "counter_arguments": [],
    }
    for attempt in range(max_retries + 1):
        audit_dir = run_dir / f"{stage_dir.name}_audit_{attempt + 1}"
        audit_dirs.append(audit_dir)
        task_package.write_package(audit_dir, prompts.semantic_audit_instructions(pack_id), {
            "stage_result.json": provenance.model_view(current),
            "stage_facts.json": facts_payload,
            "rules.md": rules,
            "protocol.json": _protocol_payload(pack_id),
            "schema.json": schemas.AUDIT_SCHEMA,
        })
        if audit_result.get("verdict") == "PASS":
            audit_task = runner.AgentTask(
                task_dir=audit_dir,
                instructions=prompts.semantic_audit_instructions(pack_id),
                reasoning_effort=pack.audit_reasoning_effort,
            )
            audit_result = runner.run(audit_task, backend=backend)
            audit_result = provenance.stamp(
                audit_result, backend, audit_dir,
                ["stage_result.json", "stage_facts.json", "rules.md",
                 "protocol.json", "schema.json"],
            )
        provenance.write(
            audit_result, run_dir / f"{stage_dir.name}_audit_result_{attempt + 1}.json")
        audit_problems = runner.validate(audit_result, schemas.AUDIT_SCHEMA)
        if audit_result.get("verdict") == "PASS" and audit_result.get("violations"):
            audit_problems.append("$.violations: PASS audit must have an empty violations list")
        if not audit_problems and audit_result.get("verdict") == "PASS":
            return current, audit_result, audit_dirs
        if attempt >= max_retries:
            break
        retry_dir = run_dir / f"{stage_dir.name}_retry_{attempt + 1}"
        audit_dirs.append(retry_dir)
        task_package.write_package(retry_dir, prompts.targeted_retry_instructions(pack_id), {
            facts_file: facts_payload,
            "stage_facts.json": facts_payload,
            "previous_result.json": provenance.model_view(current),
            "audit_result.json": provenance.model_view(audit_result),
            "rules.md": rules,
            "protocol.json": _protocol_payload(pack_id),
            "schema.json": result_schema,
        })
        retry_task = runner.AgentTask(
            task_dir=retry_dir,
            instructions=prompts.targeted_retry_instructions(pack_id),
            reasoning_effort=pack.core_reasoning_effort,
        )
        current = runner.run(retry_task, backend=backend)
        current = provenance.stamp(
            current, backend, retry_dir,
            [facts_file, "stage_facts.json", "previous_result.json", "audit_result.json",
             "rules.md", "protocol.json", "schema.json"],
        )
        schema_problems = runner.validate(current, result_schema)
        if schema_problems:
            audit_result = {
                "verdict": "NEEDS_REVISION",
                "violations": schema_problems,
                "counter_arguments": [],
            }
        else:
            audit_result = {"verdict": "PASS", "violations": [], "counter_arguments": []}
    return current, audit_result, audit_dirs


def _empty_task_selection(path_kind: str, reason: str, rule_ids: list[str]) -> dict:
    return {
        "path_kind": path_kind, "status": "NONE", "task_id": None,
        "task_type": None, "theme": None, "node_id": None,
        "missing_function": reason, "selection_logic": [reason],
        "supporting_fact_ids": [], "rule_ids": rule_ids,
        "rejected_task_ids": [],
    }


def _no_action_stage_c(as_of: str, reason: str, rule_ids: list[str]) -> dict:
    primary = _empty_task_selection("PRIMARY", reason, rule_ids)
    alternative = _empty_task_selection("ALTERNATIVE", reason, rule_ids)
    return {
        "as_of": as_of,
        "task_selection": {
            "primary_task": primary,
            "alternative_task": alternative,
            "no_action_conditions": [reason],
        },
        "path_plans": [],
        "final_action_plan": {
            "status": "NO_ACTION", "primary_ref": None, "backup_ref": None,
            "switch_rule": "无独立可执行对象，不打开次日动作",
            "no_action_conditions": [reason], "rule_ids": rule_ids,
        },
        "unknowns": [],
    }


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
    stage_dirs: list[Path] = []

    # M1: environment + direction lifecycle
    m1_dir = run_dir / "m1_macro"
    m1_rules = render_markdown(select(
        kinds=["environment", "node", "discipline"], as_of=date))
    macro_facts = projections.project_macro_facts(facts, yesterday)
    task_package.write_package(m1_dir, prompts.m1_macro_instructions(), {
        "macro_facts.json": macro_facts,
        "rules.md": m1_rules,
        "yesterday_state.json": yesterday,
        "protocol.json": _protocol_payload("M1"),
        "schema.json": schemas.M1_SCHEMA,
    })

    # M2/M3 packages are materialized as placeholders in dry-run mode so the
    # user can inspect the exact staged protocol without launching models.
    m2_dir = run_dir / "m2_nodes"
    m3_dir = run_dir / "m3_plan"
    m2_rules = render_markdown(select(
        kinds=["generator", "node", "primitive", "discipline"], as_of=date))
    m3_rules = render_markdown(select(
        kinds=["generator", "role", "exit", "primitive", "discipline"], as_of=date))
    if dry_run:
        task_package.write_package(m2_dir, prompts.m2_node_instructions(), {
            "node_facts.json": {"note": "placeholder (dry-run, M1 not executed)"},
            "macro_result.json": {"note": "placeholder (dry-run, M1 not executed)"},
            "rules.md": m2_rules,
            "protocol.json": _protocol_payload("M2"),
            "schema.json": schemas.M2_SCHEMA,
        })
        task_package.write_package(m3_dir, prompts.m3_plan_instructions(), {
            "plan_facts.json": {"note": "placeholder (dry-run, M2 not executed)"},
            "macro_result.json": {"note": "placeholder"},
            "node_result.json": {"note": "placeholder"},
            "task_candidates.json": {"status": "DRY_RUN_PLACEHOLDER", "tasks": []},
            "selected_candidate_pools.json": [],
            "rules.md": m3_rules,
            "protocol.json": _protocol_payload("M3"),
            "schema.json": schemas.STAGE_C_SCHEMA,
        })
        return {"ok": True, "dry_run": True, "date": date,
                "packages": [str(m1_dir), str(m2_dir), str(m3_dir)],
                "themes": len(facts.get("themes", [])),
                "observations": len(facts.get("stage_b_observation_universe", []))}

    try:
        m1_task = runner.AgentTask(
            task_dir=m1_dir,
            instructions=prompts.m1_macro_instructions(),
            reasoning_effort=protocols.PACKS["M1"].core_reasoning_effort,
        )
        macro_result = runner.run(m1_task, backend=backend)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_MODEL_M1",
                                problems=[_model_error(e, m1_dir)])}
    stage_dirs.append(m1_dir)
    macro_result = provenance.stamp(
        macro_result, backend, m1_dir,
        ["macro_facts.json", "rules.md", "yesterday_state.json",
         "protocol.json", "schema.json"],
    )
    m1_problems = runner.validate(macro_result, schemas.M1_SCHEMA)
    if macro_result.get("as_of") != facts.get("as_of"):
        m1_problems.append("$.as_of: does not match frozen facts")
    m1_problems.extend(semantic_audit.check_macro_coverage(macro_result, macro_facts))
    if m1_problems:
        provenance.write(macro_result, run_dir / "macro_result.draft.json")
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_SCHEMA_M1", problems=m1_problems)}
    macro_result, m1_audit, m1_extra_dirs = _audit_and_retry_pack(
        pack_id="M1", run_dir=run_dir, stage_dir=m1_dir,
        facts_file="macro_facts.json", facts_payload=macro_facts,
        result=macro_result, result_schema=schemas.M1_SCHEMA,
        rules=m1_rules, backend=backend, program_problems=[])
    stage_dirs.extend(m1_extra_dirs)
    provenance.write(macro_result, run_dir / "macro_result.json")
    if m1_audit.get("verdict") != "PASS":
        _write_token_report(run_dir, stage_dirs)
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_AUDIT_M1",
                                problems=m1_audit.get("violations", []))}

    has_path = (macro_result.get("primary_path") or {}).get("status") == "SELECTED"
    has_pending = bool((yesterday or {}).get("nodes"))
    if not has_path and not has_pending:
        stage_b_result = {**macro_result, "nodes": [], "data_gaps": macro_result.get("data_gaps") or []}
        stage_b_result = provenance.stamp(stage_b_result, backend, m1_dir,
                                          ["macro_facts.json", "rules.md", "schema.json"])
        stage_c_result = _no_action_stage_c(
            facts.get("as_of"), "M1 未形成主路径且无前日待续节点，停止后续模型调用",
            (macro_result.get("primary_path") or {}).get("rule_ids") or [])
        provenance.write(stage_b_result, run_dir / "stage_b_result.json")
        provenance.write(stage_c_result, run_dir / "stage_c_result.json")
        from roubing_engine.reasoning.plan_compiler import compile_plan
        compiled = compile_plan(stage_b_result, stage_c_result, {
            "task_candidates": [], "no_action_rule_ids": []
        }, [], facts)
        provenance.write(compiled, run_dir / "compiled_plan.draft.json")
        if compiled.get("verdict") != "PASS":
            _write_token_report(run_dir, stage_dirs)
            return {"ok": False, "date": date, "backend": backend,
                    **_write_status(run_dir, "BLOCKED_PLAN_COMPILER",
                                    problems=compiled.get("violations", []))}
        provenance.write(compiled["executable_plan"], run_dir / "executable_plan.json")
        from roubing_engine.state.ledger import save_ledger
        save_ledger(date, stage_b_result, stage_c_result)
        _write_token_report(run_dir, stage_dirs)
        status = _write_status(run_dir, "APPROVED", audit_verdict="PASS",
                               stop_condition="NO_PATH_NO_PENDING_NODE")
        return {"ok": True, "date": date, "backend": backend, "status": status["status"]}

    # M2: generator applicability and legal nodes
    node_facts = projections.project_node_facts(facts, macro_result, yesterday)
    task_package.write_package(m2_dir, prompts.m2_node_instructions(), {
        "node_facts.json": node_facts,
        "macro_result.json": provenance.model_view(macro_result),
        "rules.md": m2_rules,
        "protocol.json": _protocol_payload("M2"),
        "schema.json": schemas.M2_SCHEMA,
    })
    try:
        m2_task = runner.AgentTask(
            task_dir=m2_dir,
            instructions=prompts.m2_node_instructions(),
            reasoning_effort=protocols.PACKS["M2"].core_reasoning_effort,
        )
        node_result = runner.run(m2_task, backend=backend)
    except Exception as e:  # noqa: BLE001
        _write_token_report(run_dir, stage_dirs)
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_MODEL_M2",
                                problems=[_model_error(e, m2_dir)])}
    stage_dirs.append(m2_dir)
    node_result = provenance.stamp(
        node_result, backend, m2_dir,
        ["node_facts.json", "macro_result.json", "rules.md",
         "protocol.json", "schema.json"],
    )
    m2_problems = runner.validate(node_result, schemas.M2_SCHEMA)
    if node_result.get("as_of") != facts.get("as_of"):
        m2_problems.append("$.as_of: does not match frozen facts")
    m2_problems.extend(semantic_audit.check_node_coverage(node_result))
    if m2_problems:
        provenance.write(node_result, run_dir / "node_result.draft.json")
        _write_token_report(run_dir, stage_dirs)
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_SCHEMA_M2", problems=m2_problems)}
    node_result, m2_audit, m2_extra_dirs = _audit_and_retry_pack(
        pack_id="M2", run_dir=run_dir, stage_dir=m2_dir,
        facts_file="node_facts.json", facts_payload=node_facts,
        result=node_result, result_schema=schemas.M2_SCHEMA,
        rules=m2_rules, backend=backend, program_problems=[])
    stage_dirs.extend(m2_extra_dirs)
    provenance.write(node_result, run_dir / "node_result.json")
    if m2_audit.get("verdict") != "PASS":
        _write_token_report(run_dir, stage_dirs)
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_AUDIT_M2",
                                problems=m2_audit.get("violations", []))}

    b_result = {
        "as_of": macro_result.get("as_of"),
        "environment": macro_result.get("environment") or {},
        "environment_hypotheses": macro_result.get("environment_hypotheses") or [],
        "direction_evaluations": macro_result.get("direction_evaluations") or [],
        "direction_comparisons": macro_result.get("direction_comparisons") or [],
        "primary_path": macro_result.get("primary_path") or {},
        "nodes": node_result.get("nodes") or [],
        "generator_applicability": node_result.get("generator_applicability") or [],
        "method_trace": ((macro_result.get("method_trace") or [])
                         + (node_result.get("method_trace") or [])),
        "data_gaps": list(dict.fromkeys(
            (macro_result.get("data_gaps") or []) + (node_result.get("data_gaps") or []))),
    }
    provenance.write(b_result, run_dir / "stage_b_result.raw.json")
    b_result, canonicalizations = _canonicalize_stage_b_nodes(b_result)
    (run_dir / "stage_b_canonicalizations.json").write_text(json.dumps({
        "changes": canonicalizations,
        "status": "CHANGED" if canonicalizations else "UNCHANGED",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    b_result = provenance.stamp(
        b_result, backend, m2_dir,
        ["node_facts.json", "macro_result.json", "rules.md", "protocol.json", "schema.json"],
    )
    b_problems = runner.validate(b_result, schemas.STAGE_B_SCHEMA)
    if b_result.get("as_of") != facts.get("as_of"):
        b_problems.append("$.as_of: does not match frozen facts")
    provenance.write(b_result, run_dir / "stage_b_result.draft.json")
    if b_problems:
        _write_token_report(run_dir, stage_dirs)
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_SCHEMA_STAGE_B", problems=b_problems)}

    from roubing_engine.evaluation.fidelity import check_stage_b
    b_fidelity = check_stage_b(b_result, facts)
    (run_dir / "stage_b_fidelity_result.json").write_text(
        json.dumps({"violations": b_fidelity,
                    "verdict": "PASS" if not b_fidelity else "NEEDS_REVISION"},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    if b_fidelity:
        _write_token_report(run_dir, stage_dirs)
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_FIDELITY_STAGE_B", problems=b_fidelity)}

    # Program expands candidate pools only after audited ACTION_READY nodes.
    from roubing_engine.reasoning.task_resolver import (
        build_task_pools, resolve,
    )
    task_bundle = resolve(b_result, facts)
    candidate_pools = build_task_pools(task_bundle, facts)
    (run_dir / "task_candidates.json").write_text(
        json.dumps(task_bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "candidate_pools.json").write_text(
        json.dumps(candidate_pools, ensure_ascii=False, indent=2), encoding="utf-8")

    selected_pools = [pool for pool in candidate_pools
                      if pool.get("status") == "ACTION_READY"]
    if not selected_pools:
        c_result = _no_action_stage_c(
            facts.get("as_of"), "M2 无审计通过的 ACTION_READY 候选池，节点只观察",
            task_bundle.get("no_action_rule_ids") or [])
    else:
        plan_facts = projections.project_plan_facts(facts, selected_pools)
        task_package.write_package(m3_dir, prompts.m3_plan_instructions(), {
            "plan_facts.json": plan_facts,
            "macro_result.json": provenance.model_view(macro_result),
            "node_result.json": provenance.model_view(node_result),
            "task_candidates.json": task_bundle,
            "selected_candidate_pools.json": selected_pools,
            "rules.md": m3_rules,
            "protocol.json": _protocol_payload("M3"),
            "schema.json": schemas.STAGE_C_SCHEMA,
        })
        try:
            c_task = runner.AgentTask(
                task_dir=m3_dir,
                instructions=prompts.m3_plan_instructions(),
                reasoning_effort=protocols.PACKS["M3"].core_reasoning_effort,
            )
            c_result = runner.run(c_task, backend=backend)
        except Exception as e:  # noqa: BLE001
            _write_token_report(run_dir, stage_dirs)
            return {"ok": False, "date": date, "backend": backend,
                    **_write_status(run_dir, "BLOCKED_MODEL_M3",
                                    problems=[_model_error(e, m3_dir)])}
        stage_dirs.append(m3_dir)
        c_result = provenance.stamp(
            c_result, backend, m3_dir,
            ["plan_facts.json", "macro_result.json", "node_result.json",
             "task_candidates.json", "selected_candidate_pools.json",
             "rules.md", "protocol.json", "schema.json"],
        )
        plan_program_problems = semantic_audit.check_plan_coverage(c_result)
        if not plan_program_problems:
            c_result, m3_audit, m3_extra_dirs = _audit_and_retry_pack(
                pack_id="M3", run_dir=run_dir, stage_dir=m3_dir,
                facts_file="plan_facts.json", facts_payload=plan_facts,
                result=c_result, result_schema=schemas.STAGE_C_SCHEMA,
                rules=m3_rules, backend=backend, program_problems=[])
            stage_dirs.extend(m3_extra_dirs)
            if m3_audit.get("verdict") != "PASS":
                _write_token_report(run_dir, stage_dirs)
                return {"ok": False, "date": date, "backend": backend,
                        **_write_status(run_dir, "BLOCKED_AUDIT_M3",
                                        problems=m3_audit.get("violations", []))}
    c_problems = runner.validate(c_result, schemas.STAGE_C_SCHEMA)
    if c_result.get("as_of") != facts.get("as_of"):
        c_problems.append("$.as_of: does not match frozen facts")
    c_problems.extend(semantic_audit.check_plan_coverage(c_result))
    provenance.write(c_result, run_dir / "stage_c_result.draft.json")
    if c_problems:
        _write_token_report(run_dir, stage_dirs)
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_SCHEMA_M3", problems=c_problems)}

    # Programmatic fidelity is a hard gate, independent of the model audit.
    from roubing_engine.evaluation.fidelity import check_task_plan
    fidelity = check_task_plan(
        b_result, c_result, task_bundle, candidate_pools, facts)
    (run_dir / "fidelity_result.json").write_text(
        json.dumps(fidelity, ensure_ascii=False, indent=2), encoding="utf-8")
    if fidelity.get("verdict") != "PASS":
        _write_token_report(run_dir, stage_dirs)
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
        _write_token_report(run_dir, stage_dirs)
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_PLAN_COMPILER",
                                problems=compiled.get("violations", []))}

    # 6) audit
    a_dir = run_dir / "audit"
    audit_rules = render_markdown(select(kinds=["discipline"], as_of=date))
    audit_evidence = bundle_for_audit(
        b_result, c_result, task_bundle, compiled, as_of=date)
    combined_rules = (
        "# M1 环境与方向规则\n\n" + m1_rules
        + "\n\n# M2 节点规则\n\n" + m2_rules
        + "\n\n# M3 角色竞争与计划规则\n\n" + m3_rules
        + "\n\n# 审计纪律规则\n\n" + audit_rules
    )
    task_package.write_package(a_dir, prompts.audit_instructions(), {
        "facts.json": facts,
        "stage_b.json": provenance.model_view(b_result),
        "macro_result.json": provenance.model_view(macro_result),
        "node_result.json": provenance.model_view(node_result),
        "stage_c.json": provenance.model_view(c_result),
        "task_candidates.json": task_bundle,
        "candidate_pools.json": candidate_pools,
        "compiled_plan.draft.json": compiled,
        "rules.md": combined_rules,
        "audit_evidence_manifest.json": audit_evidence,
        "audit_evidence_coverage.md": render_bundle(audit_evidence),
        "schema.json": schemas.AUDIT_SCHEMA,
    })
    a_task = runner.AgentTask(task_dir=a_dir, instructions=prompts.audit_instructions(),
                              reasoning_effort="medium")
    try:
        a_result = runner.run(a_task, backend=backend)
    except Exception as e:  # noqa: BLE001
        a_result = {"verdict": "AUDIT_ERROR", "violations": [str(e)], "counter_arguments": []}
    a_result = provenance.stamp(
        a_result, backend, a_dir,
        ["facts.json", "stage_b.json", "macro_result.json", "node_result.json", "stage_c.json",
         "task_candidates.json", "candidate_pools.json", "compiled_plan.draft.json",
         "rules.md", "audit_evidence_manifest.json", "audit_evidence_coverage.md",
         "schema.json"])
    stage_dirs.append(a_dir)
    a_problems = runner.validate(a_result, schemas.AUDIT_SCHEMA)
    if a_result.get("verdict") == "PASS" and a_result.get("violations"):
        a_problems.append("$.violations: PASS audit must have an empty violations list")
    provenance.write(a_result, run_dir / "audit_result.json")
    if a_problems:
        _write_token_report(run_dir, stage_dirs)
        return {"ok": False, "date": date, "backend": backend,
                **_write_status(run_dir, "BLOCKED_SCHEMA_AUDIT", problems=a_problems)}
    if a_result.get("verdict") != "PASS":
        _write_token_report(run_dir, stage_dirs)
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
    _write_token_report(run_dir, stage_dirs)

    # 8) battlecard
    card = render_card(date, b_result, c_result)
    card_path = run_dir / f"battlecard_{backend}.md"
    card_path.write_text(card, encoding="utf-8")

    status = _write_status(run_dir, "APPROVED", audit_verdict="PASS")
    return {"ok": True, "date": date, "backend": backend, "status": status["status"],
            "schema_problems": {"m1": [], "m2": [], "stage_b": b_problems,
                                "m3": c_problems},
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
