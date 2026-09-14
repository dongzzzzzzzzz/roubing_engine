from __future__ import annotations

import json
import unittest
from pathlib import Path

from roubing_engine.reasoning.condition_tree import terminal_no_action_result, validate_result
from roubing_engine.reasoning import runner, schemas
from roubing_engine.reasoning.validation_factpack import build as build_validation_facts


def leaf(code: str, state: str, tier: str | None = None) -> dict:
    tier = tier or ("PRIMARY" if code == "A.SH" else "BACKUP")
    return {"thscode": code, "leaf_id": f"L-{code}", "tier": tier,
            "leaf_state": state}


class ConditionTreeTests(unittest.TestCase):
    def setUp(self):
        self.plan = {"action_plan": {
            "status": "CONDITIONAL_PAIR",
            "primary": {"thscode": "A.SH", "leaf_id": "L-A.SH", "tier": "PRIMARY"},
            "backup": {"thscode": "B.SH", "leaf_id": "L-B.SH", "tier": "BACKUP"},
        }}
        self.facts = {"snapshot": "AUCTION_0925", "validation_context_facts": []}

    def result(self, rows, current, branch, decision, next_stage):
        return {
            "leaf_results": rows,
            "context_check": {"validation_objects": [], "status": "NOT_REQUIRED",
                              "observed": []},
            "current_action_candidate": current,
            "condition_tree_hit": {"branch": branch},
            "decision": decision, "next_stage": next_stage,
        }

    def test_primary_downgrade_does_not_switch_to_backup(self):
        result = self.result(
            [leaf("A.SH", "DOWNGRADED"), leaf("B.SH", "MEETS_AUCTION_TASK")],
            None, "PRIMARY_DOWNGRADED_NO_SWITCH", "NO_ACTION", "STOP")
        self.assertEqual(validate_result(result, self.plan, self.facts), [])

    def test_primary_direct_fail_can_switch_to_independent_backup(self):
        result = self.result(
            [leaf("A.SH", "DIRECT_FAIL"), leaf("B.SH", "NEEDS_OPEN_VALIDATION")],
            "B.SH", "PRIMARY_DIRECT_FAIL_BACKUP_CONTINUES",
            "WAIT_OPEN_VALIDATION", "OPEN_0935")
        self.assertEqual(validate_result(result, self.plan, self.facts), [])

    def test_cross_path_backup_is_blocked_when_its_own_context_is_missing(self):
        plan = {"action_plan": {
            "status": "CONDITIONAL_PAIR",
            "primary": {"thscode": "A.SH", "leaf_id": "L-A.SH", "tier": "PRIMARY",
                        "task_id": "TASK-P", "path_kind": "PRIMARY"},
            "backup": {"thscode": "B.SH", "leaf_id": "L-B.SH", "tier": "BACKUP",
                       "task_id": "TASK-A", "path_kind": "ALTERNATIVE"},
        }}
        facts = {
            "snapshot": "AUCTION_0925", "market_check_data": {"available": True},
            "validation_context_facts": [{
                "thscode": "V.SH", "data_completeness": {"opening_match": "MISSING"},
            }],
            "path_validation_contexts": [
                {"path_kind": "PRIMARY", "task_id": "TASK-P", "node_id": "NODE-P",
                 "validation_objects": [], "facts": []},
                {"path_kind": "ALTERNATIVE", "task_id": "TASK-A", "node_id": "NODE-A",
                 "validation_objects": ["V.SH"], "facts": [{
                     "thscode": "V.SH", "data_completeness": {"opening_match": "MISSING"},
                 }]},
            ],
        }
        result = self.result(
            [leaf("A.SH", "DIRECT_FAIL"), leaf("B.SH", "MEETS_AUCTION_TASK")],
            None, "DATA_BLOCKED", "DATA_INSUFFICIENT", "STOP")
        result["context_check"] = {
            "validation_objects": ["V.SH"], "status": "DATA_INSUFFICIENT",
            "observed": ["数据不足，无法判断"],
        }
        result["path_context_checks"] = [
            {"path_kind": "PRIMARY", "task_id": "TASK-P", "node_id": "NODE-P",
             "validation_objects": [], "status": "NOT_REQUIRED", "observed": []},
            {"path_kind": "ALTERNATIVE", "task_id": "TASK-A", "node_id": "NODE-A",
             "validation_objects": ["V.SH"], "status": "DATA_INSUFFICIENT",
             "observed": ["数据不足，无法判断"]},
        ]
        self.assertEqual(validate_result(result, plan, facts), [])

    def test_unplanned_strong_stock_is_rejected(self):
        result = self.result(
            [leaf("A.SH", "DIRECT_FAIL"), leaf("B.SH", "DIRECT_FAIL"),
             leaf("C.SH", "MEETS_AUCTION_TASK")],
            "C.SH", "BOTH_FAIL", "WAIT_OPEN_VALIDATION", "OPEN_0935")
        problems = validate_result(result, self.plan, self.facts)
        self.assertTrue(any("精确等于" in item for item in problems))

    def test_leaf_identity_must_match_compiled_plan(self):
        result = self.result(
            [leaf("A.SH", "MEETS_AUCTION_TASK"), leaf("B.SH", "DIRECT_FAIL")],
            "A.SH", "PRIMARY_CONTINUES", "WAIT_OPEN_VALIDATION", "OPEN_0935")
        result["leaf_results"][0]["leaf_id"] = "WRONG"
        problems = validate_result(result, self.plan, self.facts)
        self.assertTrue(any("leaf_id" in item for item in problems))

    def test_validation_context_rejection_blocks_candidate(self):
        facts = {"snapshot": "AUCTION_0925", "validation_context_facts": [{
            "thscode": "V.SH", "data_completeness": {"opening_match": "AVAILABLE"},
        }], "market_check_data": {"available": True}}
        result = self.result(
            [leaf("A.SH", "MEETS_AUCTION_TASK"), leaf("B.SH", "DIRECT_FAIL")],
            None, "CONTEXT_REJECTS", "NO_ACTION", "STOP")
        result["context_check"] = {
            "validation_objects": ["V.SH"], "status": "REJECTS",
            "observed": ["验证对象否定方向任务"],
        }
        self.assertEqual(validate_result(result, self.plan, facts), [])

    def test_0935_accepts_only_0925_unique_candidate(self):
        facts = {"snapshot": "OPEN_0935", "validation_context_facts": []}
        prior = {"current_action_candidate": "B.SH"}
        result = self.result([leaf("B.SH", "MEETS_OPEN_TASK")], "B.SH",
                             "OPEN_CONFIRM", "BUY", "COMPLETE")
        self.assertEqual(validate_result(result, self.plan, facts, prior), [])

    def test_single_validation_stock_cannot_confirm_direction_without_market_data(self):
        facts = {"snapshot": "AUCTION_0925", "market_check_data": {"available": False},
                 "validation_context_facts": [{
                     "thscode": "V.SH", "data_completeness": {"opening_match": "AVAILABLE"},
                 }]}
        result = self.result(
            [leaf("A.SH", "DOWNGRADED"), leaf("B.SH", "DATA_INSUFFICIENT")],
            None, "PRIMARY_DOWNGRADED_NO_SWITCH", "NO_ACTION", "STOP")
        result["context_check"] = {
            "validation_objects": ["V.SH"], "status": "CONFIRMS",
            "observed": ["单票竞价为正"],
        }
        problems = validate_result(result, self.plan, facts)
        self.assertTrue(any("单只验证对象" in item for item in problems))

    def test_0935_cannot_reopen_selection_after_0925_none(self):
        facts = {"snapshot": "OPEN_0935", "validation_context_facts": []}
        prior = {"current_action_candidate": None}
        result = self.result([], None, "NO_CANDIDATE", "NO_ACTION", "COMPLETE")
        self.assertEqual(validate_result(result, self.plan, facts, prior), [])

    def test_0935_none_is_compiled_without_model_selection(self):
        prior = {"current_action_candidate": None, "decision": "NO_ACTION",
                 "next_stage": "STOP"}
        facts = {
            "tplus1": "2026-01-06", "snapshot": "OPEN_0935",
            "as_of": "2026-01-06T09:35:59+08:00",
            "prior_auction_result": prior,
            "action_leaf_facts": [],
            "validation_context_facts": [{
                "thscode": "V.SH",
                "data_completeness": {"open_5min": "MISSING"},
            }],
            "market_check_data": {"available": False},
        }
        result = terminal_no_action_result(facts)
        self.assertEqual(result["decision"], "NO_ACTION")
        self.assertEqual(result["next_stage"], "COMPLETE")
        self.assertEqual(result["leaf_results"], [])
        self.assertEqual(result["context_check"]["status"], "DATA_INSUFFICIENT")
        self.assertEqual(runner.validate(result, schemas.STAGE_D_SCHEMA), [])
        self.assertEqual(validate_result(result, self.plan, facts, prior), [])

    def test_terminal_no_action_rejects_existing_candidate(self):
        facts = {"snapshot": "OPEN_0935", "prior_auction_result": {
            "current_action_candidate": "A.SH"}}
        with self.assertRaisesRegex(ValueError, "open validation is required"):
            terminal_no_action_result(facts)

    def test_stage_d_schema_requires_all_execution_and_path_traces(self):
        facts = {
            "tplus1": "2026-01-06", "snapshot": "OPEN_0935",
            "as_of": "2026-01-06T09:35:59+08:00",
            "prior_auction_result": {"current_action_candidate": None},
            "action_leaf_facts": [], "validation_context_facts": [],
            "path_validation_contexts": [], "market_check_data": {"available": False},
        }
        result = terminal_no_action_result(facts)
        missing_nodes = json.loads(json.dumps(result))
        del missing_nodes["reasoning_trace"]["execution_nodes"]
        self.assertTrue(any("execution_nodes" in item for item in
                            runner.validate(missing_nodes, schemas.STAGE_D_SCHEMA)))
        missing_paths = json.loads(json.dumps(result))
        del missing_paths["path_context_checks"]
        self.assertTrue(any("path_context_checks" in item for item in
                            runner.validate(missing_paths, schemas.STAGE_D_SCHEMA)))

    def test_same_task_pair_builds_one_path_validation_context(self):
        common = {
            "task_id": "TASK-X", "path_kind": "PRIMARY", "node_id": "NODE-X",
            "anchor_date": "2026-01-05", "path_validation_objects": ["V.SH"],
            "current_function": "同任务竞争", "entry_event": ["盘后冻结"],
            "exit_conditions": ["任务失败"], "task_to_complete": "完成任务",
            "auction_conditions": ["相对任务成立"], "open_conditions": ["承接成立"],
            "downgrade_conditions": ["待确认"], "direct_fail_conditions": ["直接失败"],
        }
        plan = {
            "action_plan": {
                "status": "CONDITIONAL_PAIR",
                "primary": {**common, "thscode": "A.SH", "leaf_id": "L-A", "tier": "PRIMARY"},
                "backup": {**common, "thscode": "B.SH", "leaf_id": "L-B", "tier": "BACKUP"},
                "validation_objects": ["V.SH"],
            },
            "execution_task": {"task_id": "TASK-X", "task_type": "SAME_LEVEL_PROMOTION",
                               "theme": "示例", "node_id": "NODE-X",
                               "anchor_date": "2026-01-05", "path_kind": "PRIMARY"},
            "execution_tasks": [{"task_id": "TASK-X", "task_type": "SAME_LEVEL_PROMOTION",
                                 "theme": "示例", "node_id": "NODE-X",
                                 "anchor_date": "2026-01-05", "path_kind": "PRIMARY"}],
        }
        facts = build_validation_facts(plan, "2099-01-06", snapshot="AUCTION_0925")
        self.assertEqual(len(facts["path_validation_contexts"]), 1)
        self.assertEqual(facts["path_validation_contexts"][0]["task_id"], "TASK-X")
        self.assertEqual(facts["path_validation_contexts"][0]["validation_objects"], ["V.SH"])

    def test_empty_path_validation_objects_are_not_required_at_both_snapshots(self):
        plan = {"action_plan": {
            "status": "SINGLE",
            "primary": {"thscode": "A.SH", "leaf_id": "L-A.SH", "tier": "PRIMARY",
                        "task_id": "TASK-P", "path_kind": "PRIMARY"},
            "backup": None,
        }}
        for snapshot, state, current, branch, decision, next_stage, prior in (
            ("AUCTION_0925", "MEETS_AUCTION_TASK", "A.SH", "PRIMARY_CONTINUES",
             "WAIT_OPEN_VALIDATION", "OPEN_0935", None),
            ("OPEN_0935", "MEETS_OPEN_TASK", "A.SH", "OPEN_CONFIRM",
             "BUY", "COMPLETE", {"current_action_candidate": "A.SH"}),
        ):
            with self.subTest(snapshot=snapshot):
                facts = {
                    "snapshot": snapshot, "market_check_data": {"available": True},
                    "validation_context_facts": [],
                    "path_validation_contexts": [{
                        "path_kind": "PRIMARY", "task_id": "TASK-P", "node_id": "NODE-P",
                        "validation_objects": [], "facts": [],
                    }],
                }
                result = self.result(
                    [leaf("A.SH", state)], current, branch, decision, next_stage)
                result["path_context_checks"] = [{
                    "path_kind": "PRIMARY", "task_id": "TASK-P", "node_id": "NODE-P",
                    "validation_objects": [], "status": "NOT_REQUIRED", "observed": [],
                }]
                self.assertEqual(validate_result(result, plan, facts, prior), [])
                result["path_context_checks"][0]["status"] = "CONFIRMS"
                self.assertTrue(any("无验证对象时必须 NOT_REQUIRED" in item for item in
                                    validate_result(result, plan, facts, prior)))

    def test_missing_market_blocks_each_path_at_both_snapshots(self):
        plan = {"action_plan": {
            "status": "SINGLE",
            "primary": {"thscode": "A.SH", "leaf_id": "L-A.SH", "tier": "PRIMARY",
                        "task_id": "TASK-P", "path_kind": "PRIMARY"},
            "backup": None,
        }}
        for snapshot, state, current, branch, decision, next_stage, prior, field in (
            ("AUCTION_0925", "MEETS_AUCTION_TASK", "A.SH", "PRIMARY_CONTINUES",
             "WAIT_OPEN_VALIDATION", "OPEN_0935", None, "opening_match"),
            ("OPEN_0935", "MEETS_OPEN_TASK", "A.SH", "OPEN_CONFIRM",
             "BUY", "COMPLETE", {"current_action_candidate": "A.SH"}, "open_5min"),
        ):
            with self.subTest(snapshot=snapshot):
                row = {"thscode": "V.SH", "data_completeness": {field: "AVAILABLE"}}
                facts = {
                    "snapshot": snapshot, "market_check_data": {"available": False},
                    "validation_context_facts": [row],
                    "path_validation_contexts": [{
                        "path_kind": "PRIMARY", "task_id": "TASK-P", "node_id": "NODE-P",
                        "validation_objects": ["V.SH"], "facts": [row],
                    }],
                }
                result = self.result(
                    [leaf("A.SH", state)], current, branch, decision, next_stage)
                result["context_check"] = {
                    "validation_objects": ["V.SH"], "status": "DATA_INSUFFICIENT",
                    "observed": ["数据不足，无法判断"],
                }
                result["path_context_checks"] = [{
                    "path_kind": "PRIMARY", "task_id": "TASK-P", "node_id": "NODE-P",
                    "validation_objects": ["V.SH"], "status": "CONFIRMS", "observed": [],
                }]
                self.assertTrue(any("缺指数/板块分时时必须 DATA_INSUFFICIENT" in item
                                    for item in validate_result(result, plan, facts, prior)))

    def test_missing_path_fact_rows_cannot_confirm_and_unplanned_context_is_rejected(self):
        facts = {
            "snapshot": "AUCTION_0925", "market_check_data": {"available": True},
            "validation_context_facts": [],
            "path_validation_contexts": [{
                "path_kind": "PRIMARY", "task_id": "TASK-P", "node_id": "NODE-P",
                "validation_objects": ["V.SH"], "facts": [],
            }],
        }
        result = self.result(
            [leaf("A.SH", "MEETS_AUCTION_TASK"), leaf("B.SH", "DIRECT_FAIL")],
            "A.SH", "PRIMARY_CONTINUES", "WAIT_OPEN_VALIDATION", "OPEN_0935")
        result["path_context_checks"] = [{
            "path_kind": "PRIMARY", "task_id": "TASK-P", "node_id": "NODE-P",
            "validation_objects": ["V.SH"], "status": "CONFIRMS", "observed": [],
        }]
        problems = validate_result(result, self.plan, facts)
        self.assertTrue(any("事实行未完整覆盖" in item for item in problems))
        self.assertTrue(any("必须 DATA_INSUFFICIENT" in item for item in problems))

        no_context_facts = {"snapshot": "AUCTION_0925", "validation_context_facts": []}
        extra = self.result(
            [leaf("A.SH", "MEETS_AUCTION_TASK"), leaf("B.SH", "DIRECT_FAIL")],
            "A.SH", "PRIMARY_CONTINUES", "WAIT_OPEN_VALIDATION", "OPEN_0935")
        extra["path_context_checks"] = result["path_context_checks"]
        self.assertTrue(any("必须为空" in item for item in
                            validate_result(extra, self.plan, no_context_facts)))


class GoldenReplayTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).parent / "fixtures" / "20260105"
        self.plan = json.loads((fixture / "executable_plan.json").read_text())
        self.auction = json.loads((fixture / "auction_result.json").read_text())

    def test_20260106_real_auction_facts_match_golden_scope(self):
        facts = build_validation_facts(
            self.plan, "2026-01-06", snapshot="AUCTION_0925")
        rows = {row["thscode"]: row for row in facts["action_leaf_facts"]}
        self.assertEqual(set(rows), {"002151.SZ", "600498.SH"})
        self.assertAlmostEqual(rows["002151.SZ"]["auction_open_change_pct"], 0.02, places=2)
        self.assertAlmostEqual(rows["600498.SH"]["auction_open_change_pct"], 1.96, places=2)
        self.assertEqual({row["thscode"] for row in facts["validation_context_facts"]},
                         {"002413.SZ"})
        self.assertEqual(validate_result(self.auction, self.plan, facts), [])

    def test_20260106_0935_remains_no_action_after_auction_stopped(self):
        facts = build_validation_facts(
            self.plan, "2026-01-06", snapshot="OPEN_0935", prior_result=self.auction)
        self.assertEqual(facts["action_leaf_facts"], [])
        result = {
            "leaf_results": [], "current_action_candidate": None,
            "context_check": {
                "validation_objects": ["002413.SZ"],
                "status": "DATA_INSUFFICIENT",
                "observed": ["缺少开盘五分钟验证事实"],
            },
            "condition_tree_hit": {"branch": "NO_CANDIDATE"},
            "decision": "NO_ACTION", "next_stage": "COMPLETE",
        }
        self.assertEqual(validate_result(result, self.plan, facts, self.auction), [])


if __name__ == "__main__":
    unittest.main()
