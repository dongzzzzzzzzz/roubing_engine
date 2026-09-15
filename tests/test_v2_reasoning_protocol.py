from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from roubing_engine.reasoning import (
    close_review_pipeline,
    projections,
    protocols,
    runner,
    schemas,
    semantic_audit,
)
from roubing_engine.reasoning.validation_factpack import _auction_timeline


class V2ProtocolTests(unittest.TestCase):
    def test_protocol_declares_full_environment_and_generator_coverage(self):
        self.assertEqual(len(protocols.STAGE1_OBSERVATIONS), 5)
        self.assertEqual(protocols.ENVIRONMENT_HYPOTHESES, [
            "MAIN_TREND", "ROTATION", "DECLINE", "REGIME_SWITCH",
        ])
        self.assertEqual(protocols.expected_generator_ids(), [
            f"G{i}" for i in range(1, 13)
        ])
        self.assertEqual(set(protocols.PACKS), {"M1", "M2", "M3", "M4", "M5", "M6"})

    def test_m1_projection_excludes_stock_rows_and_m3_limits_to_pool(self):
        facts = {
            "as_of": "20260304 CLOSE", "trade_date": "20260304",
            "direction_state_facts": [{
                "theme": "A", "fact_id": "F-DIR-A", "stock_fact_ids": ["F-STOCK-A"],
            }],
            "stage_b_observation_universe": [
                {"thscode": "A.SH", "theme": "A", "fact_id": "F-STOCK-A"},
                {"thscode": "B.SH", "theme": "B", "fact_id": "F-STOCK-B"},
            ],
            "failed_observations": [{"thscode": "B.SH", "fact_id": "F-STOCK-B"}],
            "fact_catalog": {
                "F-DIR-A": {"scope": "DIRECTION"},
                "F-STOCK-A": {"scope": "STOCK", "thscode": "A.SH"},
                "F-STOCK-B": {"scope": "STOCK", "thscode": "B.SH"},
            },
        }
        m1 = projections.project_macro_facts(facts, {})
        self.assertNotIn("stage_b_observation_universe", m1)
        self.assertNotIn("stock_fact_ids", m1["direction_state_facts"][0])

        m3 = projections.project_plan_facts(facts, [{
            "pool": [{"thscode": "A.SH"}], "validation_pool": [],
        }])
        self.assertEqual([row["thscode"] for row in m3["stage_b_observation_universe"]],
                         ["A.SH"])
        self.assertNotIn("F-STOCK-B", m3["fact_catalog"])

    def test_coverage_checks_require_all_stage1_and_g8_day_one_observation(self):
        macro = {
            "method_trace": [
                {"step_id": step, "status": "NOT_APPLICABLE", "fact_ids": [],
                 "counter_fact_ids": [], "judgment": "x", "downstream_effect": [],
                 "forbidden_conclusions": [], "audit_status": "PASS"}
                for step in protocols.expected_stage1_step_ids()
            ],
            "direction_evaluations": [{"theme": "A"}],
        }
        self.assertEqual(
            semantic_audit.check_macro_coverage(
                macro, {"direction_state_facts": [{"theme": "A"}]}),
            [],
        )
        node = {
            "as_of": "20260304 CLOSE",
            "generator_applicability": [
                {"generator": g, "status": "NOT_APPLICABLE"}
                for g in protocols.expected_generator_ids()
            ],
            "nodes": [{
                "generator": "G8", "anchor_date": "2026-03-04",
                "action_status": "ACTION_READY",
                "node_questions": {key: "x" for key in protocols.NODE_QUESTION_FIELDS},
            }],
        }
        problems = semantic_audit.check_node_coverage(node)
        self.assertTrue(any("G8 anchor-day" in item for item in problems))

    def test_m2_schema_requires_node_questions(self):
        result = {
            "as_of": "20260304 CLOSE",
            "generator_applicability": [
                {
                    "generator": g,
                    "status": "NOT_APPLICABLE",
                    "prior_state": "x",
                    "prior_resistance": "x",
                    "changed_facts": ["x"],
                    "benefited_function": "x",
                    "anchor_date": None,
                    "natural_candidate_scope": "x",
                    "confirm": ["x"],
                    "cancel": ["x"],
                    "fact_ids": [],
                    "counter_fact_ids": [],
                    "rule_ids": [],
                }
                for g in protocols.expected_generator_ids()
            ],
            "nodes": [{
                "node_id": "N1",
                "node_type": "x",
                "action_status": "OBSERVATION_ONLY",
                "anchor_date": "2026-03-04",
                "theme": "A",
                "trigger_facts": ["x"],
                "trigger_fact_ids": [],
                "method_reasoning": ["x"],
                "generator": None,
                "candidate_scope": {
                    "event_statuses": ["limit_up"],
                    "board_levels": [1],
                    "sub_directions": ["UNKNOWN"],
                    "candidate_ids": [],
                    "validation_ids": [],
                    "scope_reason": "x",
                },
                "candidate_ids": [],
                "rule_ids": [],
                "confirm": ["x"],
                "cancel": ["x"],
            }],
            "method_trace": [
                {"step_id": f"S3-{g}", "status": "NOT_APPLICABLE",
                 "fact_ids": [], "counter_fact_ids": [], "judgment": "x",
                 "downstream_effect": [], "forbidden_conclusions": [],
                 "audit_status": "PASS"}
                for g in protocols.expected_generator_ids()
            ],
            "data_gaps": [],
        }
        problems = runner.validate(result, schemas.M2_SCHEMA)
        self.assertTrue(any("node_questions" in item for item in problems))

    def test_m4_and_m5_minimal_structures_validate(self):
        m4 = {
            "tplus1": "2026-03-05", "snapshot": "AUCTION_0925",
            "as_of": "2026-03-05 09:25:00",
            "auction_read_order": [
                "09:15_INITIAL_DISPLAY", "09:20_ORDER_RETENTION_DECAY",
                "09:25_FINAL_MATCH",
            ],
            "path_results": [],
            "backup_independence_check": {
                "available": False, "status": "NOT_APPLICABLE", "observed": ["无备选"],
            },
            "condition_tree_hit": {
                "branch": "NO_CANDIDATE", "primary_state": None,
                "backup_state": None, "reasoning": ["无对象"],
            },
            "current_action_candidate": None, "next_stage": "STOP",
            "decision": "NO_ACTION",
            "method_trace": [
                {"step_id": f"M4-{i}", "status": "NOT_APPLICABLE",
                 "observed": ["x"], "fact_ids": [], "judgment": "x"}
                for i in range(4)
            ],
            "unknowns": [],
        }
        self.assertEqual(runner.validate(m4, schemas.M4_AUCTION_SCHEMA), [])

        m5 = {
            "tplus1": "2026-03-05", "snapshot": "OPEN_0935",
            "as_of": "2026-03-05 09:35:00", "current_action_candidate": None,
            "open_validation": {
                "sell_pressure_path": ["无"], "stop_weakening": [],
                "same_group_event_order": [], "board_response": [],
                "conclusion": "OPEN_REJECTS",
            },
            "action_trigger": {
                "method": "NONE", "method_trace": ["无"], "thscode": None,
                "reason": ["无对象"],
            },
            "decision": "NO_ACTION",
            "method_trace": [
                {"step_id": f"M5-{i}", "status": "NOT_APPLICABLE",
                 "observed": ["x"], "fact_ids": [], "judgment": "x"}
                for i in range(5)
            ],
            "unknowns": [],
        }
        self.assertEqual(runner.validate(m5, schemas.M5_OPEN_ACTION_SCHEMA), [])

    def test_auction_timeline_projects_three_checkpoints(self):
        frame = pd.DataFrame([
            {"time_label": "09:15:00", "price": 10.0, "matched_volume": 1},
            {"time_label": "09:20:00", "price": 10.1, "matched_volume": 2},
            {"time_label": "09:25:00", "price": 10.2, "matched_volume": 3},
        ])
        timeline = _auction_timeline(frame)
        self.assertEqual([row["checkpoint"] for row in timeline], [
            "09:15_INITIAL_DISPLAY", "09:20_ORDER_RETENTION_DECAY",
            "09:25_FINAL_MATCH",
        ])
        self.assertEqual(timeline[-1]["price"], 10.2)

    def test_token_usage_extracts_jsonl_usage(self):
        usage = runner.extract_usage(
            '{"usage":{"input_tokens":1,"cached_input_tokens":2,'
            '"output_tokens":3,"reasoning_tokens":4}}\n'
        )
        self.assertEqual(usage["status"], "AVAILABLE")
        self.assertEqual(usage["total_tokens"], 8)

    def test_m6_review_facts_include_close_features(self):
        plan = {
            "plan_date": "20260304", "as_of": "20260304 CLOSE",
            "action_plan": {
                "primary": {"thscode": "A.SH"}, "backup": None,
                "validation_objects": ["B.SH"],
            },
        }
        with patch("roubing_engine.reasoning.close_review_pipeline.features_for",
                   return_value={"A.SH": {"available": True},
                                 "B.SH": {"available": True}}):
            facts = close_review_pipeline._review_facts(plan, {"m5": {}}, "2026-03-05")
        self.assertTrue(facts["close_fact_boundary"]["available"])
        self.assertEqual(set(facts["close_features"]), {"A.SH", "B.SH"})


if __name__ == "__main__":
    unittest.main()
