"""Stage D orchestrator: validate a T-day plan against T+1 reality via sub-agent.

  python -m roubing_engine.reasoning.validate_pipeline --plan-date 20260908 --tplus1 2026-09-09
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from roubing_engine.config import PROJECT_ROOT
from roubing_engine.reasoning import prompts, protocols, provenance, runner, schemas, task_package
from roubing_engine.reasoning.validation_factpack import (
    build as build_vfacts, validate_stage_d_result,
)
from roubing_engine.rules.retrieve import render_markdown, select

RUNS = PROJECT_ROOT / "runs"


def _write_token_report(run_dir: Path, stage_dirs: list[Path]) -> None:
    stages = {}
    for stage_dir in stage_dirs:
        path = stage_dir / "token_usage.json"
        stages[stage_dir.name] = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists() else {"status": "UNAVAILABLE"})
    (run_dir / "validation_token_report.json").write_text(
        json.dumps({"stages": stages}, ensure_ascii=False, indent=2), encoding="utf-8")


def _m4_to_stage_d(result: dict, vfacts: dict) -> dict:
    """Render M4 into the legacy Stage-D shape for existing condition tools."""
    by_code = {row.get("thscode"): row for row in result.get("path_results") or []}
    leaf_results = []
    state_map = {
        "AUCTION_CONFIRMS_PATH": "MEETS_AUCTION_TASK",
        "AUCTION_NEEDS_OPEN_VALIDATION": "NEEDS_OPEN_VALIDATION",
        "AUCTION_REJECTS_PATH": "DIRECT_FAIL",
        "DATA_INSUFFICIENT": "DATA_INSUFFICIENT",
    }
    for fact in vfacts.get("action_leaf_facts") or []:
        row = by_code.get(fact.get("thscode")) or {}
        leaf_results.append({
            "thscode": fact.get("thscode"),
            "leaf_id": fact.get("leaf_id"),
            "tier": fact.get("tier"),
            "path_kind": fact.get("path_kind"),
            "task_id": fact.get("task_id"),
            "node_id": fact.get("node_id"),
            "anchor_date": fact.get("anchor_date"),
            "stock_start_date": fact.get("stock_start_date"),
            "current_function": fact.get("current_function"),
            "entry_event": fact.get("entry_event") or [],
            "exit_conditions": fact.get("exit_conditions") or [],
            "leaf_state": state_map.get(row.get("auction_status"), "DATA_INSUFFICIENT"),
            "observed": row.get("observed") or ["M4竞价结果已结构化输出。"],
            "vs_plan": "M4固定顺序：自身昨日状态->同组对手->板块容量->交易空间。",
            "reason": row.get("reject_reasons") or row.get("observed") or [],
        })
    execution = (vfacts.get("execution_context") or {}).get("execution_task") or {}
    executions = (vfacts.get("execution_context") or {}).get("execution_tasks") or [execution]
    return {
        "tplus1": result.get("tplus1"),
        "snapshot": "AUCTION_0925",
        "as_of": result.get("as_of"),
        "market_check": {"index_held": None, "note": "M4只做竞价路径确认，真实卖压留到M5。"},
        "reasoning_trace": {
            "step_order": ["MARKET_AND_PATH", "EXECUTION_NODE", "ACTION_LEAVES"],
            "market_and_path": {
                "status": "DATA_INSUFFICIENT",
                "observed": ["竞价阶段不确认指数/板块真实卖压，数据不足，无法判断。"],
            },
            "execution_node": {
                "status": "SUPPORTED" if execution.get("task_id") else "DATA_INSUFFICIENT",
                "task_id": execution.get("task_id"),
                "task_type": execution.get("task_type"),
                "theme": execution.get("theme"),
                "anchor_date": execution.get("anchor_date"),
                "observed": ["M4已按冻结执行节点验证竞价任务。"],
            },
            "execution_nodes": [{
                "path_kind": item.get("path_kind"),
                "status": "SUPPORTED" if item.get("task_id") else "DATA_INSUFFICIENT",
                "task_id": item.get("task_id"),
                "task_type": item.get("task_type"),
                "theme": item.get("theme"),
                "node_id": item.get("node_id"),
                "anchor_date": item.get("anchor_date"),
                "observed": ["M4已按冻结路径任务验证竞价。"],
            } for item in executions],
        },
        "auction_pair_comparison": vfacts.get("relative_auction_contract") or {
            "status": "NOT_APPLICABLE", "stronger_code": None, "weaker_code": None,
            "comparison_text": "当前快照不需要双叶子竞价比较",
        },
        "context_check": {
            "validation_objects": [
                row.get("thscode") for row in vfacts.get("validation_context_facts") or []
                if row.get("thscode")
            ],
            "status": "DATA_INSUFFICIENT",
            "observed": ["M4只记录竞价验证对象，方向真实响应留到开盘验证，数据不足，无法判断。"],
        },
        "path_context_checks": [{
            "path_kind": item.get("path_kind"),
            "task_id": item.get("task_id"),
            "node_id": item.get("node_id"),
            "validation_objects": item.get("validation_objects") or [],
            "status": "DATA_INSUFFICIENT",
            "observed": ["M4只记录竞价上下文，路径响应留到M5，数据不足，无法判断。"],
        } for item in vfacts.get("path_validation_contexts") or []],
        "leaf_results": leaf_results,
        "condition_tree_hit": result.get("condition_tree_hit") or {},
        "current_action_candidate": result.get("current_action_candidate"),
        "next_stage": result.get("next_stage"),
        "decision": result.get("decision"),
        "unknowns": result.get("unknowns") or [],
    }


def _m5_to_stage_d(result: dict, vfacts: dict) -> dict:
    """Render M5 into the legacy Stage-D shape for existing consumers."""
    leaf_results = []
    conclusion = (result.get("open_validation") or {}).get("conclusion")
    state = {
        "OPEN_CONFIRMS": "MEETS_OPEN_TASK",
        "NEEDS_FURTHER_VALIDATION": "MEETS_OPEN_TASK",
        "OPEN_REJECTS": "OPEN_TASK_FAILED",
        "DATA_INSUFFICIENT": "DATA_INSUFFICIENT",
    }.get(conclusion, "DATA_INSUFFICIENT")
    for fact in vfacts.get("action_leaf_facts") or []:
        leaf_results.append({
            "thscode": fact.get("thscode"),
            "leaf_id": fact.get("leaf_id"),
            "tier": fact.get("tier"),
            "path_kind": fact.get("path_kind"),
            "task_id": fact.get("task_id"),
            "node_id": fact.get("node_id"),
            "anchor_date": fact.get("anchor_date"),
            "stock_start_date": fact.get("stock_start_date"),
            "current_function": fact.get("current_function"),
            "entry_event": fact.get("entry_event") or [],
            "exit_conditions": fact.get("exit_conditions") or [],
            "leaf_state": state,
            "observed": (
                (result.get("open_validation") or {}).get("sell_pressure_path") or []
            ) + ((result.get("open_validation") or {}).get("board_response") or []),
            "vs_plan": "M5先验证开盘卖压/承接/事件顺序/板块响应，再选择动作方式。",
            "reason": (result.get("action_trigger") or {}).get("reason") or [],
        })
    execution = (vfacts.get("execution_context") or {}).get("execution_task") or {}
    executions = (vfacts.get("execution_context") or {}).get("execution_tasks") or [execution]
    decision_map = {
        "BUY": "BUY",
        "NO_ACTION": "NO_ACTION",
        "WAIT_CLOSE_CONFIRM": "NO_ACTION",
        "DATA_INSUFFICIENT": "DATA_INSUFFICIENT",
    }
    return {
        "tplus1": result.get("tplus1"),
        "snapshot": "OPEN_0935",
        "as_of": result.get("as_of"),
        "market_check": {"index_held": None, "note": "M5以结构化开盘验证为准。"},
        "reasoning_trace": {
            "step_order": ["MARKET_AND_PATH", "EXECUTION_NODE", "ACTION_LEAVES"],
            "market_and_path": {
                "status": "DATA_INSUFFICIENT",
                "observed": ["M5未独立确认指数环境时，数据不足，无法判断。"],
            },
            "execution_node": {
                "status": "SUPPORTED" if execution.get("task_id") else "DATA_INSUFFICIENT",
                "task_id": execution.get("task_id"),
                "task_type": execution.get("task_type"),
                "theme": execution.get("theme"),
                "anchor_date": execution.get("anchor_date"),
                "observed": ["M5已按冻结执行节点验证开盘任务。"],
            },
            "execution_nodes": [{
                "path_kind": item.get("path_kind"),
                "status": "SUPPORTED" if item.get("task_id") else "DATA_INSUFFICIENT",
                "task_id": item.get("task_id"),
                "task_type": item.get("task_type"),
                "theme": item.get("theme"),
                "node_id": item.get("node_id"),
                "anchor_date": item.get("anchor_date"),
                "observed": ["M5已按冻结路径任务验证开盘。"],
            } for item in executions],
        },
        "auction_pair_comparison": vfacts.get("relative_auction_contract") or {
            "status": "NOT_APPLICABLE", "stronger_code": None, "weaker_code": None,
            "comparison_text": "当前快照不需要双叶子竞价比较",
        },
        "context_check": {
            "validation_objects": [
                row.get("thscode") for row in vfacts.get("validation_context_facts") or []
                if row.get("thscode")
            ],
            "status": "UNRESOLVED",
            "observed": (result.get("open_validation") or {}).get("board_response") or [],
        },
        "path_context_checks": [{
            "path_kind": item.get("path_kind"),
            "task_id": item.get("task_id"),
            "node_id": item.get("node_id"),
            "validation_objects": item.get("validation_objects") or [],
            "status": "UNRESOLVED",
            "observed": (result.get("open_validation") or {}).get("board_response") or [],
        } for item in vfacts.get("path_validation_contexts") or []],
        "leaf_results": leaf_results,
        "condition_tree_hit": {
            "branch": "OPEN_CONFIRM" if result.get("decision") in {"BUY", "WAIT_CLOSE_CONFIRM"}
            else "OPEN_REJECT" if result.get("decision") == "NO_ACTION" else "DATA_BLOCKED",
            "primary_state": conclusion,
            "backup_state": None,
            "reasoning": (result.get("action_trigger") or {}).get("reason") or ["M5结构化验证结果。"],
        },
        "current_action_candidate": result.get("current_action_candidate"),
        "next_stage": "COMPLETE",
        "decision": decision_map.get(result.get("decision"), "DATA_INSUFFICIENT"),
        "unknowns": result.get("unknowns") or [],
    }


def _tail_leaf(plan: dict, m5_result: dict) -> dict | None:
    code = (
        m5_result.get("current_action_candidate")
        or (m5_result.get("action_trigger") or {}).get("thscode")
    )
    if not code:
        return None
    for leaf in (
        (plan.get("action_plan") or {}).get("primary"),
        (plan.get("action_plan") or {}).get("backup"),
    ):
        if leaf and leaf.get("thscode") == code:
            return leaf
    return None


def _tail_validation_facts(plan: dict, leaf: dict, tplus1: str) -> dict:
    return {
        "plan_date": plan.get("plan_date"),
        "tplus1": tplus1,
        "snapshot": "VTAIL",
        "as_of": f"{tplus1} 14:56:59 Asia/Shanghai",
        "current_action_leaf": leaf,
        "tail_contract": {
            "tail_event_trigger": leaf.get("tail_event_trigger"),
            "required_board_reflux": leaf.get("required_board_reflux"),
            "required_breakout_state": leaf.get("required_breakout_state"),
            "regulatory_condition": leaf.get("regulatory_condition"),
            "cancel_conditions": leaf.get("cancel_conditions") or [],
            "latest_valid_time": leaf.get("latest_valid_time"),
        },
        "data_boundary": {
            "status": "DATA_INSUFFICIENT",
            "reason": "tail intraday event feed is not materialized in this factpack yet",
        },
    }


def run_tail_validation(plan_date: str, tplus1: str, backend: str = "codex",
                        dry_run: bool = False) -> dict:
    run_dir = RUNS / plan_date
    status_path = run_dir / "run_status.json"
    if not status_path.exists() or json.loads(status_path.read_text()).get("status") != "APPROVED":
        raise RuntimeError("VTAIL requires an APPROVED EOD plan")
    plan_path = run_dir / "executable_plan.json"
    if not plan_path.exists():
        raise RuntimeError(f"missing executable plan: {plan_path}")
    m5_path = run_dir / f"m5_open_action_result_{tplus1}.json"
    if not m5_path.exists():
        raise RuntimeError("VTAIL requires a canonical M5 OPEN_0935 result")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    m5_result = json.loads(m5_path.read_text(encoding="utf-8"))
    method = (m5_result.get("action_trigger") or {}).get("method")
    if method != "TAIL_CONFIRMATION":
        raise RuntimeError("VTAIL may only follow M5 action_trigger.method=TAIL_CONFIRMATION")
    leaf = _tail_leaf(plan, m5_result)
    if not leaf or leaf.get("action_type") != "TAIL_CONFIRMATION":
        raise RuntimeError("VTAIL current leaf must be pre-frozen as action_type=TAIL_CONFIRMATION")

    facts = _tail_validation_facts(plan, leaf, tplus1)
    facts_path = run_dir / f"tail_validation_facts_{tplus1}.json"
    provenance.write(facts, facts_path)
    vtail_dir = run_dir / f"vtail_{tplus1}"
    rules = render_markdown(select(kinds=["primitive", "exit", "discipline"], as_of=plan_date))
    task_package.write_package(vtail_dir, prompts.vtail_instructions(), {
        "executable_plan.json": plan,
        "tail_validation_facts.json": facts,
        "m5_open_action_result.json": m5_result,
        "rules.md": rules,
        "schema.json": schemas.VTAIL_SCHEMA,
    })
    if dry_run:
        return {"ok": True, "dry_run": True, "package": str(vtail_dir)}

    task = runner.AgentTask(
        task_dir=vtail_dir,
        instructions=prompts.vtail_instructions(),
        reasoning_effort=protocols.PACKS["M5"].core_reasoning_effort,
    )
    result = runner.run(task, backend=backend)
    result = provenance.stamp(
        result, backend, vtail_dir,
        ["executable_plan.json", "tail_validation_facts.json",
         "m5_open_action_result.json", "rules.md", "schema.json"],
    )
    problems = runner.validate(result, schemas.VTAIL_SCHEMA)
    if result.get("tplus1") != tplus1:
        problems.append("$.tplus1: does not match requested date")
    if result.get("as_of") != facts.get("as_of"):
        problems.append("$.as_of: does not match tail validation facts")
    validation = result.get("tail_event_validation") or {}
    for key, expected in facts["tail_contract"].items():
        if validation.get(key) != expected:
            problems.append(f"$.tail_event_validation.{key}: must copy frozen tail contract")
    if validation.get("conclusion") == "TAIL_CONFIRMS" and result.get("decision") != "BUY":
        problems.append("TAIL_CONFIRMS must produce BUY")
    if validation.get("conclusion") == "TAIL_REJECTS" and result.get("decision") != "NO_ACTION":
        problems.append("TAIL_REJECTS must produce NO_ACTION")
    draft_path = run_dir / f"vtail_result_{tplus1}.draft.json"
    provenance.write(result, draft_path)
    if problems:
        raise RuntimeError("VTAIL schema invalid: " + "; ".join(problems))
    result_path = run_dir / f"vtail_result_{tplus1}.json"
    provenance.write(result, result_path)
    return {"ok": True, "plan_date": plan_date, "tplus1": tplus1,
            "backend": backend, "result_file": str(result_path)}


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
    prior_m4_result = None
    if snapshot == "OPEN_0935":
        prior_m4_path = run_dir / f"m4_auction_result_{tplus1}.json"
        prior_path = run_dir / f"stage_d_result_{tplus1}_auction_0925.json"
        if prior_m4_path.exists():
            prior_m4_result = json.loads(prior_m4_path.read_text(encoding="utf-8"))
            prior_result = prior_m4_result
        elif prior_path.exists():
            prior_result = json.loads(prior_path.read_text(encoding="utf-8"))
        else:
            raise RuntimeError("OPEN_0935 requires the canonical AUCTION_0925 condition result")
    vfacts = build_vfacts(
        plan, tplus1, snapshot=snapshot, prior_result=prior_result)
    facts_path = run_dir / f"validation_facts_{tplus1}_{suffix}.json"
    facts_path.write_text(
        json.dumps(vfacts, ensure_ascii=False, indent=2), encoding="utf-8")

    pack_id = "M4" if snapshot == "AUCTION_0925" else "M5"
    d_dir = run_dir / f"{pack_id.lower()}_{tplus1}_{suffix}"
    # Freeze methodological knowledge at T-day close.  A T+1 intraday replay
    # must not consume posts published later on T+1 or after the validation day.
    d_rules = render_markdown(select(
        kinds=["primitive", "exit", "discipline"], as_of=plan_date))
    stage_prompt = (prompts.m4_auction_instructions()
                    if pack_id == "M4" else prompts.m5_open_action_instructions())
    stage_schema = (schemas.M4_AUCTION_SCHEMA if pack_id == "M4"
                    else schemas.M5_OPEN_ACTION_SCHEMA)
    package = {
        "executable_plan.json": plan,
        "validation_facts.json": vfacts,
        "rules.md": d_rules,
        "schema.json": stage_schema,
    }
    if pack_id == "M5":
        package["m4_auction_result.json"] = prior_m4_result or prior_result or {}
    task_package.write_package(d_dir, stage_prompt, package)

    if dry_run:
        return {"ok": True, "dry_run": True, "package": str(d_dir),
                "n_candidates": len(vfacts.get("action_leaf_facts", []))}

    prior_has_candidate = bool((prior_result or {}).get("current_action_candidate"))
    if snapshot == "OPEN_0935" and not prior_has_candidate:
        result = {
            "tplus1": tplus1,
            "snapshot": "OPEN_0935",
            "as_of": vfacts.get("as_of"),
            "current_action_candidate": None,
            "open_validation": {
                "sell_pressure_path": ["M4没有唯一动作对象，M5不得重新选股。"],
                "stop_weakening": [],
                "same_group_event_order": [],
                "board_response": [],
                "conclusion": "OPEN_REJECTS",
            },
            "action_trigger": {
                "method": "NONE", "method_trace": ["09:25无对象，停止。"],
                "thscode": None, "reason": ["M4未传入 current_action_candidate。"],
            },
            "decision": "NO_ACTION",
            "method_trace": [
                {"step_id": step, "status": "NOT_APPLICABLE",
                 "observed": ["M4无对象，M5机械停止。"], "fact_ids": [],
                 "judgment": "NO_CANDIDATE"}
                for step in ["M5-SELL-PRESSURE", "M5-STOP-WEAKENING",
                             "M5-EVENT-ORDER", "M5-BOARD-RESPONSE", "M5-ACTION"]
            ],
            "unknowns": [],
        }
    else:
        task = runner.AgentTask(
            task_dir=d_dir,
            instructions=stage_prompt,
            reasoning_effort=protocols.PACKS[pack_id].core_reasoning_effort,
        )
        result = runner.run(task, backend=backend)
    result = provenance.stamp(
        result, backend, d_dir,
        list(package.keys()),
    )
    problems = runner.validate(result, stage_schema)
    if result.get("tplus1") != tplus1:
        problems.append("$.tplus1: does not match validation facts")
    if result.get("snapshot") != snapshot:
        problems.append("$.snapshot: does not match validation facts")
    if result.get("as_of") != vfacts.get("as_of"):
        problems.append("$.as_of: does not match validation facts")
    if pack_id == "M4":
        plan_codes = {c.get("thscode") for c in vfacts.get("action_leaf_facts", [])}
        result_codes = {c.get("thscode") for c in result.get("path_results", [])}
        if result_codes != plan_codes:
            problems.append(
                f"$.path_results: codes differ from frozen snapshot plan; "
                f"expected={sorted(plan_codes)} got={sorted(result_codes)}")
        legacy_result = _m4_to_stage_d(result, vfacts)
    else:
        expected = (prior_result or {}).get("current_action_candidate")
        if result.get("current_action_candidate") != expected:
            problems.append("$.current_action_candidate: must equal M4 frozen candidate")
        legacy_result = _m5_to_stage_d(result, vfacts)

    from roubing_engine.reasoning.condition_tree import validate_result as validate_tree
    problems.extend(validate_tree(legacy_result, plan, vfacts, prior_result))
    official_name = "m4_auction_result" if pack_id == "M4" else "m5_open_action_result"
    official_draft_path = run_dir / f"{official_name}_{tplus1}.draft.json"
    provenance.write(result, official_draft_path)
    draft_path = run_dir / f"stage_d_result_{tplus1}_{suffix}.draft.json"
    provenance.write(legacy_result, draft_path)
    if problems:
        raise RuntimeError(f"{pack_id} schema invalid: {'; '.join(problems)}")

    # Independent second pass: it receives the frozen facts and the proposed
    # result, and cannot repair or reinterpret missing observations.
    audit_dir = run_dir / f"{pack_id.lower()}_audit_{tplus1}_{suffix}"
    task_package.write_package(audit_dir, prompts.stage_d_audit_instructions(), {
        "stage_d_result.json": provenance.model_view(legacy_result),
        "stage_result.json": provenance.model_view(result),
        "validation_facts.json": vfacts,
        "executable_plan.json": plan,
        "rules.md": d_rules,
        "schema.json": schemas.AUDIT_SCHEMA,
    })
    audit_task = runner.AgentTask(
        task_dir=audit_dir,
        instructions=prompts.stage_d_audit_instructions(),
        reasoning_effort=protocols.PACKS[pack_id].audit_reasoning_effort,
    )
    audit_result = runner.run(audit_task, backend=backend)
    audit_result = provenance.stamp(
        audit_result, backend, audit_dir,
        ["stage_d_result.json", "stage_result.json", "validation_facts.json", "executable_plan.json",
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
    official_path = run_dir / f"{official_name}_{tplus1}.json"
    provenance.write(result, official_path)
    result_path = run_dir / f"stage_d_result_{tplus1}_{suffix}.json"
    provenance.write(legacy_result, result_path)
    _write_token_report(run_dir, [d_dir, audit_dir])

    return {"ok": True, "plan_date": plan_date, "tplus1": tplus1, "backend": backend,
            "snapshot": snapshot, "schema_problems": problems,
            "pack": pack_id, "result_file": str(official_path),
            "compat_result_file": str(result_path)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--plan-date", required=True, help="T day YYYYMMDD (has stage_c_result)")
    p.add_argument("--tplus1", required=True, help="T+1 YYYY-MM-DD")
    p.add_argument("--backend", default="codex", choices=["codex", "cursor"])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--snapshot", default="OPEN_0935",
                   choices=["AUCTION_0925", "OPEN_0935", "VTAIL"])
    args = p.parse_args()
    if args.snapshot == "VTAIL":
        out = run_tail_validation(args.plan_date, args.tplus1, backend=args.backend,
                                  dry_run=args.dry_run)
    else:
        out = run_validation(args.plan_date, args.tplus1, backend=args.backend,
                             dry_run=args.dry_run, snapshot=args.snapshot)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
