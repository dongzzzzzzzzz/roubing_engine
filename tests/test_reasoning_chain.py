from __future__ import annotations

import unittest
from pathlib import Path

from roubing_engine.reasoning.day_factpack import build as build_factpack
from roubing_engine.reasoning.task_resolver import (
    build_task_pools, resolve, select_task_pools, summarize_tasks,
)
from roubing_engine.reasoning.plan_compiler import compile_plan
from roubing_engine.evaluation.fidelity import check_role_relation, check_task_selection


def selected_stage_b(facts: dict, theme: str, *, action_node: dict | None = None,
                     competitor_theme: str | None = None) -> dict:
    direction = next(item for item in facts["direction_state_facts"]
                     if item["theme"] == theme)
    evaluations = [{
        "theme": theme, "direction_fact_id": direction["fact_id"],
        "path_status": "PRIMARY",
    }]
    if competitor_theme:
        competitor = next(item for item in facts["direction_state_facts"]
                          if item["theme"] == competitor_theme)
        evaluations.append({
            "theme": competitor_theme, "direction_fact_id": competitor["fact_id"],
            "path_status": "COMPETITOR",
        })
    node = action_node or {
        "node_id": "NODE-OBS", "node_type": "DIRECTION_OBSERVATION_ONLY",
        "action_status": "OBSERVATION_ONLY", "theme": theme,
        "anchor_date": "2026-01-05", "generator": None,
        "candidate_scope": {
            "event_statuses": [], "board_levels": [], "sub_directions": [],
            "candidate_ids": [], "validation_ids": [],
            "scope_reason": "未形成合法动作节点",
        },
        "candidate_ids": [], "method_reasoning": ["只观察"], "rule_ids": [],
    }
    return {
        "as_of": facts["as_of"],
        "primary_path": {
            "status": "SELECTED", "theme": theme,
            "direction_fact_id": direction["fact_id"],
        },
        "direction_evaluations": evaluations,
        "nodes": [node],
    }


class TaskResolverTests(unittest.TestCase):
    def test_no_primary_path_produces_no_stock_tasks(self):
        result = resolve({"as_of": "20260105 CLOSE", "primary_path": {
            "status": "NONE", "theme": None, "direction_fact_id": None,
            "rule_ids": ["DISC_NO_FIXED_SCORE"],
        }}, {"stage_b_observation_universe": []})
        self.assertEqual(result["status"], "NO_PRIMARY_PATH")
        self.assertEqual(result["task_candidates"], [])
        self.assertEqual(result["no_action_rule_ids"], ["DISC_NO_FIXED_SCORE"])

    def test_observation_node_cannot_be_turned_into_board_tasks(self):
        facts = build_factpack("20260105", with_index=False)
        bundle = resolve(selected_stage_b(facts, "商业航天"), facts)
        self.assertEqual(bundle["status"], "NO_ACTION_TASK")
        self.assertEqual(bundle["task_candidates"], [])
        self.assertEqual(bundle["observed_nodes"][0]["action_status"],
                         "OBSERVATION_ONLY")

    def test_action_node_opens_only_its_frozen_same_task_scope(self):
        facts = build_factpack("20260105", with_index=False)
        node = {
            "node_id": "NODE-SAT-G8", "node_type": "UNIQUENESS_SAME_LEVEL",
            "action_status": "ACTION_READY", "theme": "商业航天",
            "anchor_date": "2025-12-31", "generator": "G8",
            "candidate_scope": {
                "event_statuses": ["limit_up"], "board_levels": [2],
                "sub_directions": ["卫星导航"], "candidate_ids": [],
                "validation_ids": ["002413.SZ"],
                "scope_reason": "同日起步、同卫星导航分支、同为二板",
            },
            "candidate_ids": [], "method_reasoning": ["同任务二进三竞争"],
            "rule_ids": ["G08_UNIQUENESS"],
        }
        bundle = resolve(selected_stage_b(facts, "商业航天", action_node=node), facts)
        target = bundle["task_candidates"][0]
        self.assertEqual(set(target["validation_ids"]), {"002413.SZ"})
        self.assertEqual(target["anchor_date"], "2025-12-31")
        self.assertEqual(target["node_id"], "NODE-SAT-G8")
        self.assertEqual(target["path_kind"], "PRIMARY")
        self.assertEqual(target["status"], "ACTION_READY")
        self.assertEqual(set(target["candidate_ids"]), {"002151.SZ", "600498.SH"})
        self.assertEqual(target["validation_anchor_dates"]["002413.SZ"],
                         "2025-12-29")
        self.assertEqual(set(target["role_assignment_contract"]["required_unknown_codes"]),
                         {"002151.SZ", "600498.SH", "002413.SZ"})
        self.assertIn("G08_UNIQUENESS", target["required_rule_ids"])
        self.assertIn("DISC_NO_HINDSIGHT", target["required_rule_ids"])
        self.assertEqual(target["pair_preference_contract"]["status"],
                         "SYMMETRIC_UNRESOLVED")
        self.assertIsNone(target["pair_preference_contract"]["primary_hint"])
        self.assertIsNone(target["pair_preference_contract"]["backup_hint"])
        self.assertIn("INDEPENDENCE_AND_EVENT_ORDER",
                      target["pair_preference_contract"]["allowed_evidence_families"])

    def test_task_pool_contains_only_frozen_scope(self):
        facts = build_factpack("20260105", with_index=False)
        node = {
            "node_id": "NODE-SAT-G8", "node_type": "UNIQUENESS_SAME_LEVEL",
            "action_status": "ACTION_READY", "theme": "商业航天",
            "anchor_date": "2025-12-31", "generator": "G8",
            "candidate_scope": {
                "event_statuses": ["limit_up"], "board_levels": [2],
                "sub_directions": ["卫星导航"], "candidate_ids": [],
                "validation_ids": ["002413.SZ"], "scope_reason": "冻结范围",
            },
            "candidate_ids": [], "method_reasoning": ["同任务竞争"],
            "rule_ids": ["G08_UNIQUENESS"],
        }
        bundle = resolve(selected_stage_b(facts, "商业航天", action_node=node), facts)
        pools = build_task_pools(bundle, facts)
        task = next(item for item in bundle["task_candidates"]
                    if set(item["candidate_ids"]) == {"002151.SZ", "600498.SH"})
        pool = next(item for item in pools if item["task_id"] == task["task_id"])
        self.assertEqual({item["thscode"] for item in pool["pool"]},
                         {"002151.SZ", "600498.SH"})
        self.assertEqual({item["thscode"] for item in pool["validation_pool"]},
                         {"002413.SZ"})
        self.assertEqual(pool["status"], "ACTION_READY")

    def test_competitor_direction_requires_its_own_action_node(self):
        facts = build_factpack("20260105", with_index=False)
        competitor = next(item for item in facts["direction_state_facts"]
                          if item["theme"] == "人脑工程")
        stage = selected_stage_b(
            facts, "商业航天", competitor_theme="人脑工程")
        stage["nodes"].append({
            "node_id": "NODE-BRAIN-G8", "node_type": "UNIQUENESS_START_COHORT",
            "action_status": "ACTION_READY", "theme": "人脑工程",
            "anchor_date": "2026-01-05", "generator": "G8",
            "candidate_scope": {
                "event_statuses": ["limit_up"], "board_levels": [1],
                "sub_directions": [], "candidate_ids": [], "validation_ids": [],
                "scope_reason": "同日首板完整队列",
            },
            "candidate_ids": [], "method_reasoning": ["替代方向独立启动"],
            "rule_ids": ["G08_UNIQUENESS"],
        })
        bundle = resolve(stage, facts)
        task = bundle["task_candidates"][0]
        self.assertEqual(task["direction_fact_id"], competitor["fact_id"])
        self.assertEqual(task["path_kind"], "ALTERNATIVE")
        self.assertTrue(task["candidate_ids"])


class PlanCompilerTests(unittest.TestCase):
    def setUp(self):
        self.facts = {
            "fact_catalog": {"F-D": {"scope": "DIRECTION"}},
            "stage_b_observation_universe": [
                {"thscode": "A.SH"}, {"thscode": "B.SH"}, {"thscode": "V.SH"},
            ],
        }
        self.stage_b = {
            "as_of": "20260105 CLOSE",
            "primary_path": {"status": "SELECTED", "theme": "示例",
                             "direction_fact_id": "F-D"},
        }
        self.task_bundle = {"task_candidates": [{
            "task_id": "TASK-X", "task_type": "SAME_LEVEL_PROMOTION",
            "theme": "示例", "direction_fact_id": "F-D",
        }]}
        self.pools = [{
            "task_id": "TASK-X", "status": "READY",
            "pool": [{"thscode": "A.SH"}, {"thscode": "B.SH"}],
            "validation_pool": [{"thscode": "V.SH"}],
        }]
        leaf = lambda code: {
            "thscode": code, "task_to_complete": "独立完成同板级晋级任务",
            "auction_conditions": ["相对同任务对手保持主动且验证对象不弱"],
            "open_conditions": ["开盘后承受分歧并维持价格重心"],
            "downgrade_conditions": ["竞价关系未决，需要开盘确认"],
            "direct_fail_conditions": ["竞价直接失去任务资格"],
        }
        candidate = lambda code, relation: {
            "thscode": code, "task_id": "TASK-X", "task_relation": relation,
        }
        self.stage_c = {
            "execution_task": {"status": "SELECTED", "task_id": "TASK-X",
                               "task_type": "SAME_LEVEL_PROMOTION", "theme": "示例",
                               "supporting_fact_ids": ["F-D"]},
            "candidates": [candidate("A.SH", "ACTION_COMPETITOR"),
                           candidate("B.SH", "ACTION_COMPETITOR"),
                           candidate("V.SH", "VALIDATION_ONLY")],
            "action_competition_group": {
                "task_id": "TASK-X", "members": ["A.SH", "B.SH"],
                "validation_objects": ["V.SH"],
            },
            "action_plan": {
                "status": "CONDITIONAL_PAIR", "task_id": "TASK-X",
                "primary": leaf("A.SH"), "backup": leaf("B.SH"),
                "validation_objects": ["V.SH"],
                "switch_rule": "PRIMARY直接失败且BACKUP独立满足自身条件才切换",
                "no_action_conditions": ["两者均未完成任务"],
            },
        }

    def test_valid_pair_compiles_to_closed_plan(self):
        result = compile_plan(self.stage_b, self.stage_c, self.task_bundle,
                              self.pools, self.facts)
        self.assertEqual(result["verdict"], "PASS")
        plan = result["executable_plan"]
        self.assertEqual(plan["allowed_action_codes"], ["A.SH", "B.SH"])
        self.assertEqual(plan["action_plan"]["switch_policy"],
                         "PRIMARY_DIRECT_FAIL_AND_BACKUP_INDEPENDENT_PASS")

    def test_validation_object_cannot_be_action_leaf(self):
        self.stage_c["action_plan"]["backup"]["thscode"] = "V.SH"
        result = compile_plan(self.stage_b, self.stage_c, self.task_bundle,
                              self.pools, self.facts)
        self.assertEqual(result["verdict"], "NEEDS_REVISION")
        self.assertTrue(any("验证对象" in item for item in result["violations"]))

    def test_fixed_open_percentage_is_rejected(self):
        self.stage_c["action_plan"]["primary"]["auction_conditions"] = ["必须高开3%"]
        result = compile_plan(self.stage_b, self.stage_c, self.task_bundle,
                              self.pools, self.facts)
        self.assertTrue(any("固定数字阈值" in item for item in result["violations"]))

    def test_three_unresolved_action_members_force_no_action(self):
        self.facts["stage_b_observation_universe"].append({"thscode": "C.SH"})
        self.pools[0]["pool"].append({"thscode": "C.SH"})
        self.stage_c["candidates"].append({
            "thscode": "C.SH", "task_id": "TASK-X", "task_relation": "ACTION_COMPETITOR",
        })
        self.stage_c["action_competition_group"]["members"].append("C.SH")
        result = compile_plan(self.stage_b, self.stage_c, self.task_bundle,
                              self.pools, self.facts)
        self.assertTrue(any("三只以上" in item for item in result["violations"]))

    def test_primary_downgrade_cannot_be_backup_switch_rule(self):
        self.stage_c["action_plan"]["switch_rule"] = "PRIMARY降级后切BACKUP"
        result = compile_plan(self.stage_b, self.stage_c, self.task_bundle,
                              self.pools, self.facts)
        self.assertTrue(any("直接失败" in item for item in result["violations"]))

    def test_symmetric_pair_rejects_primary_without_task_function_evidence(self):
        contract = {
            "status": "SYMMETRIC_UNRESOLVED", "primary_hint": None,
            "backup_hint": None,
            "allowed_evidence_families": ["DIRECTION_RESPONSE"],
        }
        self.task_bundle["task_candidates"][0]["pair_preference_contract"] = contract
        self.pools[0]["pair_preference_contract"] = contract
        self.stage_c["pairwise_comparison"] = [{
            "left_thscode": "A.SH", "right_thscode": "B.SH",
            "comparison_dimensions": ["仍然无法区分"],
            "left_advantages": [], "right_advantages": [],
            "unresolved": ["方向响应未知"], "conclusion": "NO_EDGE",
            "fact_ids": [], "evidence_families": ["DIRECTION_RESPONSE"],
            "rule_ids": [],
        }]
        result = compile_plan(self.stage_b, self.stage_c, self.task_bundle,
                              self.pools, self.facts)
        self.assertTrue(any("单边任务功能优势" in item for item
                            in result["violations"]))

    def test_symmetric_pair_accepts_primary_proved_by_allowed_task_family(self):
        contract = {
            "status": "SYMMETRIC_UNRESOLVED", "primary_hint": None,
            "backup_hint": None,
            "allowed_evidence_families": ["DIRECTION_RESPONSE"],
        }
        self.task_bundle["task_candidates"][0]["pair_preference_contract"] = contract
        self.stage_c["pairwise_comparison"] = [{
            "left_thscode": "A.SH", "right_thscode": "B.SH",
            "comparison_dimensions": ["谁的推进获得方向响应"],
            "left_advantages": ["A推进时验证对象同步响应"],
            "right_advantages": [], "unresolved": [],
            "conclusion": "LEFT_PRIMARY", "fact_ids": ["F-D"],
            "evidence_families": ["DIRECTION_RESPONSE"], "rule_ids": [],
        }]
        result = compile_plan(self.stage_b, self.stage_c, self.task_bundle,
                              self.pools, self.facts)
        self.assertEqual(result["verdict"], "PASS")

    def test_production_python_does_not_hardcode_golden_theme_or_stocks(self):
        package = Path(__file__).parents[1] / "roubing_engine"
        forbidden = ("商业航天", "北斗星通", "烽火通信", "002151.SZ", "600498.SH")
        hits = []
        for path in package.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for marker in forbidden:
                if marker in text:
                    hits.append(f"{path.relative_to(package)}:{marker}")
        self.assertEqual(hits, [])


class SplitStageCTests(unittest.TestCase):
    def test_c1_task_summary_contains_no_stock_or_pool_size(self):
        bundle = {"as_of": "20260302 CLOSE", "status": "ACTION_READY",
                  "task_candidates": [{
                      "task_id": "TASK-X", "task_type": "SAME_LEVEL_PROMOTION",
                      "task_name": "同板级晋级", "status": "ACTION_READY",
                      "path_kind": "PRIMARY", "theme": "示例", "node_id": "NODE-X",
                      "node_type": "UNIQUENESS", "node_action_status": "ACTION_READY",
                      "anchor_date": "2026-03-02", "required_function": "晋级",
                      "required_rule_ids": ["G08_UNIQUENESS"],
                      "scope_logic": ["同任务"], "completion_signals": ["完成"],
                      "failure_signals": ["失败"], "data_gaps": [],
                      "eligibility_fact_ids": ["F-DIR"],
                      "candidate_ids": ["A.SH", "B.SH"], "validation_ids": ["V.SH"],
                      "pair_preference_contract": {"primary_hint": "A.SH"},
                  }]}
        summary = summarize_tasks(bundle)
        text = str(summary)
        for forbidden in ("A.SH", "B.SH", "V.SH", "candidate_ids",
                          "validation_ids", "pool_size", "primary_hint"):
            self.assertNotIn(forbidden, text)

    def test_c1_rejects_easy_single_as_task_reason(self):
        task = {
            "task_id": "TASK-X", "task_type": "SAME_LEVEL_PROMOTION",
            "status": "ACTION_READY", "path_kind": "PRIMARY", "theme": "示例",
            "node_id": "NODE-X", "required_rule_ids": ["G08_UNIQUENESS"],
            "eligibility_fact_ids": ["F-DIR"],
        }
        decision = {
            "primary_task": {
                "path_kind": "PRIMARY", "status": "SELECTED", "task_id": "TASK-X",
                "task_type": "SAME_LEVEL_PROMOTION", "theme": "示例", "node_id": "NODE-X",
                "missing_function": "晋级", "selection_logic": ["候选只有一只，容易收敛"],
                "supporting_fact_ids": ["F-DIR"], "rule_ids": ["G08_UNIQUENESS"],
                "rejected_task_ids": [],
            },
            "alternative_task": {
                "path_kind": "ALTERNATIVE", "status": "NONE", "task_id": None,
                "task_type": None, "theme": None, "node_id": None,
                "missing_function": "无替代", "selection_logic": ["无独立节点"],
                "supporting_fact_ids": [], "rule_ids": [], "rejected_task_ids": [],
            },
        }
        violations = check_task_selection(
            {"primary_path": {"theme": "示例"}}, decision,
            {"task_candidates": [task]}, {"fact_catalog": {"F-DIR": {"scope": "DIRECTION"}}})
        self.assertTrue(any("非法理由" in item for item in violations))

    def test_c1_none_requires_the_frozen_no_action_rule_contract(self):
        decision = {
            "primary_task": {
                "path_kind": "PRIMARY", "status": "NONE", "task_id": None,
                "task_type": None, "theme": None, "node_id": None,
                "missing_function": "无动作节点", "selection_logic": ["方向不可比"],
                "supporting_fact_ids": ["F-DIR"], "rule_ids": [],
                "rejected_task_ids": [],
            },
            "alternative_task": {
                "path_kind": "ALTERNATIVE", "status": "NONE", "task_id": None,
                "task_type": None, "theme": None, "node_id": None,
                "missing_function": "无替代节点", "selection_logic": ["替代未独立成立"],
                "supporting_fact_ids": [], "rule_ids": ["DISC_NO_FIXED_SCORE"],
                "rejected_task_ids": [],
            },
        }
        bundle = {"task_candidates": [],
                  "no_action_rule_ids": ["DISC_NO_FIXED_SCORE"]}
        violations = check_task_selection(
            {"primary_path": {"theme": None}}, decision, bundle,
            {"fact_catalog": {"F-DIR": {"scope": "DIRECTION"}}})
        self.assertTrue(any("primary_task" in item and "no_action_rule_ids" in item
                            for item in violations))
        decision["primary_task"]["rule_ids"] = ["DISC_NO_FIXED_SCORE"]
        self.assertEqual(check_task_selection(
            {"primary_path": {"theme": None}}, decision, bundle,
            {"fact_catalog": {"F-DIR": {"scope": "DIRECTION"}}}), [])

    def test_selected_pool_projection_exposes_only_c1_tasks(self):
        decision = {
            "primary_task": {"status": "SELECTED", "task_id": "P"},
            "alternative_task": {"status": "NONE", "task_id": None},
        }
        pools = [{"task_id": "P"}, {"task_id": "A"}, {"task_id": "X"}]
        self.assertEqual(select_task_pools(decision, pools), [{"task_id": "P"}])

    def test_low_level_strength_cannot_replace_a_different_task_role(self):
        candidate = {
            "thscode": "LOW.SH",
            "agency_event_model": {
                "relation_state": "ROLE_REPLACED", "conclusion": "ACTIVE",
                "reference_task_id": "OTHER-TASK",
                "role_replacement_basis": ["低位股票先涨"],
            },
        }
        violations = check_role_relation(
            candidate, {"previous_role_task": {"available": True}}, "HIGH-TASK")
        self.assertTrue(any("不同任务对象不得确认" in item for item in violations))

    def test_pushed_by_reference_cannot_be_called_active(self):
        candidate = {
            "thscode": "A.SH",
            "agency_event_model": {
                "relation_state": "PUSHED_BY_REFERENCE", "conclusion": "ACTIVE",
                "reference_task_id": "TASK-X", "role_replacement_basis": [],
            },
        }
        violations = check_role_relation(candidate, {}, "TASK-X")
        self.assertTrue(any("被反推不能同时写主动" in item for item in violations))

    def test_compiler_supports_independent_cross_direction_backup(self):
        def path_plan(kind, task_id, code):
            leaf = {"thscode": code, "task_id": task_id, "path_kind": kind,
                    "task_to_complete": "独立完成本路径任务",
                    "auction_conditions": ["相对自身任务不弱"],
                    "open_conditions": ["承压后仍推进"],
                    "downgrade_conditions": ["只展示未确认"],
                    "direct_fail_conditions": ["结构直接失败"]}
            return {
                "path_kind": kind,
                "execution_task": {"status": "SELECTED", "task_id": task_id,
                                   "task_type": "TASK", "theme": kind,
                                   "missing_function": "功能", "selection_logic": ["节点需要"],
                                   "supporting_fact_ids": [], "rule_ids": [],
                                   "rejected_task_ids": []},
                "action_plan": {"status": "SINGLE", "task_id": task_id,
                                "primary": leaf, "backup": None,
                                "validation_objects": [], "rule_ids": [],
                                "switch_rule": "单对象", "no_action_conditions": ["失败"]},
                "candidates": [{"thscode": code, "anchor_date": "2026-03-02",
                                "node_id": f"NODE-{kind}", "stock_start_date": "2026-03-02",
                                "observed_function": "功能", "observed_state": ["事实"],
                                "cancel_if": ["失败"]}],
            }
        tasks = {"task_candidates": [
            {"task_id": "TASK-P", "status": "ACTION_READY", "path_kind": "PRIMARY",
             "node_id": "NODE-PRIMARY", "anchor_date": "2026-03-02"},
            {"task_id": "TASK-A", "status": "ACTION_READY", "path_kind": "ALTERNATIVE",
             "node_id": "NODE-ALTERNATIVE", "anchor_date": "2026-03-02"},
        ]}
        pools = [{"task_id": "TASK-P", "status": "ACTION_READY", "validation_pool": []},
                 {"task_id": "TASK-A", "status": "ACTION_READY", "validation_pool": []}]
        result = compile_plan(
            {"as_of": "20260302 CLOSE", "primary_path": {"theme": "PRIMARY"}},
            {"path_plans": [path_plan("PRIMARY", "TASK-P", "P.SH"),
                            path_plan("ALTERNATIVE", "TASK-A", "A.SH")],
             "final_action_plan": {
                 "status": "CONDITIONAL_PAIR",
                 "primary_ref": {"path_kind": "PRIMARY", "task_id": "TASK-P",
                                 "thscode": "P.SH"},
                 "backup_ref": {"path_kind": "ALTERNATIVE", "task_id": "TASK-A",
                                "thscode": "A.SH"},
                 "switch_rule": "PRIMARY直接失败且替代路径与个股独立通过才切换",
                 "no_action_conditions": ["两条路径都失败"], "rule_ids": [],
             }}, tasks, pools, {})
        self.assertEqual(result["verdict"], "PASS")
        plan = result["executable_plan"]
        self.assertEqual(plan["action_plan"]["primary"]["task_id"], "TASK-P")
        self.assertEqual(plan["action_plan"]["backup"]["task_id"], "TASK-A")
        self.assertEqual(plan["action_plan"]["backup"]["path_kind"], "ALTERNATIVE")


if __name__ == "__main__":
    unittest.main()
