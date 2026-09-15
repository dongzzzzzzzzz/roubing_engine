from __future__ import annotations

import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

from roubing_engine.reasoning import eod_pipeline, prompts
from roubing_engine.candidates.generators import ensure_mainstream_generators
from roubing_engine.reasoning.runner import (
    AgentTask,
    build_codex_cmd,
    detect_skill_contamination,
    run as run_agent,
)
from roubing_engine.reasoning import regression
from roubing_engine.evaluation.fidelity import check_stage_b


def reasoned(value="fixture", status="APPLICABLE"):
    return {
        "status": status,
        "evidence_kind": "DATA_INSUFFICIENT" if status == "DATA_INSUFFICIENT" else "MODEL_INFERENCE",
        "value": value,
        "observed": ["fixture fact"],
        "inference": "fixture inference",
        "supporting_fact_ids": ["F-DIR-EXAMPLE"] if status == "APPLICABLE" else [],
        "counter_fact_ids": [],
        "rule_ids": ["DISC_NO_FIXED_SCORE"] if status == "APPLICABLE" else [],
        "unknowns": ["fixture gap"] if status == "DATA_INSUFFICIENT" else [],
    }


def lifecycle_contract():
    return {
        "first_candidate_date": reasoned("2026-09-08"),
        "current_day_index": reasoned(1),
        "stage_yesterday": reasoned(None, "DATA_INSUFFICIENT"),
        "stage_today": reasoned("LAUNCH_TEST"),
        "stage_change": reasoned("首日启动候选"),
        "pioneer_state": reasoned("首日先锋待验证"),
        "capacity_state": reasoned("容量未知", "DATA_INSUFFICIENT"),
        "back_row_feedback": reasoned("后排未知", "DATA_INSUFFICIENT"),
        "board_index_state": reasoned("板块指数未知", "DATA_INSUFFICIENT"),
        "buyer_feedback": reasoned("昨日买方反馈未知", "DATA_INSUFFICIENT"),
        "first_divergence_date": reasoned(None, "NOT_APPLICABLE"),
        "divergence_order": reasoned("NONE", "NOT_APPLICABLE"),
        "repair_history": reasoned([], "NOT_APPLICABLE"),
        "repair_quality": reasoned("NONE", "NOT_APPLICABLE"),
        "catalyst_state": {
            "catalyst_type": reasoned("UNKNOWN", "DATA_INSUFFICIENT"),
            "catalyst_stage": reasoned("NEW"),
            "first_seen_or_repeated": reasoned("首次出现待验证"),
            "keyword_only_stocks": reasoned([]),
            "capital_selected_stocks": reasoned(["A.SH"]),
            "reason_continuity": reasoned("待次日验证"),
            "next_day_buyer_premium": reasoned("未知", "DATA_INSUFFICIENT"),
            "post_divergence_repair": reasoned("未发生分歧", "NOT_APPLICABLE"),
        },
        "regulatory_constraints": reasoned([]),
        "upgrade_conditions": reasoned(["次日延续"]),
        "downgrade_conditions": reasoned(["次日不延续"]),
        "tomorrow_validation": reasoned(["验证延续"]),
        "mainstream_questions": {
            "startup_continuation_divergence": reasoned("UNKNOWN", "DATA_INSUFFICIENT"),
            "front_capacity_diffusion_layers": reasoned("UNKNOWN", "DATA_INSUFFICIENT"),
            "board_index_strength_or_breakout": reasoned("UNKNOWN", "DATA_INSUFFICIENT"),
            "major_divergence_core_capacity_repair": reasoned("UNKNOWN", "DATA_INSUFFICIENT"),
            "internal_takeover_after_core_constraint": reasoned("UNKNOWN", "DATA_INSUFFICIENT"),
        },
    }


def trace(step_id, status="APPLICABLE"):
    return {
        "step_id": step_id,
        "status": status,
        "fact_ids": ["F-DIR-EXAMPLE"] if status == "APPLICABLE" else [],
        "counter_fact_ids": [],
        "reason_code": step_id,
        "judgment": "fixture",
        "downstream_effect": ["fixture"],
        "forbidden_conclusions": [],
        "audit_status": "PASS",
    }


def stage_b():
    return {
        "as_of": "20260908 CLOSE",
        "environment": {
            "status": "DATA_INSUFFICIENT", "reasoning": ["首日账本只描述当日截面"],
            "supporting_fact_ids": ["F-DIR-EXAMPLE"], "counter_fact_ids": [],
            "rule_ids": ["ENV_ROTATION"],
            "migrated_from": None, "tomorrow_checks": ["检查"],
        },
        "direction_evaluations": [{
            "theme": "示例", "direction_fact_id": "F-DIR-EXAMPLE", "stage": "启动",
            **lifecycle_contract(),
            "market_relation": "LEADS", "path_status": "PRIMARY",
            "observed_facts": ["共同首板"], "inferences": ["方向待次日验证"],
            "supporting_fact_ids": ["F-DIR-EXAMPLE"], "counter_fact_ids": [],
            "rule_ids": ["NODE_UNIQUENESS"],
            "competitors": [], "data_gaps": [],
        }],
        "direction_comparisons": [],
        "primary_path": {
            "status": "SELECTED", "theme": "示例", "direction_fact_id": "F-DIR-EXAMPLE",
            "selection_logic": ["示例方向相对领先"], "supporting_fact_ids": ["F-DIR-EXAMPLE"],
            "counter_fact_ids": [], "competitor_themes": [],
            "rule_ids": ["DISC_NO_FIXED_SCORE"],
            "cancel_conditions": [],
        },
        "nodes": [{
            "node_id": "NODE-EXAMPLE-G8", "action_status": "ACTION_READY",
            "node_type": "UNIQUENESS", "anchor_date": "2026-09-07", "theme": "示例",
            "trigger_facts": ["共同首板、同日起步"], "trigger_fact_ids": ["F-DIR-EXAMPLE"],
            "method_reasoning": ["共同起步进入唯一性竞争"],
            "generator": "G8", "candidate_ids": [],
            "candidate_scope": {"event_statuses": ["limit_up"], "board_levels": [1],
                                "sub_directions": [], "candidate_ids": [],
                                "validation_ids": [], "scope_reason": "同日首板"},
            "rule_ids": ["NODE_UNIQUENESS", "G08_UNIQUENESS"],
            "confirm": ["确认"], "cancel": ["取消"],
        }],
        "data_gaps": [],
    }


def m1_result():
    result = dict(stage_b())
    result.pop("nodes", None)
    result["environment_hypotheses"] = [{
        "environment": name,
        "status": "APPLICABLE" if name == "ROTATION" else "NOT_APPLICABLE",
        "supporting_fact_ids": ["F-DIR-EXAMPLE"] if name == "ROTATION" else [],
        "counter_fact_ids": [],
        "unknowns": [],
        "downstream_effect": ["fixture"],
        "forbidden_conclusions": [],
    } for name in ("MAIN_TREND", "ROTATION", "DECLINE", "REGIME_SWITCH")]
    result["method_trace"] = [
        trace(step) for step in (
            "S1-INDEX-TREND", "S1-TOTAL_TURNOVER_SUPPORT",
            "S1-LARGE_CAP_BUYER_FEEDBACK", "S1-YESTERDAY_STRONG_FEEDBACK",
            "S1-PROFIT_EFFECT_SPREAD", "S1-OLD_NEW_TAKEOVER",
            "S1-HYPOTHESIS-MAIN_TREND", "S1-HYPOTHESIS-ROTATION",
            "S1-HYPOTHESIS-DECLINE", "S1-HYPOTHESIS-REGIME_SWITCH",
        )
    ]
    return result


def m2_result():
    node = dict(stage_b()["nodes"][0])
    node["node_questions"] = {
        "prior_state": "共同起步",
        "prior_resistance": "同起算日唯一性未确认",
        "changed_facts": ["共同首板、同日起步"],
        "benefited_function": "同起算日晋级者",
        "anchor_date": "2026-09-07",
        "natural_candidate_scope": "同日首板完整队列",
        "confirm": ["确认"],
        "cancel": ["取消"],
    }
    return {
        "as_of": "20260908 CLOSE",
        "generator_applicability": [{
            "generator": f"G{i}",
            "status": "APPLICABLE" if i == 8 else "NOT_APPLICABLE",
            "prior_state": "fixture",
            "prior_resistance": "fixture",
            "changed_facts": ["fixture"] if i == 8 else [],
            "benefited_function": "fixture",
            "anchor_date": "2026-09-07" if i == 8 else None,
            "natural_candidate_scope": "fixture",
            "confirm": ["确认"],
            "cancel": ["取消"],
            "fact_ids": ["F-DIR-EXAMPLE"] if i == 8 else [],
            "counter_fact_ids": [],
            "rule_ids": ["G08_UNIQUENESS"] if i == 8 else [],
        } for i in range(1, 13)],
        "nodes": [node],
        "method_trace": [trace(f"G{i}") for i in range(1, 13)],
        "data_gaps": [],
    }


def _legacy_stage_c_fixture():
    claim = {
        "status": "UNKNOWN", "statement": "无法确认",
        "evidence": [], "evidence_refs": [],
    }
    return {
        "as_of": "20260908 CLOSE",
        "execution_task": {
            "status": "SELECTED", "task_id": "TASK-EXAMPLE",
            "task_type": "SAME_LEVEL_PROMOTION", "theme": "示例",
            "missing_function": "同板级晋级者", "selection_logic": ["任务可比较"],
            "supporting_fact_ids": ["F-DIR-EXAMPLE"], "rejected_task_ids": [],
        },
        "action_competition_group": {
            "task_id": "TASK-EXAMPLE", "members": ["A.SH"],
            "validation_objects": [], "comparison_basis": ["同任务"],
            "resolved_out": [], "unresolved": [],
        },
        "pairwise_comparison": [],
        "action_plan": {
            "status": "SINGLE", "task_id": "TASK-EXAMPLE",
            "primary": {"thscode": "A.SH", "task_to_complete": "独立晋级",
                        "auction_conditions": ["相对同任务对象不弱"],
                        "open_conditions": ["开盘完成任务"],
                        "downgrade_conditions": ["需要开盘确认"],
                        "direct_fail_conditions": ["任务直接失败"]},
            "backup": None, "validation_objects": [],
            "switch_rule": "单对象，无备选切换",
            "no_action_conditions": ["对象未完成任务"],
        },
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
        "competition_groups": [{
            "group_id": "g", "generator": "G8", "anchor_date": "2026-09-07",
            "theme": "示例", "comparison_basis": ["同方向"], "members": ["A.SH"],
            "not_comparable_with": [],
            "leader_state": {
                "status": "UNRESOLVED", "thscode": None,
                "evidence": [], "evidence_refs": [],
            },
            "pairwise_relations": [], "next_confirmation": ["次日"],
            "coverage_status": "PARTIAL", "next_day_tasks": ["逐一验证"],
            "uniqueness_status": "UNRESOLVED",
        }],
        "candidates": [{
            "thscode": "A.SH", "name": "示例A", "theme": "示例", "node": "UNIQUENESS",
            "task_id": "TASK-EXAMPLE", "observed_function": "同板级晋级",
            "task_relation": "ACTION_COMPETITOR", "node_id": "NODE-EXAMPLE-G8",
            "generator": "G8", "anchor_date": "2026-09-07",
            "stock_start_date": "2026-09-07", "role": "UNKNOWN", "role_family": "UNKNOWN",
            "role_status": "CANDIDATE",
            "functional_role": {
                "role": "UNKNOWN", "role_status": "CANDIDATE",
                "entered_by_event": ["共同首板待验证"],
                "current_function": "同起算日候选，功能未确认",
                "must_complete_next": ["次日完成同组晋级"],
                "invalidated_by": ["次日竞争失败"],
                "previous_role": None,
                "possible_next_roles": ["ASSIST_OR_COMPANION", "FOLLOWER", "UNKNOWN"],
                "active_or_passive_relation": "UNKNOWN",
                "author_letter_label": "UNKNOWN",
            },
            "stock_expectation": {
                "current_role": "UNKNOWN",
                "today_state": "TURNOVER_LIMIT",
                "self_benchmark": "相对首板自身惯性验证",
                "peer_benchmark": "次日强于同组第二名",
                "environment_benchmark": "方向需继续增强",
                "auction_expectation": "竞价保持同任务主动关系",
                "open_expectation": "开盘承接不被同组反推",
                "board_response_expectation": "板块响应不能走弱",
                "role_task": "完成同板级晋级",
                "minimum_confirmation": "同组相对主动且方向不弱",
                "direct_cancel": "竞价即落后且方向无响应",
                "regulatory_constraint": "无可确认约束",
                "generation_order": [
                    "T_DAY_ROLE", "T_DAY_PERFORMANCE", "T_DAY_BOARD_STATE",
                    "SAME_GROUP_SECOND_PLACE", "CURRENT_REGULATION_AND_REMAINING_SPACE",
                ],
            },
            "capacity_tasks": {"price_progression": "未知", "pullback_recovery": "未知", "sector_leadership": "未知", "center_of_gravity": "未知", "replacement_state": "未确认"},
            "agency_event_model": {"reference": "同组", "event_sequence": ["未知"], "target_behavior": "未知", "data_sufficiency": "UNKNOWN", "conclusion": "UNKNOWN"},
            "letter_carrier": "UNKNOWN", "competition_group": "g", "competitors": [],
            "observed_state": ["事实"], "tomorrow_must_do": ["任务"],
            "acceptable_variants": [], "failure_signals": ["失败"],
            "cancel_if": ["取消"], "output_tier": "待验证候选",
            "evidence": ["F-STOCK-A"],
            "evidence_refs": [
                {"id": "F-STOCK-A", "evidence_kind": "OBSERVED_FACT",
                 "source_field": "candidate_pools.pool[].fact_id"},
                {"id": "G08_UNIQUENESS", "evidence_kind": "AUTHOR_INTERPRETATION",
                 "source_field": "rules.md"},
            ],
        }],
        "excluded_candidates": [],
        "unknowns": [],
    }


def stage_c1():
    return {
        "as_of": "20260908 CLOSE",
        "decision_order": ["方向关系", "节点前态", "缺失功能", "匹配任务"],
        "primary_task": {
            "path_kind": "PRIMARY", "status": "SELECTED",
            "task_id": "TASK-EXAMPLE", "task_type": "SAME_LEVEL_PROMOTION",
            "theme": "示例", "node_id": "NODE-EXAMPLE-G8",
            "missing_function": "同起算日晋级者", "selection_logic": ["G8节点需要唯一性晋级"],
            "supporting_fact_ids": ["F-DIR-EXAMPLE"],
            "rule_ids": ["G08_UNIQUENESS"], "rejected_task_ids": [],
        },
        "alternative_task": {
            "path_kind": "ALTERNATIVE", "status": "NONE",
            "task_id": None, "task_type": None, "theme": None, "node_id": None,
            "missing_function": "无独立替代节点", "selection_logic": ["没有替代动作任务"],
            "supporting_fact_ids": [], "rule_ids": ["DISC_NO_FIXED_SCORE"],
            "rejected_task_ids": [],
        },
        "no_action_conditions": ["主路径任务未完成"], "unknowns": [],
    }


def stage_c():
    legacy = _legacy_stage_c_fixture()
    selection = stage_c1()
    legacy["execution_task"] = {
        key: value for key, value in selection["primary_task"].items()
        if key not in {"path_kind", "node_id"}
    }
    legacy["candidates"][0]["agency_event_model"].update({
        "reference_task_id": "TASK-EXAMPLE",
        "relation_state": "INDEPENDENCE_NOT_CONFIRMED",
        "role_replacement_basis": [],
    })
    legacy["action_plan"]["primary"].update({
        "task_id": "TASK-EXAMPLE", "path_kind": "PRIMARY",
    })
    legacy["candidates"][0]["evidence"] = ["F-STOCK-A", "G08_UNIQUENESS"]
    legacy["competition_groups"][0]["rule_ids"] = ["G08_UNIQUENESS"]
    legacy["action_plan"]["rule_ids"] = ["G08_UNIQUENESS"]
    path_analysis = dict(legacy["paths"]["primary"])
    path_analysis["trigger"] = []
    return {
        "as_of": legacy["as_of"],
        "task_selection": {
            "primary_task": selection["primary_task"],
            "alternative_task": selection["alternative_task"],
            "no_action_conditions": selection["no_action_conditions"],
        },
        "path_plans": [{
            "path_kind": "PRIMARY", "execution_task": legacy["execution_task"],
            "path_analysis": path_analysis,
            "competition_group": legacy["competition_groups"][0],
            "pairwise_comparison": legacy["pairwise_comparison"],
            "action_plan": legacy["action_plan"], "candidates": legacy["candidates"],
            "excluded_candidates": [], "unknowns": [],
        }],
        "final_action_plan": {
            "status": "SINGLE",
            "primary_ref": {"path_kind": "PRIMARY", "task_id": "TASK-EXAMPLE",
                            "thscode": "A.SH"},
            "backup_ref": None, "switch_rule": "单对象，无备选",
            "no_action_conditions": ["主对象未完成任务"],
            "rule_ids": ["G08_UNIQUENESS"],
        },
        "unknowns": [],
    }


class PipelineGateTests(unittest.TestCase):
    def test_c1_fact_package_contains_no_stock_rows_or_codes(self):
        facts = {
            "as_of": "20260302 CLOSE", "trade_date": "20260302",
            "fact_catalog": {
                "F-DIR": {"scope": "DIRECTION"},
                "F-STOCK": {"scope": "STOCK", "thscode": "A.SH"},
            },
            "stage_b_observation_universe": [{"thscode": "A.SH", "name": "股票A"}],
        }
        packaged = eod_pipeline._task_selection_facts(facts)
        self.assertNotIn("stage_b_observation_universe", packaged)
        self.assertNotIn("F-STOCK", packaged["fact_catalog"])
        self.assertNotIn("A.SH", str(packaged))

    def test_non_adjacent_previous_state_is_rejected(self):
        from unittest.mock import patch
        from roubing_engine.reasoning import eod_pipeline
        state = {
            "trade_date": "20260105",
            "environment": {"status": "DATA_INSUFFICIENT"},
            "stage_b_provenance": {"generated_at": "2026-09-14T00:00:00Z"},
            "stage_c_provenance": {"generated_at": "2026-09-14T00:00:01Z"},
        }
        with patch("roubing_engine.state.ledger.load_prev_ledger", return_value=state):
            packaged = eod_pipeline._load_prev_state("20260302")
        self.assertEqual(packaged, {})

    def test_adjacent_previous_state_strips_runtime_provenance(self):
        from unittest.mock import patch
        from roubing_engine.reasoning import eod_pipeline
        state = {
            "trade_date": "20260227",
            "environment": {"status": "DATA_INSUFFICIENT"},
            "stage_b_provenance": {"generated_at": "2026-09-14T00:00:00Z"},
            "stage_c_provenance": {"generated_at": "2026-09-14T00:00:01Z"},
        }
        with patch("roubing_engine.state.ledger.load_prev_ledger", return_value=state):
            packaged = eod_pipeline._load_prev_state("20260302")
        self.assertEqual(packaged["trade_date"], "20260227")
        self.assertNotIn("stage_b_provenance", packaged)
        self.assertNotIn("stage_c_provenance", packaged)

    def test_ledger_persists_formal_role_status(self):
        import json
        from roubing_engine.state import ledger
        plan = stage_c()
        candidate = plan["path_plans"][0]["candidates"][0]
        candidate["role_status"] = "CANDIDATE"
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(ledger, "LEDGER_DIR", Path(tmp)), \
                patch.object(ledger, "load_prev_ledger", return_value={}):
            path = ledger.save_ledger("20260908", stage_b(), plan)
            saved = json.loads(path.read_text(encoding="utf-8"))
        role = saved["roles"][0]
        self.assertEqual(role["role_status"], "CANDIDATE")
        self.assertEqual(role["new_role_status"], "CANDIDATE")

    def _first_day_stage_b_facts(self):
        return {
            "previous_state_summary": {"available": False},
            "previous_buyer_feedback": {"available": False},
            "path_comparison_contract": {"cross_section_comparison_available": True},
            "direction_state_facts": [
                {"theme": "方向甲", "fact_id": "F-DIR-A"},
                {"theme": "方向乙", "fact_id": "F-DIR-B"},
            ],
            "fact_catalog": {
                "F-ENV": {"scope": "ENVIRONMENT"},
                "F-DIR-A": {"scope": "DIRECTION", "theme": "方向甲"},
                "F-DIR-B": {"scope": "DIRECTION", "theme": "方向乙"},
            },
            "stage_b_observation_universe": [],
        }

    def _first_day_stage_b_result(self):
        return {
            "environment": {
                "status": "DATA_INSUFFICIENT", "migrated_from": None,
                "supporting_fact_ids": ["F-ENV"], "counter_fact_ids": [],
                "rule_ids": ["ENV_ROTATION"],
            },
            "direction_evaluations": [
                {"theme": "方向甲", "direction_fact_id": "F-DIR-A",
                 **lifecycle_contract(),
                 "path_status": "PRIMARY", "supporting_fact_ids": ["F-DIR-A"],
                 "counter_fact_ids": [], "rule_ids": ["DISC_NO_FIXED_SCORE"]},
                {"theme": "方向乙", "direction_fact_id": "F-DIR-B",
                 **lifecycle_contract(),
                 "path_status": "COMPETITOR", "supporting_fact_ids": ["F-DIR-B"],
                 "counter_fact_ids": [], "rule_ids": ["DISC_NO_FIXED_SCORE"]},
            ],
            "direction_comparisons": [{
                "left_theme": "方向甲", "right_theme": "方向乙",
                "dimensions": ["梯队完整性", "昨日买方反馈"],
                "relation": "LEFT_DOMINATES", "reasoning": ["方向甲多维领先"],
                "supporting_fact_ids": ["F-DIR-A", "F-DIR-B"],
                "counter_fact_ids": [], "rule_ids": ["DISC_NO_FIXED_SCORE"],
            }],
            "primary_path": {
                "status": "SELECTED", "theme": "方向甲",
                "direction_fact_id": "F-DIR-A",
                "supporting_fact_ids": ["F-DIR-A"], "counter_fact_ids": [],
                "rule_ids": ["DISC_NO_FIXED_SCORE"],
            },
            "nodes": [],
        }

    def test_first_day_environment_must_not_invent_rotation(self):
        facts = self._first_day_stage_b_facts()
        result = self._first_day_stage_b_result()
        result["environment"]["status"] = "ROTATION"
        problems = check_stage_b(result, facts)
        self.assertTrue(any("必须降级为 DATA_INSUFFICIENT" in item for item in problems))

    def test_optional_history_gaps_cannot_block_available_cross_section(self):
        facts = self._first_day_stage_b_facts()
        result = self._first_day_stage_b_result()
        result["direction_evaluations"][0]["path_status"] = "BLOCKED_DATA"
        result["primary_path"].update({
            "status": "BLOCKED_DATA", "theme": None, "direction_fact_id": None,
        })
        problems = check_stage_b(result, facts)
        self.assertTrue(any("最低横向比较条件" in item for item in problems))

    def test_first_day_can_select_conditional_priority_path(self):
        self.assertEqual(check_stage_b(
            self._first_day_stage_b_result(), self._first_day_stage_b_facts()), [])

    def test_incomparable_directions_cannot_force_primary_path(self):
        facts = self._first_day_stage_b_facts()
        result = self._first_day_stage_b_result()
        result["direction_comparisons"][0]["relation"] = "INCOMPARABLE"
        problems = check_stage_b(result, facts)
        self.assertTrue(any("不得强行 SELECTED" in item for item in problems))

    def test_height_cannot_be_declared_irreversible_priority(self):
        facts = self._first_day_stage_b_facts()
        result = self._first_day_stage_b_result()
        result["primary_path"]["selection_logic"] = [
            "三板先赢，因此后续不能反转",
        ]
        problems = check_stage_b(result, facts)
        self.assertTrue(any("不可逆优先级" in item for item in problems))

    def test_action_node_requires_generator_and_scope(self):
        facts = self._first_day_stage_b_facts()
        result = self._first_day_stage_b_result()
        result["nodes"] = [{
            "node_id": "NODE-BAD", "node_type": "OBS", "action_status": "ACTION_READY",
            "anchor_date": "2026-01-05", "theme": "方向甲", "generator": None,
            "trigger_facts": ["事实"], "trigger_fact_ids": ["F-DIR-A"],
            "method_reasoning": ["错误动作节点"], "candidate_ids": [],
            "candidate_scope": {"event_statuses": [], "board_levels": [],
                                "sub_directions": [], "candidate_ids": [],
                                "validation_ids": [], "scope_reason": "空范围"},
            "rule_ids": ["NODE_UNIQUENESS"], "confirm": [], "cancel": [],
        }]
        problems = check_stage_b(result, facts)
        self.assertTrue(any("ACTION_READY 必须有 generator" in item for item in problems))
        self.assertTrue(any("缺少可执行 candidate_scope" in item for item in problems))

    def test_observation_node_cannot_hide_generator(self):
        facts = self._first_day_stage_b_facts()
        result = self._first_day_stage_b_result()
        result["nodes"] = [{
            "node_id": "NODE-BAD", "node_type": "UNIQUENESS",
            "action_status": "OBSERVATION_ONLY", "anchor_date": "2026-01-05",
            "theme": "方向甲", "generator": "G8", "trigger_facts": ["共同首板"],
            "trigger_fact_ids": ["F-DIR-A"], "method_reasoning": ["仅观察"],
            "candidate_ids": [],
            "candidate_scope": {"event_statuses": ["limit_up"], "board_levels": [1],
                                "sub_directions": [], "candidate_ids": [],
                                "validation_ids": [], "scope_reason": "同日首板"},
            "rule_ids": ["G08_UNIQUENESS"], "confirm": [], "cancel": [],
        }]
        problems = check_stage_b(result, facts)
        self.assertTrue(any("非 ACTION_READY 节点不得保留 generator" in item
                            for item in problems))

    def test_same_day_g8_cannot_be_action_ready(self):
        facts = self._first_day_stage_b_facts()
        result = self._first_day_stage_b_result()
        result["as_of"] = "20260105 CLOSE"
        result["nodes"] = [{
            "node_id": "NODE-SAME-DAY-G8", "node_type": "UNIQUENESS",
            "action_status": "ACTION_READY", "anchor_date": "2026-01-05",
            "theme": "方向甲", "generator": "G8",
            "trigger_facts": ["共同首板、同日起步"],
            "trigger_fact_ids": ["F-DIR-A"],
            "method_reasoning": ["首日只建立竞争观察组"], "candidate_ids": [],
            "candidate_scope": {"event_statuses": ["limit_up"], "board_levels": [1],
                                "sub_directions": [], "candidate_ids": [],
                                "validation_ids": [], "scope_reason": "同日首板"},
            "rule_ids": ["NODE_UNIQUENESS", "G08_UNIQUENESS"],
            "confirm": [], "cancel": [],
        }]
        problems = check_stage_b(result, facts)
        self.assertTrue(any("G8 起算日当天" in item for item in problems))

    def test_non_action_generator_is_transparently_canonicalized_to_null(self):
        result = {"nodes": [{
            "node_id": "NODE-OBS", "action_status": "OBSERVATION_ONLY",
            "generator": "G8", "candidate_scope": {"candidate_ids": ["A.SH"]},
        }, {
            "node_id": "NODE-ACT", "action_status": "ACTION_READY",
            "generator": "G8", "candidate_scope": {"candidate_ids": ["B.SH"]},
        }]}
        canonical, changes = eod_pipeline._canonicalize_stage_b_nodes(result)
        self.assertEqual(result["nodes"][0]["generator"], "G8")
        self.assertIsNone(canonical["nodes"][0]["generator"])
        self.assertEqual(canonical["nodes"][1]["generator"], "G8")
        self.assertEqual(changes[0]["path"], "nodes[0].generator")

    def test_stage_b_prompt_distinguishes_blocked_none_and_selected(self):
        from roubing_engine.reasoning import prompts
        prompt_text = prompts.stage_b_instructions()
        self.assertIn("盘后相对优先路径候选", prompt_text)
        self.assertIn("当日比较字段齐全但方向无法拉开差异时用 NONE", prompt_text)
        self.assertIn("不得仅因此写BLOCKED_DATA", prompt_text)

    def test_stage_b_prompt_forbids_unavailable_generator_citations(self):
        from roubing_engine.reasoning import prompts
        prompt_text = prompts.stage_b_instructions()
        self.assertIn("若 [G06_DIVERGENCE_REPAIR] 不在 rules.md", prompt_text.replace("\n", " "))
        self.assertIn("不得在 nodes、reasoning 或 data_gaps 中引用", prompt_text.replace("\n", " "))

    def test_stage_c_treats_open_0935_as_snapshot_not_fixed_threshold(self):
        from roubing_engine.reasoning import prompts
        prompt_text = prompts.stage_c_instructions()
        self.assertIn("不是作者规定的统一“五分钟成败阈值”", prompt_text)
        self.assertIn("不得仅因五分钟已到", prompt_text)

    def test_stage_b_model_failure_invalidates_old_approved_status(self):
        facts = {
            "available": True, "as_of": "20260908 CLOSE", "trade_date": "20260908",
            "themes": [], "direction_state_facts": [], "fact_catalog": {},
            "stage_b_observation_universe": [],
        }
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(eod_pipeline, "RUNS", Path(tmp)), \
             patch.object(eod_pipeline, "build_factpack", return_value=facts), \
             patch.object(eod_pipeline.runner, "run", side_effect=RuntimeError("offline")):
            run_dir = Path(tmp) / "20260908"
            run_dir.mkdir(parents=True)
            (run_dir / "run_status.json").write_text('{"status":"APPROVED"}')
            result = eod_pipeline.run_pipeline("20260908", backend="codex", with_daily=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "BLOCKED_MODEL_M1")

    def test_new_run_archives_downstream_stale_outputs_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            generated = [
                "stage_b/output/result.json", "stage_c1/output/result.json",
                "stage_c2/output/result.json", "audit/output/result.json",
                "stage_b_result.draft.json", "stage_c_result.json",
                "executable_plan.json", "battlecard_codex.md",
            ]
            for relative in generated:
                path = run_dir / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("old", encoding="utf-8")
            market_data = run_dir / "warehouse.parquet"
            market_data.write_text("keep", encoding="utf-8")
            removed = eod_pipeline._invalidate_previous_run_outputs(
                run_dir, keep_stage_b_draft=True)
            self.assertTrue((run_dir / "stage_b_result.draft.json").exists())
            self.assertTrue(market_data.exists())
            self.assertFalse((run_dir / "stage_c2/output/result.json").exists())
            self.assertFalse((run_dir / "executable_plan.json").exists())
            self.assertIn("stage_c2/output/result.json", removed)
            archived = list((run_dir / "_superseded").glob("*/executable_plan.json"))
            self.assertEqual(len(archived), 1)
            self.assertEqual(archived[0].read_text(encoding="utf-8"), "old")

    def test_single_day_regression_stops_after_failed_eod(self):
        with patch.object(regression, "run_pipeline", return_value={"ok": False}) as eod, \
             patch.object(regression, "run_validation") as validation:
            result = regression.run_single_day("20260105", "2026-01-06")
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "EOD")
        eod.assert_called_once()
        validation.assert_not_called()

    def test_single_day_regression_runs_both_snapshots_in_order(self):
        with patch.object(regression, "run_pipeline", return_value={"ok": True}), \
             patch.object(regression, "run_validation", side_effect=[
                 {"ok": True, "snapshot": "AUCTION_0925"},
                 {"ok": True, "snapshot": "OPEN_0935"},
             ]) as validation:
            result = regression.run_single_day("20260105", "2026-01-06")
        self.assertTrue(result["ok"])
        self.assertEqual([call.kwargs["snapshot"] for call in validation.call_args_list],
                         ["AUCTION_0925", "OPEN_0935"])

    def test_external_skill_markers_are_detected(self):
        self.assertEqual(detect_skill_contamination("loaded serenity-skill"), ["serenity-skill"])
        self.assertEqual(detect_skill_contamination("normal model output"), [])

    def test_runner_uses_isolated_codex_home_and_saves_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "task"
            task_dir.mkdir()
            (task_dir / "output").mkdir()
            (task_dir / "contamination.json").write_text('{"status":"CONTAMINATED"}')
            source_home = root / "source-codex-home"
            source_home.mkdir()
            (source_home / "auth.json").write_text('{"OPENAI_API_KEY":"test-only"}')
            (source_home / "config.toml").write_text(
                'model_provider = "custom"\n'
                'model = "test-model"\n'
                'model_reasoning_effort = "high"\n'
                'notify = ["should-not-run"]\n\n'
                '[model_providers.custom]\n'
                'name = "Test Proxy"\n'
                'base_url = "http://proxy.invalid/v1"\n'
                'wire_api = "responses"\n'
                'requires_openai_auth = true\n\n'
                '[mcp_servers.bad]\ncommand = "should-not-run"\n\n'
                '[plugins.bad]\nenabled = true\n'
            )
            isolated_home = None
            def fake_run_child(cmd, *, cwd, timeout, env, stdout_path,
                               stderr_path, result_path):
                nonlocal isolated_home
                self.assertTrue(Path(env.get("CODEX_HOME", "")).name.startswith("roubing-codex-home-"))
                isolated_home = Path(env["CODEX_HOME"])
                config = (isolated_home / "config.toml").read_text()
                self.assertIn('model_provider = "custom"', config)
                self.assertIn('model = "test-model"', config)
                self.assertIn("[model_providers.\"custom\"]", config)
                self.assertIn('base_url = "http://proxy.invalid/v1"', config)
                self.assertNotIn("[plugins", config)
                self.assertNotIn("[marketplaces", config)
                self.assertNotIn("[mcp_servers", config)
                self.assertNotIn("notify", config)
                self.assertFalse((isolated_home / "skills").exists())
                self.assertTrue((isolated_home / "auth.json").is_symlink())
                result_path.write_text('{"ok": true}')
                stdout_path.write_text("stdout")
                stderr_path.write_text("stderr")
                return 0, {"ok": True}, False
            with patch.dict(os.environ, {"ROUBING_CODEX_SOURCE_HOME": str(source_home)}), \
                 patch("roubing_engine.reasoning.runner._run_child", side_effect=fake_run_child):
                result = run_agent(AgentTask(task_dir, "prompt"), backend="codex")
            self.assertEqual(result["ok"], True)
            self.assertIsNotNone(isolated_home)
            self.assertFalse(isolated_home.exists())
            self.assertFalse((task_dir / "contamination.json").exists())
            self.assertTrue((task_dir / "stdout.log").exists())
            self.assertTrue((task_dir / "stderr.log").exists())

    def test_execution_config_rejects_missing_selected_custom_provider(self):
        from roubing_engine.reasoning.runner import _execution_config
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            (source / "config.toml").write_text('model_provider = "missing"\n')
            with self.assertRaisesRegex(RuntimeError, "no matching model_providers table"):
                _execution_config(source)

    def test_execution_config_allows_isolated_model_override(self):
        from roubing_engine.reasoning.runner import _execution_config
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            (source / "config.toml").write_text(
                'model_provider = "custom"\nmodel = "global-model"\n'
                '[model_providers.custom]\nbase_url = "http://proxy.invalid/v1"\n'
            )
            with patch.dict(os.environ, {"ROUBING_CODEX_MODEL": "regression-model"}):
                config = _execution_config(source)
            self.assertIn('model = "regression-model"', config)
            self.assertNotIn('model = "global-model"', config)
            self.assertIn('base_url = "http://proxy.invalid/v1"', config)

    def test_codex_command_disables_external_extension_surfaces(self):
        cmd = build_codex_cmd(AgentTask(Path("/tmp/task"), "prompt"))
        joined = " ".join(cmd)
        self.assertIn("--ephemeral", cmd)
        self.assertIn("--ignore-rules", cmd)
        for feature in ("plugins", "remote_plugin", "recommended_plugins", "apps", "skill_search"):
            self.assertIn(f"--disable {feature}", joined)

    def test_established_mainstream_without_method_node_stays_observation_only(self):
        stage = {
            "mainstream_directions": [{"theme": "商业航天", "stage": "延续",
                                       "supporting": ["梯队"], "counter": ["断层"]}],
            "nodes": [],
        }
        repaired = ensure_mainstream_generators(stage, "2026-01-05")
        self.assertEqual(repaired["nodes"], [])
        self.assertEqual(stage["nodes"], [])

    def test_starting_mainstream_without_explicit_node_stays_observation_only(self):
        stage = {
            "mainstream_directions": [{"theme": "人脑工程", "stage": "热点候选",
                                       "supporting": ["共同首板"], "counter": []}],
            "nodes": [],
        }
        repaired = ensure_mainstream_generators(stage, "2026-01-05")
        self.assertEqual(repaired["nodes"], [])

    def test_mixed_ladder_hotspot_does_not_get_g8_cohort(self):
        stage = {
            "mainstream_directions": [{"theme": "AI智能体", "stage": "热点候选",
                                       "supporting": ["3板、2板、首板混合梯队"], "counter": []}],
            "nodes": [],
        }
        repaired = ensure_mainstream_generators(stage, "2026-01-05")
        self.assertEqual(repaired["nodes"], [])

    def test_legacy_pool_builder_cannot_bypass_task_resolver(self):
        from roubing_engine.candidates.generators import build_pools_from_nodes
        with self.assertRaisesRegex(RuntimeError, "task_resolver"):
            build_pools_from_nodes([{"generator": "G8"}], "2026-01-05")

    def test_production_pipeline_uses_only_task_resolver_candidate_entry(self):
        source = Path(eod_pipeline.__file__).read_text(encoding="utf-8")
        self.assertIn("reasoning.task_resolver", source)
        self.assertNotIn("candidates.generators", source)
        self.assertNotIn("ensure_mainstream_generators", source)

    def test_legacy_stage_c_prompt_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "legacy Stage C prompt is retired"):
            prompts._legacy_stage_c_instructions()

    def test_failed_audit_never_persists_official_plan(self):
        facts = {
            "available": True, "as_of": "20260908 CLOSE", "trade_date": "20260908",
            "themes": [],
            "direction_state_facts": [{"theme": "示例", "fact_id": "F-DIR-EXAMPLE"}],
            "fact_catalog": {
                "F-DIR-EXAMPLE": {"scope": "DIRECTION", "theme": "示例"},
                "F-STOCK-A": {"scope": "STOCK", "thscode": "A.SH"},
            },
            "stage_b_observation_universe": [{
                "thscode": "A.SH", "name": "示例A", "theme": "示例",
                "fact_id": "F-STOCK-A", "direction_fact_id": "F-DIR-EXAMPLE",
            }],
        }
        pools = [{
            "task_id": "TASK-EXAMPLE", "task_type": "SAME_LEVEL_PROMOTION",
            "task_name": "同板级晋级", "anchor_date": "2026-09-07", "theme": "示例",
            "node_id": "NODE-EXAMPLE-G8", "node_action_status": "ACTION_READY",
            "path_kind": "PRIMARY",
            "method_generators": ["G8"], "required_function": "同板级晋级",
            "required_rule_ids": ["G08_UNIQUENESS"],
            "status": "ACTION_READY", "pool": [{"thscode": "A.SH", "name": "示例A",
                                               "theme": "示例", "limit_time": None,
                                               "fact_id": "F-STOCK-A",
                                               "required_anchor_date": "2026-09-07",
                                               "required_node_id": "NODE-EXAMPLE-G8",
                                               "required_stock_start_date": "2026-09-07",
                                               "previous_role_task": {"available": False}}],
            "pool_size": 1, "validation_pool": [], "validation_pool_size": 0,
            "data_blocks": [],
        }]
        audit = {"verdict": "NEEDS_REVISION", "violations": ["反方未解决"],
                 "counter_arguments": ["可能是一日游"]}
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(eod_pipeline, "RUNS", Path(tmp)), \
             patch.object(eod_pipeline, "build_factpack", return_value=facts), \
             patch("roubing_engine.reasoning.task_resolver.resolve", return_value={
                 "as_of": "20260908 CLOSE", "status": "ACTION_READY",
                 "no_action_rule_ids": ["DISC_NO_FIXED_SCORE"],
                 "task_candidates": [{
                     "task_id": "TASK-EXAMPLE", "task_type": "SAME_LEVEL_PROMOTION",
                     "theme": "示例", "direction_fact_id": "F-DIR-EXAMPLE",
                     "status": "ACTION_READY", "path_kind": "PRIMARY",
                     "node_id": "NODE-EXAMPLE-G8", "node_type": "UNIQUENESS",
                     "node_action_status": "ACTION_READY", "anchor_date": "2026-09-07",
                     "required_function": "同板级晋级",
                     "required_rule_ids": ["G08_UNIQUENESS"],
                     "method_generators": ["G8"], "scope_logic": ["同任务"],
                     "completion_signals": ["完成"], "failure_signals": ["失败"],
                     "data_gaps": [],
                     "eligibility_fact_ids": ["F-DIR-EXAMPLE", "F-STOCK-A"],
                 }],
             }), \
             patch("roubing_engine.reasoning.task_resolver.build_task_pools",
                   return_value=pools), \
             patch.object(eod_pipeline.runner, "run", side_effect=[
                 m1_result(), m2_result(), stage_c1(), stage_c(), audit]):
            result = eod_pipeline.run_pipeline("20260908", backend="codex", with_daily=False)
            run_dir = Path(tmp) / "20260908"
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "BLOCKED_AUDIT")
            audit_rules = (run_dir / "audit" / "rules.md").read_text()
            audit_evidence = (run_dir / "audit" / "audit_evidence_coverage.md").read_text()
            self.assertIn("# M1 环境与方向规则", audit_rules)
            self.assertIn("# M3 角色竞争与计划规则", audit_rules)
            self.assertIn("# 审计纪律规则", audit_rules)
            self.assertIn("命中案例数", audit_evidence)
            self.assertNotIn("_provenance", (run_dir / "stage_c1" / "stage_b.json").read_text())
            self.assertNotIn("generated_at", (run_dir / "stage_c2" / "stage_b.json").read_text())
            self.assertNotIn("_provenance", (run_dir / "stage_c2" / "c1_decision.json").read_text())
            self.assertNotIn("generated_at", (run_dir / "audit" / "stage_c.json").read_text())
            self.assertFalse((run_dir / "stage_b" / "original_posts.md").exists())
            self.assertFalse((run_dir / "stage_c2" / "original_posts.md").exists())
            self.assertTrue((run_dir / "stage_c_result.draft.json").exists())
            self.assertFalse((run_dir / "stage_c_result.json").exists())
            self.assertFalse((run_dir / "battlecard_codex.md").exists())


if __name__ == "__main__":
    unittest.main()
