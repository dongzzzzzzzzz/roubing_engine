from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from roubing_engine.collectors import storage
from roubing_engine.collectors.f10_context import serialize_announcements
from roubing_engine.evaluation.fidelity import check_plan
from roubing_engine.reasoning import runner, schemas
from roubing_engine.reasoning.validation_factpack import (
    _auction_summary,
    _open5m,
    validate_snapshot_payload,
)
from roubing_engine.warehouse.timebox import seconds_from_label, session_type
from roubing_engine.warehouse.as_of import daily_available_at


class TimeSnapshotTests(unittest.TestCase):
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
    def _valid_candidate(self):
        return {
            "thscode": "A.SH", "theme": "示例", "node": "NODE", "generator": "G8",
            "anchor_date": "2026-09-08", "role": "UNKNOWN", "letter_carrier": "UNKNOWN",
            "competition_group": "g", "competitors": [], "observed_state": ["事实"],
            "tomorrow_must_do": ["任务"], "acceptable_variants": [],
            "failure_signals": ["失败"], "cancel_if": ["取消"], "output_tier": "待验证候选",
            "evidence": ["事实来源"],
        }

    def _valid_stage_c(self):
        return {
            "as_of": "20260908 CLOSE",
            "competition_groups": [{
                "group_id": "g", "comparison_basis": ["同方向同起算"], "members": ["A.SH"],
                "not_comparable_with": [], "leader_state": "UNRESOLVED",
                "pairwise_relations": [], "next_confirmation": ["次日确认"],
            }],
            "candidates": [self._valid_candidate()],
            "excluded_candidates": [],
            "paths": {
                "primary": {"desc": "主路径", "confirm": [], "cancel": []},
                "alternative": {"desc": "备选", "trigger": [], "cancel": []},
                "no_action": {"trigger": []},
            },
            "unknowns": [],
        }

    def test_nested_schema_rejects_incomplete_candidate(self):
        result = self._valid_stage_c()
        del result["candidates"][0]["tomorrow_must_do"]
        problems = runner.validate(result, schemas.STAGE_C_SCHEMA)
        self.assertTrue(any("tomorrow_must_do" in problem for problem in problems))

    def test_schema_rejects_letter_guess(self):
        result = self._valid_stage_c()
        result["candidates"][0]["letter_carrier"] = "A"
        problems = runner.validate(result, schemas.STAGE_C_SCHEMA)
        self.assertTrue(any("letter_carrier" in problem for problem in problems))

    def test_fidelity_rejects_candidate_outside_pool(self):
        stage_b = {"environment": {"candidate": "ROTATION"}, "nodes": [{
            "generator": "G8", "anchor_date": "2026-09-08"}]}
        stage_c = self._valid_stage_c()
        pools = [{"generator": "G8", "anchor_date": "2026-09-08", "pool": []}]
        result = check_plan(stage_b, stage_c, pools)
        self.assertEqual(result["verdict"], "NEEDS_REVISION")
        self.assertTrue(any("确定性候选池" in item for item in result["violations"]))

    def test_fidelity_rejects_score_or_position_output(self):
        stage_b = {"environment": {"candidate": "ROTATION"}, "nodes": [{
            "generator": "G8", "anchor_date": "2026-09-08"}]}
        stage_c = self._valid_stage_c()
        stage_c["candidates"][0]["score"] = 88
        stage_c["position_size"] = "half"
        pools = [{"generator": "G8", "anchor_date": "2026-09-08",
                  "pool": [{"thscode": "A.SH"}]}]
        result = check_plan(stage_b, stage_c, pools)
        self.assertTrue(any("固定打分/概率/仓位" in item for item in result["violations"]))

    def test_partial_pool_cannot_create_primary_candidate(self):
        stage_b = {"environment": {"candidate": "ROTATION"}, "nodes": [{
            "generator": "G8", "anchor_date": "2026-09-08"}]}
        stage_c = self._valid_stage_c()
        stage_c["candidates"][0]["output_tier"] = "主候选"
        pools = [{"generator": "G8", "anchor_date": "2026-09-08",
                  "status": "PARTIAL_DATA", "pool": [{"thscode": "A.SH"}]}]
        result = check_plan(stage_b, stage_c, pools)
        self.assertTrue(any("PARTIAL_DATA" in item for item in result["violations"]))

    def test_valid_schema(self):
        self.assertEqual(runner.validate(self._valid_stage_c(), schemas.STAGE_C_SCHEMA), [])


class CorpusTests(unittest.TestCase):
    def test_corpus_keeps_full_text(self):
        path = Path(__file__).parents[1] / "roubing_engine" / "rules" / "corpus_units.json"
        units = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(units), 282)
        self.assertTrue(all("text" in unit for unit in units))
        self.assertTrue(any(len(unit["text"]) > 400 for unit in units))


if __name__ == "__main__":
    unittest.main()
