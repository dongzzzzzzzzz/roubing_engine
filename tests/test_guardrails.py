from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from roubing_engine.collectors import storage
from roubing_engine.collectors.serialize import serialize_opening
from roubing_engine.collectors.f10_context import serialize_announcements
from roubing_engine.evaluation.fidelity import check_plan
from roubing_engine.reasoning import runner, schemas
from roubing_engine.reasoning import prompts
from roubing_engine.reasoning.validation_factpack import (
    _auction_summary,
    _open5m,
    validate_stage_d_result,
    validate_snapshot_payload,
)
from roubing_engine.warehouse.timebox import seconds_from_label, session_type
from roubing_engine.warehouse.as_of import daily_available_at
from roubing_engine.reasoning.day_factpack import _auction_strength, build as build_factpack
from roubing_engine.reasoning.evidence_compiler import compile_day, fact_id
from roubing_engine.features.index_ctx import intraday_market_context
from roubing_engine.rules.regulatory import active_rules
from roubing_engine.rules.evidence_bundle import bundle_for_audit, bundle_for_nodes
from roubing_engine.rules.retrieve import select as select_rules
from roubing_engine.rules import corpus_index
from roubing_engine.rules.corpus_index import search as search_posts
from roubing_engine.rules.themes import canonical_theme, hierarchy_for, same_theme
from roubing_engine.features.risk_ctx import risk_context


class TimeSnapshotTests(unittest.TestCase):
    def test_theme_hierarchy_never_merges_separate_energy_directions(self):
        hierarchy = hierarchy_for(["油服工程", "石油化工", "油气开采"], "2026-03-02")
        self.assertTrue(all(item["parent_theme"] == "油气能源链" for item in hierarchy))
        self.assertTrue(all(item["executable_merge_allowed"] is False for item in hierarchy))
        self.assertFalse(same_theme("油服工程", "石油化工", "2026-03-02"))

    def test_theme_mapping_obeys_valid_from_date(self):
        _, before = canonical_theme("油服工程", "2026-01-05")
        _, active = canonical_theme("油服工程", "2026-03-02")
        self.assertIsNone(before["parent_theme"])
        self.assertEqual(active["parent_theme"], "油气能源链")

    def test_opening_match_partition_schema_and_coverage(self):
        path = Path(__file__).parents[1] / "data" / "warehouse" / "opening_match" / "date=20260106" / "part.parquet"
        if not path.exists():
            self.skipTest("captured 2026-01-06 opening_match fixture is not present")
        frame = pd.read_parquet(path)
        required = {"time_label", "trade_datetime", "price", "volume",
                    "order_count", "trade_amount_yuan", "event_kind",
                    "thscode", "trade_date"}
        self.assertTrue(required.issubset(frame.columns))
        self.assertGreater(len(frame), 0)
        self.assertEqual(frame["thscode"].nunique(), len(frame))
        self.assertTrue(frame["price"].notna().all())
        self.assertTrue((frame["time_label"] == "09:25").all())

    def test_opening_serializer_uses_0925_price_for_legacy_response(self):
        snapshot = type("Snapshot", (), {
            "time_label": "09:25", "trade_datetime": None, "price": 10.5,
            "volume": 100, "order_count": 2, "trade_amount_yuan": 1050.0,
            "event_kind": "OPENING_MATCH",
        })()
        auction = type("Auction", (), {
            "snapshot_0925": snapshot,
            "pre_close_price": None, "open_price": None,
            "open_change_pct": None, "open_amount": None,
        })()
        rows = serialize_opening(auction, "000001.SZ", "20260106")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price"], 10.5)
        self.assertEqual(rows[0]["open_price"], 10.5)
        self.assertIsNone(rows[0]["pre_close_price"])

    def test_opening_strength_derives_change_from_previous_close(self):
        strength = _auction_strength("20260106")
        row = strength["300409.SZ"]
        self.assertIsNotNone(row["open_price"])
        self.assertIsNotNone(row["pre_close_price"])
        expected = round((row["open_price"] / row["pre_close_price"] - 1) * 100, 2)
        self.assertEqual(row["open_change_pct"], expected)

    def test_opening_strength_keeps_missing_code_missing(self):
        strength = _auction_strength("20260106")
        self.assertNotIn("300003.SZ", strength)

    def test_intraday_market_context_marks_missing_as_blocked(self):
        context = intraday_market_context("2026-01-06", "OPEN_0935")
        self.assertFalse(context["available"])
        self.assertEqual(context["status"], "BLOCKED_DATA")
        self.assertEqual(context["datasets"]["index_intraday"], "MISSING")
        self.assertEqual(context["datasets"]["theme_intraday"], "MISSING")

    def test_intraday_market_context_filters_rows_at_snapshot(self):
        import tempfile
        from unittest.mock import patch
        from roubing_engine.features import index_ctx
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for dataset in ("index_minute_bar", "theme_minute_bar"):
                path = root / dataset / "date=20260106"
                path.mkdir(parents=True)
                pd.DataFrame([
                    {"time_label": "09:35:59", "series": dataset, "value": 1.0},
                    {"time_label": "09:36:00", "series": dataset, "value": 2.0},
                ]).to_parquet(path / "part.parquet", index=False)
            with patch.object(index_ctx, "WAREHOUSE", root):
                context = intraday_market_context("2026-01-06", "OPEN_0935")
            self.assertTrue(context["available"])
            self.assertEqual(len(context["index_rows"]), 1)
            self.assertEqual(len(context["theme_rows"]), 1)
        self.assertEqual(context["index_rows"][0]["value"], 1.0)

    def test_direction_facts_keep_event_counts_and_mark_diffusion_gap(self):
        facts = compile_day("20260105")
        row = next(item for item in facts["direction_facts"] if item["theme"] == "人脑工程")
        self.assertGreater(row["n_limit_up"], 0)
        self.assertIn("1", row["ladder_distribution"])
        self.assertIn(row["opening_match_coverage"]["status"], {"AVAILABLE", "PARTIAL", "MISSING"})
        self.assertEqual(row["diffusion"]["status"], "BLOCKED_DATA")
        self.assertFalse(row["diffusion"]["available"])

    def test_fact_ids_are_stable_and_catalogued(self):
        first = build_factpack("20260105", with_index=False)
        second = build_factpack("20260105", with_index=False)
        self.assertEqual(first["fact_catalog"], second["fact_catalog"])
        self.assertEqual(
            fact_id("20260105", "DIR", "人脑工程"),
            next(item["fact_id"] for item in first["direction_state_facts"]
                 if item["theme"] == "人脑工程"),
        )
        self.assertTrue(first["environment_facts"])
        self.assertTrue(all(item["fact_id"] in first["fact_catalog"]
                            for item in first["direction_state_facts"]))

    def test_path_comparison_contract_separates_history_from_cross_section(self):
        facts = build_factpack("20260105", with_index=False)
        contract = facts["path_comparison_contract"]
        self.assertTrue(contract["cross_section_comparison_available"])
        self.assertGreaterEqual(contract["comparable_direction_count"], 2)
        self.assertFalse(contract["historical_confirmation_available"])
        self.assertIn("不得仅因此写BLOCKED_DATA", contract["blocking_semantics"])

    def test_stock_observations_expose_operational_fact_fields(self):
        facts = build_factpack("20260105", with_index=False)
        stock = facts["stage_b_observation_universe"][0]
        required = {
            "fact_id", "direction_fact_id", "sub_direction", "board_level",
            "limit_time", "turnover_percentile_250d", "prior_high",
            "previous_role_task", "fact_refs",
        }
        self.assertTrue(required.issubset(stock))
        self.assertIn(stock["fact_id"], facts["fact_catalog"])
        self.assertIn(stock["direction_fact_id"], facts["fact_catalog"])

    def test_limit_run_anchor_uses_trading_calendar_not_calendar_subtraction(self):
        facts = build_factpack("20260105", with_index=False)
        rows = {row["thscode"]: row for row in facts["stage_b_observation_universe"]}
        self.assertEqual(rows["002151.SZ"]["event_anchor_date"], "2025-12-31")
        self.assertEqual(rows["600498.SH"]["event_anchor_date"], "2025-12-31")
        self.assertEqual(rows["002413.SZ"]["event_anchor_date"], "2025-12-29")
        self.assertEqual(rows["002151.SZ"]["event_anchor_status"], "DERIVED")

    def test_context_status_separates_collector_capture_and_history_safety(self):
        facts = compile_day("20260105")
        context = facts["context_data"]
        self.assertTrue(context["announcement"]["collector_exists"])
        self.assertTrue(context["hot_topic"]["collector_exists"])
        self.assertFalse(context["announcement"]["captured_today"])
        self.assertFalse(context["hot_topic"]["captured_today"])
        self.assertEqual(context["announcement"]["status"], "BLOCKED_DATA")
        self.assertEqual(context["hot_topic"]["status"], "BLOCKED_DATA")

    def test_regulatory_rules_are_selected_by_effective_date(self):
        current = active_rules("2026-01-05")
        self.assertTrue(current["available"])
        self.assertEqual(current["status"], "READY")
        self.assertEqual({rule["id"] for rule in current["rules"]},
                         {"SSE_TRADING_RULES_2023", "SZSE_TRADING_RULES_2023"})
        self.assertFalse(current["numeric_thresholds_available"])
        self.assertIn("不得计算异动距离", current["data_block"])
        before = active_rules("2022-12-31")
        self.assertFalse(before["available"])
        self.assertEqual(before["status"], "BLOCKED_DATA")

    def test_risk_context_marks_optional_missing_datasets(self):
        context = risk_context("20260105", ["300409.SZ"])
        self.assertFalse(context["available"])
        self.assertEqual(set(context["datasets"]),
                         {"suspension", "special_monitor", "risk_notice"})
        self.assertTrue(all(item["status"] == "BLOCKED_DATA"
                            for item in context["datasets"].values()))
    def test_daily_asof_accepts_partition_date_format(self):
        self.assertEqual(daily_available_at("20260908").isoformat(),
                         daily_available_at("2026-09-08").isoformat())

    def test_auction_summary_excludes_closing_auction(self):
        frame = pd.DataFrame([
            {"time_label": "09:15:01", "time_seconds": 33301, "price": 10.0,
             "matched_volume": 100, "session_type": "OPENING_AUCTION"},
            {"time_label": "09:24:58", "time_seconds": 33898, "price": 10.2,
             "matched_volume": 500, "session_type": "OPENING_AUCTION"},
            {"time_label": "14:59:58", "time_seconds": 53998, "price": 9.1,
             "matched_volume": 900, "session_type": "CLOSING_AUCTION"},
        ])
        summary = _auction_summary(frame)
        self.assertEqual(summary["last_time"], "09:24:58")
        self.assertEqual(summary["last_observed_process_price"], 10.2)
        self.assertNotIn("final_price", summary)

    def test_auction_summary_exposes_raw_unmatched_observations(self):
        frame = pd.DataFrame([
            {"time_label": "09:15:01", "time_seconds": 33301, "price": 10.0,
             "matched_volume": 100, "unmatched_volume": 900,
             "unmatched_signed_raw": 900, "unmatched_direction_raw": 1,
             "session_type": "OPENING_AUCTION"},
            {"time_label": "09:24:58", "time_seconds": 33898, "price": 10.2,
             "matched_volume": 500, "unmatched_volume": 400,
             "unmatched_signed_raw": -400, "unmatched_direction_raw": -1,
             "session_type": "OPENING_AUCTION"},
        ])
        summary = _auction_summary(frame)
        self.assertEqual(summary["unmatched_first_observed_vol"], 900)
        self.assertEqual(summary["unmatched_last_observed_vol"], 400)
        self.assertEqual(summary["unmatched_peak_vol"], 900)
        self.assertEqual(summary["unmatched_signed_last_raw"], -400)
        self.assertEqual(summary["unmatched_direction_first_raw"], 1)
        self.assertEqual(summary["unmatched_direction_last_raw"], -1)

    def test_open5m_never_exposes_close(self):
        frame = pd.DataFrame([
            {"time_label": "09:31", "price": 10.0},
            {"time_label": "09:35", "price": 10.2},
            {"time_label": "15:00", "price": 8.0},
        ])
        result = _open5m(frame, 10.0, 9.8)
        self.assertEqual(result["last_time"], "09:35")
        self.assertNotIn("day_close_price", result)
        self.assertEqual(len(result["path"]), 2)

    def test_payload_guard_rejects_outcome_fields(self):
        facts = {
            "snapshot": "OPEN_0935",
            "candidates": [{"tplus1_close": 10.0, "open_5min": {"path": []}}],
        }
        self.assertTrue(validate_snapshot_payload(facts))

    def test_session_classifier(self):
        self.assertEqual(session_type(seconds_from_label("09:24:58")), "OPENING_AUCTION")
        self.assertEqual(session_type(seconds_from_label("14:59:58")), "CLOSING_AUCTION")


class StorageTests(unittest.TestCase):
    def test_targeted_merge_preserves_other_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_warehouse = storage.WAREHOUSE
            storage.WAREHOUSE = Path(tmp)
            try:
                base = [
                    {"trade_date": "20260909", "thscode": "A.SH", "time_label": "09:31",
                     "source": "eltdx", "price": 1.0},
                    {"trade_date": "20260909", "thscode": "B.SH", "time_label": "09:31",
                     "source": "eltdx", "price": 2.0},
                ]
                storage.write_dataset("minute_bar", "20260909", base, mode="replace")
                storage.write_dataset("minute_bar", "20260909", [{
                    "trade_date": "20260909", "thscode": "A.SH", "time_label": "09:31",
                    "source": "eltdx", "price": 1.5,
                }], mode="merge")
                result = pd.read_parquet(
                    Path(tmp) / "minute_bar" / "date=20260909" / "part.parquet")
                self.assertEqual(set(result["thscode"]), {"A.SH", "B.SH"})
                self.assertEqual(float(result[result["thscode"] == "A.SH"].iloc[0]["price"]), 1.5)
                captures = list((Path(tmp) / "_captures" / "minute_bar" /
                                 "date=20260909").glob("capture=*.parquet"))
                self.assertEqual(len(captures), 2)
            finally:
                storage.WAREHOUSE = old_warehouse


class F10ContextTests(unittest.TestCase):
    def test_announcement_is_filtered_by_historical_availability(self):
        response = type("Response", (), {"rows": [
            {"rec_id": "old", "title": "已知公告", "issue_date": "2026-09-08 00:00:00",
             "redistime": "2026-09-08 12:00:00", "source": "上交所"},
            {"rec_id": "future", "title": "未来公告", "issue_date": "2026-09-09 00:00:00",
             "redistime": "2026-09-08 16:00:00", "source": "上交所"},
        ]})()
        rows = serialize_announcements(response, "600108.SH", "2026-09-08")
        self.assertEqual([row["rec_id"] for row in rows], ["old"])


class SchemaAndFidelityTests(unittest.TestCase):
    def test_stage_d_prompt_includes_data_insufficient_auction_state(self):
        self.assertIn("DATA_INSUFFICIENT", prompts.stage_d_instructions())
        self.assertIn("缺开盘五分钟或逐笔时是否写成确认", prompts.stage_d_audit_instructions())
        self.assertIn("execution_nodes", prompts.stage_d_instructions())
        self.assertIn("path_context_checks", prompts.stage_d_instructions())

    def test_stage_d_requires_every_frozen_execution_node(self):
        facts = {
            "snapshot": "AUCTION_0925", "market_check_data": {"available": True},
            "execution_context": {
                "execution_task": {"task_id": "TASK-P", "task_type": "CORE_SWITCH",
                                   "theme": "示例", "anchor_date": "2026-01-05"},
                "execution_tasks": [{
                    "path_kind": "PRIMARY", "task_id": "TASK-P", "task_type": "CORE_SWITCH",
                    "theme": "示例", "node_id": "NODE-P", "anchor_date": "2026-01-05",
                }],
            },
            "action_leaf_facts": [],
            "relative_auction_contract": {
                "status": "NOT_APPLICABLE", "stronger_code": None, "weaker_code": None,
                "comparison_text": "当前快照不需要双叶子竞价比较",
            },
        }
        result = {
            "market_check": {"index_held": True},
            "reasoning_trace": {
                "step_order": ["MARKET_AND_PATH", "EXECUTION_NODE", "ACTION_LEAVES"],
                "market_and_path": {"status": "SUPPORTED", "observed": ["可用"]},
                "execution_node": {
                    "status": "SUPPORTED", "task_id": "TASK-P", "task_type": "CORE_SWITCH",
                    "theme": "示例", "anchor_date": "2026-01-05", "observed": ["冻结"]},
                "execution_nodes": [],
            },
            "context_check": {"status": "NOT_REQUIRED", "observed": []},
            "path_context_checks": [], "leaf_results": [],
            "auction_pair_comparison": facts["relative_auction_contract"],
        }
        problems = validate_stage_d_result(result, facts)
        self.assertTrue(any("execution_nodes" in item for item in problems))

    def test_stage_c_prompt_states_role_family_and_same_group_discipline(self):
        text = prompts.stage_c_instructions()
        self.assertIn("分支核心→核心", text)
        self.assertIn("competitors", text)
        self.assertIn("只能填写", text)

    def test_stage_c_prompt_includes_competition_group_schema_fields(self):
        text = prompts.stage_c_instructions()
        self.assertIn('"coverage_status": "COMPLETE|PARTIAL|MISSING"', text)
        self.assertIn('"next_day_tasks": ["全组次日需逐一验证的任务"]', text)
        self.assertIn(
            '"uniqueness_status": "UNRESOLVED|CONFIRMED|REPLACED|CANCELLED"',
            text,
        )

    def test_stage_d_hard_gate_blocks_missing_open5m_confirmation(self):
        facts = {"snapshot": "OPEN_0935", "market_check_data": {"available": False},
                 "action_leaf_facts": [{"thscode": "A.SH", "data_completeness": {
                     "opening_match": "AVAILABLE", "opening_auction": "AVAILABLE",
                     "open_5min": "MISSING", "first5m_activity": "MISSING"}}]}
        result = {"market_check": {"index_held": None}, "leaf_results": [{
            "thscode": "A.SH", "leaf_state": "MEETS_OPEN_TASK",
            "observed": [], "vs_plan": ""
        }]}
        problems = validate_stage_d_result(result, facts)
        self.assertTrue(any("open_5min coverage" in item for item in problems))

    def test_stage_d_auction_snapshot_forbids_open5_conclusion(self):
        facts = {"snapshot": "AUCTION_0925", "market_check_data": {"available": False},
                 "action_leaf_facts": [{"thscode": "A.SH", "data_completeness": {
                     "opening_match": "AVAILABLE", "opening_auction": "AVAILABLE",
                     "open_5min": "NOT_IN_SNAPSHOT", "first5m_activity": "NOT_IN_SNAPSHOT"}}]}
        result = {"market_check": {"index_held": None}, "leaf_results": [{
            "thscode": "A.SH", "leaf_state": "MEETS_OPEN_TASK",
            "observed": [], "vs_plan": ""
        }]}
        problems = validate_stage_d_result(result, facts)
        self.assertTrue(any("09:25 forbids" in item for item in problems))
    def _valid_candidate(self):
        return {
            "thscode": "A.SH", "name": "示例A", "theme": "示例",
            "task_id": "TASK-EXAMPLE", "observed_function": "同板级晋级",
            "task_relation": "ACTION_COMPETITOR", "node": "NODE",
            "node_id": "NODE-EXAMPLE", "generator": "G8",
            "anchor_date": "2026-09-08", "stock_start_date": "2026-09-08",
            "role": "UNKNOWN", "role_family": "UNKNOWN", "role_status": "CANDIDATE",
            "letter_carrier": "UNKNOWN",
            "capacity_tasks": {"price_progression": "未知", "pullback_recovery": "未知", "sector_leadership": "未知", "center_of_gravity": "未知", "replacement_state": "未确认"},
            "agency_event_model": {"reference": "同组", "reference_task_id": "TASK-EXAMPLE",
                                   "event_sequence": ["未知"], "target_behavior": "未知",
                                   "data_sufficiency": "UNKNOWN", "conclusion": "UNKNOWN",
                                   "relation_state": "INDEPENDENCE_NOT_CONFIRMED",
                                   "role_replacement_basis": []},
            "competition_group": "g", "competitors": [], "observed_state": ["事实"],
            "tomorrow_must_do": ["任务"], "acceptable_variants": [],
            "failure_signals": ["失败"], "cancel_if": ["取消"], "output_tier": "待验证候选",
            "evidence": ["事实来源"],
        }

    def _valid_stage_c(self):
        claim = {"status": "UNKNOWN", "statement": "无法确认", "evidence": []}
        return {
            "as_of": "20260908 CLOSE",
            "execution_task": {
                "status": "SELECTED", "task_id": "TASK-EXAMPLE",
                "task_type": "SAME_LEVEL_PROMOTION", "theme": "示例",
                "missing_function": "同板级晋级者",
                "selection_logic": ["同任务对象可比较"],
                "supporting_fact_ids": [], "rejected_task_ids": [],
            },
            "action_competition_group": {
                "task_id": "TASK-EXAMPLE", "members": ["A.SH"],
                "validation_objects": [], "comparison_basis": ["同任务"],
                "resolved_out": [], "unresolved": [],
            },
            "pairwise_comparison": [],
            "action_plan": {
                "status": "SINGLE", "task_id": "TASK-EXAMPLE",
                "primary": {
                    "thscode": "A.SH", "task_id": "TASK-EXAMPLE", "path_kind": "PRIMARY",
                    "task_to_complete": "独立晋级",
                    "auction_conditions": ["竞价相对同任务对象不弱"],
                    "open_conditions": ["开盘后完成自身任务"],
                    "downgrade_conditions": ["仅需开盘确认"],
                    "direct_fail_conditions": ["任务直接失败"],
                },
                "backup": None, "validation_objects": [],
                "switch_rule": "单对象，无备选切换",
                "no_action_conditions": ["对象未完成任务"],
            },
            "competition_groups": [{
            "group_id": "g", "generator": "G8", "anchor_date": "2026-09-08",
            "theme": "示例", "comparison_basis": ["同方向同起算"], "members": ["A.SH"],
            "not_comparable_with": [],
            "leader_state": {"status": "UNRESOLVED", "thscode": None, "evidence": []},
            "pairwise_relations": [], "next_confirmation": ["次日确认"],
            "coverage_status": "PARTIAL", "next_day_tasks": ["逐一验证"],
            "uniqueness_status": "UNRESOLVED",
            }],
            "candidates": [self._valid_candidate()],
            "excluded_candidates": [],
            "paths": {
                "primary": {"observed_facts": ["事实"], "ai_inferences": [], "unknowns": ["未知"],
                            "capital_source": dict(claim), "buyer": dict(claim),
                            "seller": dict(claim), "destination_layer": dict(claim),
                            "successor": dict(claim), "confirm": [], "cancel": []},
                "alternative": {"observed_facts": ["事实"], "ai_inferences": [], "unknowns": ["未知"],
                                "capital_source": dict(claim), "buyer": dict(claim),
                                "seller": dict(claim), "destination_layer": dict(claim),
                                "successor": dict(claim), "trigger": [], "cancel": []},
                "no_action": {"observed_facts": ["事实"], "ai_inferences": [],
                              "unknowns": ["未知"], "trigger": []},
            },
            "unknowns": [],
        }

    def _valid_stage_c2(self):
        legacy = self._valid_stage_c()
        primary_selection = {
            "path_kind": "PRIMARY", "status": "SELECTED",
            "task_id": "TASK-EXAMPLE", "task_type": "SAME_LEVEL_PROMOTION",
            "theme": "示例", "node_id": "NODE-EXAMPLE",
            "missing_function": "同板级晋级者", "selection_logic": ["节点需要晋级功能"],
            "supporting_fact_ids": [], "rule_ids": [], "rejected_task_ids": [],
        }
        alternative_selection = {
            "path_kind": "ALTERNATIVE", "status": "NONE",
            "task_id": None, "task_type": None, "theme": None, "node_id": None,
            "missing_function": "没有独立替代任务", "selection_logic": ["无合法替代节点"],
            "supporting_fact_ids": [], "rule_ids": [], "rejected_task_ids": [],
        }
        path_analysis = dict(legacy["paths"]["primary"])
        path_analysis["trigger"] = []
        return {
            "as_of": legacy["as_of"],
            "task_selection": {
                "primary_task": primary_selection,
                "alternative_task": alternative_selection,
                "no_action_conditions": ["主路径对象不完成任务"],
            },
            "path_plans": [{
                "path_kind": "PRIMARY",
                "execution_task": legacy["execution_task"],
                "path_analysis": path_analysis,
                "competition_group": legacy["competition_groups"][0],
                "pairwise_comparison": legacy["pairwise_comparison"],
                "action_plan": legacy["action_plan"],
                "candidates": legacy["candidates"],
                "excluded_candidates": legacy["excluded_candidates"],
                "unknowns": [],
            }],
            "final_action_plan": {
                "status": "SINGLE",
                "primary_ref": {"path_kind": "PRIMARY", "task_id": "TASK-EXAMPLE",
                                "thscode": "A.SH"},
                "backup_ref": None,
                "switch_rule": "单对象，无备选切换",
                "no_action_conditions": ["主对象未完成任务"], "rule_ids": [],
            },
            "unknowns": [],
        }

    def test_nested_schema_rejects_incomplete_candidate(self):
        result = self._valid_stage_c2()
        del result["path_plans"][0]["candidates"][0]["tomorrow_must_do"]
        problems = runner.validate(result, schemas.STAGE_C_SCHEMA)
        self.assertTrue(any("tomorrow_must_do" in problem for problem in problems))

    def test_schema_requires_formal_role_status(self):
        result = self._valid_stage_c2()
        del result["path_plans"][0]["candidates"][0]["role_status"]
        problems = runner.validate(result, schemas.STAGE_C_SCHEMA)
        self.assertTrue(any("role_status" in problem for problem in problems))

    def test_schema_rejects_letter_guess(self):
        result = self._valid_stage_c2()
        result["path_plans"][0]["candidates"][0]["letter_carrier"] = "A"
        problems = runner.validate(result, schemas.STAGE_C_SCHEMA)
        self.assertTrue(any("letter_carrier" in problem for problem in problems))

    def test_fidelity_rejects_role_family_mismatch(self):
        stage_b = {"environment": {"candidate": "ROTATION"}, "nodes": [
            {"generator": "G8", "anchor_date": "2026-09-08", "theme": "示例"}]}
        stage_c = self._valid_stage_c()
        stage_c["candidates"][0]["role"] = "容量核心"
        stage_c["candidates"][0]["role_family"] = "核心"
        pools = [{"generator": "G8", "anchor_date": "2026-09-08", "theme": "示例",
                  "pool": [{"thscode": "A.SH", "name": "示例A", "theme": "示例",
                            "limit_time": None}]}]
        result = check_plan(stage_b, stage_c, pools)
        self.assertTrue(any("role_family" in item for item in result["violations"]))

    def test_fidelity_rejects_candidate_theme_mismatch(self):
        stage_b = {"environment": {"candidate": "ROTATION"}, "nodes": [
            {"generator": "G8", "anchor_date": "2026-09-08", "theme": "事实方向"}]}
        stage_c = self._valid_stage_c()
        stage_c["candidates"][0]["theme"] = "错误方向"
        pools = [{"generator": "G8", "anchor_date": "2026-09-08", "theme": "事实方向",
                  "pool": [{"thscode": "A.SH", "name": "示例A", "theme": "事实方向",
                            "limit_time": None}]}]
        result = check_plan(stage_b, stage_c, pools)
        self.assertTrue(any("theme 与候选池事实不一致" in item for item in result["violations"]))

    def test_fidelity_rejects_candidate_name_mismatch(self):
        stage_b = {"environment": {"candidate": "ROTATION"}, "nodes": [
            {"generator": "G8", "anchor_date": "2026-09-08", "theme": "示例"}]}
        stage_c = self._valid_stage_c()
        stage_c["candidates"][0]["name"] = "错误名称"
        pools = [{"generator": "G8", "anchor_date": "2026-09-08", "theme": "示例",
                  "status": "READY", "pool": [{"thscode": "A.SH", "name": "示例A",
                                                   "theme": "示例", "limit_time": "09:50:00"}]}]
        result = check_plan(stage_b, stage_c, pools)
        self.assertTrue(any("name 与候选池事实不一致" in item for item in result["violations"]))

    def test_fidelity_rejects_reversed_pairwise_event_order(self):
        stage_b = {"environment": {"candidate": "ROTATION"}, "nodes": [
            {"generator": "G8", "anchor_date": "2026-09-08", "theme": "示例"}]}
        stage_c = self._valid_stage_c()
        group = stage_c["competition_groups"][0]
        group["members"] = ["A.SH", "B.SH"]
        group["pairwise_relations"] = [{
            "left_thscode": "A.SH", "right_thscode": "B.SH",
            "left_event_time": "09:50:00", "right_event_time": "09:40:00",
            "relation": "LEFT_EARLIER", "evidence": ["封板时间"],
        }]
        stage_c["excluded_candidates"] = [{
            "thscode": "B.SH", "name": "示例B", "theme": "示例",
            "generator": "G8", "anchor_date": "2026-09-08", "reason": "待次日验证",
        }]
        pools = [{"generator": "G8", "anchor_date": "2026-09-08", "theme": "示例",
                  "status": "READY", "pool": [
                      {"thscode": "A.SH", "name": "示例A", "theme": "示例",
                       "limit_time": "09:50:00"},
                      {"thscode": "B.SH", "name": "示例B", "theme": "示例",
                       "limit_time": "09:40:00"},
                  ]}]
        result = check_plan(stage_b, stage_c, pools)
        self.assertTrue(any("先后关系写反" in item for item in result["violations"]))

    def test_fidelity_rejects_g8_same_day_active_or_role_confirmation(self):
        stage_b = {"environment": {"candidate": "ROTATION"}, "nodes": [
            {"generator": "G8", "anchor_date": "2026-09-08", "theme": "示例"}]}
        stage_c = self._valid_stage_c()
        candidate = stage_c["candidates"][0]
        candidate["role"] = "情绪核心"
        candidate["role_family"] = "核心"
        candidate["role_status"] = "CONFIRMED"
        candidate["agency_event_model"]["data_sufficiency"] = "SUFFICIENT"
        candidate["agency_event_model"]["conclusion"] = "ACTIVE"
        candidate["output_tier"] = "主候选"
        group = stage_c["competition_groups"][0]
        group["leader_state"] = {"status": "PROVISIONAL", "thscode": "A.SH", "evidence": ["早"]}
        pools = [{"generator": "G8", "anchor_date": "2026-09-08", "theme": "示例",
                  "status": "READY", "pool": [{"thscode": "A.SH", "name": "示例A",
                                                   "theme": "示例", "limit_time": "09:30:00"}]}]
        result = check_plan(stage_b, stage_c, pools)
        self.assertTrue(any("不得提前确认角色" in item for item in result["violations"]))
        self.assertTrue(any("不足以确认主动或被动" in item for item in result["violations"]))
        self.assertTrue(any("不得确认或暂定leader" in item for item in result["violations"]))

    def test_fidelity_rejects_g8_same_day_provisional_role_status(self):
        stage_b = {"environment": {"candidate": "ROTATION"}, "nodes": [
            {"generator": "G8", "anchor_date": "2026-09-08", "theme": "示例"}]}
        stage_c = self._valid_stage_c()
        stage_c["candidates"][0]["role_status"] = "PROVISIONAL"
        pools = [{"generator": "G8", "anchor_date": "2026-09-08", "theme": "示例",
                  "status": "READY", "pool": [{"thscode": "A.SH", "name": "示例A",
                                                   "theme": "示例", "limit_time": "09:30:00"}]}]
        result = check_plan(stage_b, stage_c, pools)
        self.assertTrue(any("role_status 只能 CANDIDATE/UNKNOWN" in item
                            for item in result["violations"]))

    def test_fidelity_rejects_g8_same_day_exclusion(self):
        stage_b = {"environment": {"candidate": "ROTATION"}, "nodes": [
            {"generator": "G8", "anchor_date": "2026-09-08", "theme": "示例"}]}
        stage_c = self._valid_stage_c()
        stage_c["candidates"] = []
        stage_c["excluded_candidates"] = [{
            "thscode": "A.SH", "name": "示例A", "theme": "示例", "generator": "G8",
            "anchor_date": "2026-09-08", "reason": "当日封板较晚",
        }]
        pools = [{"generator": "G8", "anchor_date": "2026-09-08", "theme": "示例",
                  "status": "READY", "pool": [{"thscode": "A.SH", "name": "示例A",
                                                   "theme": "示例", "limit_time": "10:00:00"}]}]
        result = check_plan(stage_b, stage_c, pools)
        self.assertTrue(any("不得排除同期成员" in item for item in result["violations"]))

    def test_fidelity_rejects_supported_buyer_story_without_tick_or_feedback(self):
        stage_b = {"environment": {"candidate": "ROTATION"}, "nodes": [
            {"generator": "G8", "anchor_date": "2026-09-08", "theme": "示例"}]}
        stage_c = self._valid_stage_c()
        stage_c["paths"]["primary"]["buyer"] = {
            "status": "SUPPORTED", "statement": "新资金确定承接", "evidence": ["涨停"],
        }
        pools = [{"generator": "G8", "anchor_date": "2026-09-08", "theme": "示例",
                  "status": "READY", "pool": [{"thscode": "A.SH", "name": "示例A",
                                                   "theme": "示例", "limit_time": None}]}]
        facts = {
            "data_completeness": {"trade_tick": {"available": False}},
            "previous_buyer_feedback": {"available": False},
        }
        result = check_plan(stage_b, stage_c, pools, facts=facts)
        self.assertTrue(any("缺逐笔或昨日买方反馈" in item for item in result["violations"]))

    def test_fidelity_rejects_candidate_outside_pool(self):
        stage_b = {"environment": {"candidate": "ROTATION"}, "nodes": [{
            "generator": "G8", "anchor_date": "2026-09-08", "theme": "示例"}]}
        stage_c = self._valid_stage_c()
        pools = [{"generator": "G8", "anchor_date": "2026-09-08", "theme": "示例",
                  "pool": []}]
        result = check_plan(stage_b, stage_c, pools)
        self.assertEqual(result["verdict"], "NEEDS_REVISION")
        self.assertTrue(any("确定性候选池" in item for item in result["violations"]))

    def test_fidelity_rejects_score_or_position_output(self):
        stage_b = {"environment": {"candidate": "ROTATION"}, "nodes": [{
            "generator": "G8", "anchor_date": "2026-09-08", "theme": "示例"}]}
        stage_c = self._valid_stage_c()
        stage_c["candidates"][0]["score"] = 88
        stage_c["position_size"] = "half"
        pools = [{"generator": "G8", "anchor_date": "2026-09-08", "theme": "示例",
                  "pool": [{"thscode": "A.SH", "name": "示例A", "theme": "示例",
                            "limit_time": None}]}]
        result = check_plan(stage_b, stage_c, pools)
        self.assertTrue(any("固定打分/概率/仓位" in item for item in result["violations"]))

    def test_partial_pool_cannot_create_primary_candidate(self):
        stage_b = {"environment": {"candidate": "ROTATION"}, "nodes": [{
            "generator": "G8", "anchor_date": "2026-09-08", "theme": "示例"}]}
        stage_c = self._valid_stage_c()
        stage_c["candidates"][0]["output_tier"] = "主候选"
        pools = [{"generator": "G8", "anchor_date": "2026-09-08", "theme": "示例",
                  "status": "PARTIAL_DATA", "pool": [{"thscode": "A.SH", "name": "示例A",
                                                           "theme": "示例", "limit_time": None}]}]
        result = check_plan(stage_b, stage_c, pools)
        self.assertTrue(any("PARTIAL_DATA" in item for item in result["violations"]))

    def test_valid_schema(self):
        self.assertEqual(runner.validate(self._valid_stage_c2(), schemas.STAGE_C_SCHEMA), [])


class CorpusTests(unittest.TestCase):
    def test_corpus_sources_are_portable_and_bundled(self):
        repo_root = Path(__file__).parents[1]
        expected_root = repo_root / "reference" / "corpus"
        self.assertEqual(corpus_index.CORPUS_ROOT, expected_root)
        self.assertTrue(all(path.parent == expected_root for path in corpus_index.SOURCES))
        self.assertTrue(all(path.exists() for path in corpus_index.SOURCES))

    def test_rules_are_strictly_cut_off_for_historical_replay(self):
        selected = select_rules(as_of="2026-01-05")
        ids = {item["id"] for item in selected}
        self.assertIn("G06_DIVERGENCE_REPAIR", ids)
        self.assertNotIn("PRIM_EXPECTATION_DELTA", ids)
        self.assertIn("G09_CORE_SWITCH", ids)
        self.assertIn("ROLE_ASSIST_LETTER", ids)
        self.assertIn("ROLE_TOTAL_CORE", ids)
        self.assertTrue(all(
            all(str(date)[:10] <= "2026-01-05" for date in item.get("source_dates") or [])
            for item in selected
        ))
        self.assertIn("DISC_NO_HINDSIGHT", ids)
        self.assertIn("DISC_SNAPSHOT_NOT_THRESHOLD", ids)

    def test_original_posts_are_strictly_cut_off_for_historical_replay(self):
        posts = search_posts(["主流"], limit=282, as_of="2026-01-05")
        self.assertGreater(len(posts), 0)
        self.assertTrue(all(str(item["date"])[:10] <= "2026-01-05" for item in posts))

    def test_evidence_bundle_respects_knowledge_cutoff(self):
        bundle = bundle_for_nodes(
            [{"node_type": "CORE_SWITCH", "theme": "示例"}],
            limit=20,
            as_of="2026-01-05",
        )
        self.assertEqual(bundle["knowledge_cutoff"], "2026-01-05")
        self.assertIn("G09_CORE_SWITCH", bundle["required_rule_ids"])
        self.assertTrue(all(
            str(item.get("date"))[:10] <= "2026-01-05"
            for item in bundle.get("case_cards") or []
        ))

    def test_corpus_keeps_full_text(self):
        path = Path(__file__).parents[1] / "roubing_engine" / "rules" / "corpus_units.json"
        units = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(units), 282)
        self.assertTrue(all("text" in unit for unit in units))
        self.assertTrue(any(len(unit["text"]) > 400 for unit in units))

    def test_corpus_case_cards_are_traceable(self):
        path = Path(__file__).parents[1] / "roubing_engine" / "rules" / "corpus_case_cards.json"
        cards = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(cards), 282)
        required = {"case_id", "date", "title", "hash", "text", "snippet",
                    "applicable_conditions", "counterexamples", "evidence_level"}
        self.assertTrue(all(required.issubset(card) for card in cards))
        self.assertEqual(len({card["hash"] for card in cards}), len(cards))
        self.assertTrue(all(card["evidence_level"] == "RAW_POST" for card in cards))

    def test_node_evidence_recall_bundle_has_required_rules_and_cases(self):
        bundle = bundle_for_nodes([{"node_type": "CORE_SWITCH", "theme": "示例"}], limit=20)
        self.assertIn("NODE_CORE_SWITCH", bundle["required_rule_ids"])
        self.assertIn("NODE_HIGH_LOW_SWITCH", bundle["required_rule_ids"])
        self.assertGreater(bundle["matched_case_count"], 0)
        self.assertEqual(bundle["status"], "READY")

    def test_node_evidence_recall_covers_each_method_family(self):
        expected = {
            "DIVERGENCE_REPAIR": "REPAIR",
            "BREAKOUT": "BREAKOUT",
            "UNIQUENESS_START_COHORT": "UNIQUENESS",
            "CAPACITY_VALIDATION": "CAPACITY",
            "CORE_SWITCH": "CORE_SWITCH",
            "HIGH_LOW_SWITCH": "HIGH_LOW",
            "SECOND_WAVE": "SECOND_WAVE",
            "BOTTOM_REPAIR": "BOTTOM_REPAIR",
            "FIRST_ACTIVE_DIVERGENCE": "ACTIVE_DIVERGENCE",
        }
        for node_type, requirement in expected.items():
            with self.subTest(node_type=node_type):
                bundle = bundle_for_nodes([{
                    "node_id": f"NODE-{node_type}", "node_type": node_type,
                    "theme": "示例",
                }])
                self.assertIn(requirement, {
                    item["requirement"] for item in bundle["manifest"]})
                coverage = next(item for item in bundle["coverage"]
                                if item["requirement"] == requirement)
                self.assertTrue(coverage["rule_ids"])
                self.assertTrue(coverage["matched_case_hashes"])

    def test_audit_evidence_is_derived_from_actual_tasks_and_relations(self):
        stage_b = {"nodes": [{
            "node_id": "NODE-G8", "node_type": "UNIQUENESS_START_COHORT",
            "generator": "G8", "theme": "示例",
        }]}
        stage_c = {
            "path_plans": [{
                "path_kind": "ALTERNATIVE",
                "candidates": [{
                    "role": "容量核心", "role_status": "REPLACED",
                    "agency_event_model": {"relation_state": "ROLE_REPLACED"},
                }],
            }],
            "final_action_plan": {
                "backup_ref": {"path_kind": "ALTERNATIVE"},
                "no_action_conditions": ["结构失败则不行动"],
            },
        }
        tasks = {"task_candidates": [{
            "task_id": "TASK-G8", "task_type": "SAME_LEVEL_PROMOTION",
        }]}
        bundle = bundle_for_audit(stage_b, stage_c, tasks, {})
        requirements = {item["requirement"] for item in bundle["manifest"]}
        self.assertTrue({
            "UNIQUENESS", "ROLE", "AGENCY", "ROLE_REPLACEMENT",
            "EXIT", "ALTERNATIVE",
        }.issubset(requirements))
        self.assertGreater(bundle["matched_case_count"], 4)


if __name__ == "__main__":
    unittest.main()
