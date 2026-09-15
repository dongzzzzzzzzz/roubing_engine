"""Program-side coverage checks for V2 method traces."""
from __future__ import annotations

from roubing_engine.reasoning import protocols


def _trace_index(result: dict) -> dict[str, dict]:
    return {
        item.get("step_id"): item
        for item in result.get("method_trace") or []
        if isinstance(item, dict) and item.get("step_id")
    }


def check_macro_coverage(result: dict, macro_facts: dict) -> list[str]:
    problems: list[str] = []
    trace = _trace_index(result)
    for step_id in protocols.expected_stage1_step_ids():
        if step_id not in trace:
            problems.append(f"method_trace missing {step_id}")
    expected_themes = {
        row.get("theme") for row in macro_facts.get("direction_state_facts") or []
        if row.get("theme")
    }
    got_themes = {
        row.get("theme") for row in result.get("direction_evaluations") or []
        if row.get("theme")
    }
    missing = sorted(expected_themes - got_themes)
    if missing:
        problems.append(f"direction lifecycle missing themes: {missing}")
    return problems


def check_node_coverage(result: dict) -> list[str]:
    problems: list[str] = []
    rows = result.get("generator_applicability") or []
    by_id = {row.get("generator"): row for row in rows if isinstance(row, dict)}
    for generator in protocols.expected_generator_ids():
        if generator not in by_id:
            problems.append(f"generator_applicability missing {generator}")
            continue
        status = by_id[generator].get("status")
        if status not in protocols.TRACE_STATUSES:
            problems.append(f"{generator}.status invalid: {status!r}")
    raw_as_of = str(result.get("as_of", ""))
    as_of_date = raw_as_of[:10]
    if len(raw_as_of) >= 8 and raw_as_of[:8].isdigit():
        as_of_date = f"{raw_as_of[:4]}-{raw_as_of[4:6]}-{raw_as_of[6:8]}"
    for index, node in enumerate(result.get("nodes") or []):
        answers = node.get("node_questions") or {}
        missing = [key for key in protocols.NODE_QUESTION_FIELDS if key not in answers]
        if missing:
            problems.append(f"nodes[{index}] missing node_questions fields: {missing}")
        if node.get("generator") == "G8" and node.get("anchor_date") == as_of_date:
            if node.get("action_status") == "ACTION_READY":
                problems.append("G8 anchor-day node cannot be ACTION_READY; it must open observation/group state only")
    return problems


def check_plan_coverage(result: dict) -> list[str]:
    problems: list[str] = []
    final = result.get("final_action_plan") or {}
    if final.get("status") == "CONDITIONAL_PAIR" and not final.get("backup_ref"):
        problems.append("CONDITIONAL_PAIR requires an independent backup_ref")
    if final.get("backup_ref") and "独立" not in (final.get("switch_rule") or ""):
        problems.append("backup path must require independent positive conditions")
    for plan in result.get("path_plans") or []:
        action = plan.get("action_plan") or {}
        candidates = [
            row for row in plan.get("candidates") or []
            if row.get("task_relation") == "ACTION_COMPETITOR"
            and row.get("output_tier") != "取消或不行动"
        ]
        if len(candidates) >= 3 and action.get("status") != "NO_ACTION":
            problems.append(
                f"{plan.get('path_kind')}/{(plan.get('execution_task') or {}).get('task_id')}: "
                "three or more unresolved action candidates must stay observation-only")
    return problems
