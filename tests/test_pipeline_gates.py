from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from roubing_engine.reasoning import eod_pipeline


def stage_b():
    return {
        "as_of": "20260908 CLOSE",
        "environment": {
            "candidate": "ROTATION", "supporting": ["事实"], "counter": [],
            "migrated_from": None, "tomorrow_checks": ["检查"],
        },
        "mainstream_directions": [],
        "nodes": [{
            "node_type": "UNIQUENESS", "anchor_date": "2026-09-08", "theme": "示例",
            "trigger_facts": ["事实"], "generator": "G8", "candidate_ids": [],
            "confirm": ["确认"], "cancel": ["取消"],
        }],
        "data_gaps": [],
    }


def stage_c():
    return {
        "as_of": "20260908 CLOSE",
        "paths": {
            "primary": {"desc": "主路径", "confirm": [], "cancel": []},
            "alternative": {"desc": "备选", "trigger": [], "cancel": []},
            "no_action": {"trigger": []},
        },
        "competition_groups": [{
            "group_id": "g", "comparison_basis": ["同方向"], "members": ["A.SH"],
            "not_comparable_with": [], "leader_state": "UNRESOLVED",
            "pairwise_relations": [], "next_confirmation": ["次日"],
        }],
        "candidates": [{
            "thscode": "A.SH", "theme": "示例", "node": "UNIQUENESS",
            "generator": "G8", "anchor_date": "2026-09-08", "role": "UNKNOWN",
            "letter_carrier": "UNKNOWN", "competition_group": "g", "competitors": [],
            "observed_state": ["事实"], "tomorrow_must_do": ["任务"],
            "acceptable_variants": [], "failure_signals": ["失败"],
            "cancel_if": ["取消"], "output_tier": "待验证候选", "evidence": ["证据"],
        }],
        "excluded_candidates": [],
        "unknowns": [],
    }


class PipelineGateTests(unittest.TestCase):
    def test_failed_audit_never_persists_official_plan(self):
        facts = {
            "available": True, "as_of": "20260908 CLOSE", "trade_date": "20260908",
            "themes": [], "stage_b_observation_universe": [],
        }
        pools = [{
            "generator": "G8", "anchor_date": "2026-09-08", "status": "READY",
            "pool": [{"thscode": "A.SH"}], "pool_size": 1, "data_blocks": [],
        }]
        audit = {"verdict": "NEEDS_REVISION", "violations": ["反方未解决"],
                 "counter_arguments": ["可能是一日游"]}
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(eod_pipeline, "RUNS", Path(tmp)), \
             patch.object(eod_pipeline, "build_factpack", return_value=facts), \
             patch("roubing_engine.candidates.generators.build_pools_from_nodes",
                   return_value=pools), \
             patch.object(eod_pipeline.runner, "run", side_effect=[stage_b(), stage_c(), audit]):
            result = eod_pipeline.run_pipeline("20260908", backend="codex", with_daily=False)
            run_dir = Path(tmp) / "20260908"
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "BLOCKED_AUDIT")
            self.assertTrue((run_dir / "stage_c_result.draft.json").exists())
            self.assertFalse((run_dir / "stage_c_result.json").exists())
            self.assertFalse((run_dir / "battlecard_codex.md").exists())


if __name__ == "__main__":
    unittest.main()
