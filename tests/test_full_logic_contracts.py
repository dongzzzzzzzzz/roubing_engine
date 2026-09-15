from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

import pandas as pd

from roubing_engine.reasoning import contracts
from roubing_engine.reasoning.day_factpack import build as build_factpack
from roubing_engine.collectors import schedule
from roubing_engine.collectors import serialize
from roubing_engine.warehouse.contract_report import validate_warehouse
from roubing_engine.warehouse.migrate_contract import migrate


def reasoned(value="observed", *, status="APPLICABLE"):
    return {
        "status": status,
        "evidence_kind": "DATA_INSUFFICIENT" if status == "DATA_INSUFFICIENT" else "MODEL_INFERENCE",
        "value": value,
        "observed": ["Factual observation"],
        "inference": "reasoned from facts and rules",
        "supporting_fact_ids": ["F-1"] if status == "APPLICABLE" else [],
        "counter_fact_ids": [],
        "rule_ids": ["R-1"] if status == "APPLICABLE" else [],
        "unknowns": ["missing data"] if status == "DATA_INSUFFICIENT" else [],
    }


class FullLogicContractTests(unittest.TestCase):
    def test_contract_catalog_has_exact_plan_enumerations(self):
        self.assertEqual(len(contracts.FACT_TABLES), 12)
        self.assertEqual(contracts.EVIDENCE_KINDS, (
            "OBSERVED_FACT", "AUTHOR_INTERPRETATION", "MODEL_INFERENCE",
            "DATA_INSUFFICIENT", "POST_ASOF_OUTCOME",
        ))
        self.assertEqual(contracts.RULE_PROVENANCE_KINDS, (
            "AUTHOR_EXPLICIT", "CROSS_POST_SYNTHESIS",
            "RESEARCH_DISCIPLINE", "UNRESOLVED",
        ))
        self.assertEqual(contracts.LIFECYCLE_STAGES, (
            "RANDOM_HOTSPOT", "LAUNCH_TEST", "CONTINUATION_CANDIDATE",
            "MAINSTREAM_CONFIRMED", "FIRST_OR_MAJOR_DIVERGENCE", "REPAIR",
            "OSCILLATION_OR_SECOND_WAVE", "DECLINE_OR_ENDED",
        ))
        self.assertEqual(len(contracts.MAINSTREAM_QUESTIONS), 5)
        self.assertEqual(contracts.CATALYST_TYPES, (
            "EVENT", "POLICY", "INDUSTRY", "EARNINGS", "UNKNOWN",
        ))
        self.assertEqual(contracts.CATALYST_STAGES, (
            "NEW", "CONTINUING", "DIFFUSING", "REPEATED",
            "REALIZATION_RISK", "INVALIDATED",
        ))
        self.assertEqual(contracts.FUNCTIONAL_ROLES, (
            "TOTAL_CORE", "EMOTION_HEIGHT_CORE", "CAPACITY_CORE", "BRANCH_CORE",
            "ASSIST_OR_COMPANION", "CATCH_UP", "LOW_LEVEL_SYMBIOSIS",
            "SECOND_WAVE_CARRIER", "OLD_CORE_RESIDUAL", "FOLLOWER", "UNKNOWN",
        ))
        self.assertEqual(len(contracts.EXPECTATION_MAPPINGS), 10)
        self.assertEqual(len(contracts.CONCEPT_GUARDRAILS), 10)
        self.assertEqual(len(contracts.SCENARIOS), 9)
        self.assertEqual(contracts.EXIT_REASONS, (
            "FAILED_EXPECTATION", "ROLE_REPLACED", "BOARD_ORDER_DETERIORATED",
            "HIGH_LEVEL_ADVANCE_FAILED", "STRUCTURE_BROKEN",
            "CATALYST_REGULATION_ENV_INVALIDATED",
        ))
        self.assertEqual(contracts.EXIT_STYLES, (
            "EARLY_RISK_REDUCTION", "WAIT_FOR_STRUCTURE_BREAK",
        ))

    def test_fact_row_requires_source_request_id_time_and_units(self):
        ok = {
            "trade_date": "20260302", "thscode": "000001.SZ",
            "eltdx_code": "000001", "open": 1.0, "high": 1.1, "low": 0.9,
            "close": 1.0, "adj_open": 1.0, "adj_high": 1.1,
            "adj_low": 0.9, "adj_close": 1.0, "volume": 100,
            "volume_unit": "share", "amount": 1000, "change_pct": 5.0,
            "event_time": "2026-03-02 15:00:00 Asia/Shanghai",
            "fetched_at": "2026-03-02 15:02:00 Asia/Shanghai",
            "source": "Financial-API", "interface": "daily_bar",
            "request_id": "REQ-1",
        }
        self.assertEqual(contracts.validate_fact_row("stock_daily_bar", ok), [])

        bad = dict(ok)
        bad.pop("request_id")
        bad["source"] = "eltdx"
        bad["volume_unit"] = "lot"
        bad["event_time"] = None
        violations = contracts.validate_fact_row("stock_daily_bar", bad)
        self.assertTrue(any("source must be Financial-API" in item for item in violations))
        self.assertTrue(any("volume_unit" in item for item in violations))
        self.assertTrue(any("request_id" in item for item in violations))
        self.assertTrue(any("event_time null" in item for item in violations))

    def test_dual_source_conflicts_must_keep_raw_split_values(self):
        ok = {
            "source_values": {"Financial-API": {}, "eltdx": {}},
            "field_conflicts": {"close": {"Financial-API": 10.0, "eltdx": 10.1}},
            "raw_split_fields": {
                "close": ["Financial-API_close", "eltdx_close"],
            },
            "conflict_status": "CONFLICT_RETAINED",
        }
        self.assertEqual(contracts.validate_source_conflict("stock_daily_bar", ok), [])

        bad = {
            "source_values": {"Financial-API": {}, "eltdx": {}},
            "field_conflicts": {"close": {"Financial-API": 10.0, "eltdx": 10.1}},
            "raw_split_fields": {"close": ["close"]},
            "conflict_resolution": "average",
        }
        violations = contracts.validate_source_conflict("stock_daily_bar", bad)
        self.assertTrue(any("forbidden conflict_resolution" in item for item in violations))
        self.assertTrue(any("conflicting raw values must be split" in item
                            for item in violations))
        self.assertTrue(any("conflict_status" in item for item in violations))

    def test_evidence_refs_require_kind_and_reject_post_asof_support(self):
        self.assertEqual(contracts.validate_evidence_refs("candidate", [{
            "id": "F-1",
            "evidence_kind": "OBSERVED_FACT",
            "source_field": "fact_catalog",
        }]), [])
        violations = contracts.validate_evidence_refs("candidate", [{
            "id": "F-FUTURE",
            "evidence_kind": "POST_ASOF_OUTCOME",
            "source_field": "tomorrow_close",
        }])
        self.assertTrue(any("post-as-of" in item for item in violations))
        self.assertTrue(contracts.validate_evidence_refs("candidate", []))

    def test_local_downgrade_is_not_system_block(self):
        self.assertEqual(contracts.validate_block_scope({
            "scope": "SYSTEM_BLOCK",
            "reason": "FULL_HISTORICAL_AUCTION_UNRECOVERABLE",
        }), [])
        self.assertTrue(any("SYSTEM_BLOCK reason invalid" in item for item in
                            contracts.validate_block_scope({
                                "scope": "SYSTEM_BLOCK",
                                "reason": "ONLY_0925_AVAILABLE",
                            })))
        self.assertTrue(any("must not block" in item for item in
                            contracts.validate_block_scope({
                                "scope": "LOCAL_DOWNGRADE",
                                "reason": "MISSING_INTRADAY",
                                "blocked_conclusions": ["秒级主动顺序"],
                                "blocks_eod_reasoning": True,
                            })))

    def test_lifecycle_requires_mainstream_questions_and_catalyst_contract(self):
        row = {
            field: reasoned("x") for field in contracts.LIFECYCLE_FIELDS
            if field != "theme"
        }
        row["theme"] = "方向甲"
        row.update({
            "stage_yesterday": reasoned(None, status="DATA_INSUFFICIENT"),
            "stage_today": reasoned("MAINSTREAM_CONFIRMED"),
            "mainstream_questions": {
                key: reasoned("answered") for key in contracts.MAINSTREAM_QUESTIONS
            },
            "catalyst_state": {
                field: reasoned("observed") for field in contracts.CATALYST_FIELDS
            },
        })
        row["catalyst_state"]["catalyst_type"] = reasoned("POLICY")
        row["catalyst_state"]["catalyst_stage"] = reasoned("DIFFUSING")
        self.assertEqual(contracts.validate_lifecycle_row(row), [])

        bad = dict(row)
        bad["stage_today"] = reasoned("三天十家固定主流")
        bad["mainstream_questions"] = {}
        bad["catalyst_state"] = {
            **row["catalyst_state"],
            "catalyst_stage": reasoned("BUY_NOW"),
            "direct_buy_signal": True,
        }
        violations = contracts.validate_lifecycle_row(bad)
        self.assertTrue(any("stage_today.value invalid" in item for item in violations))
        self.assertTrue(any("mainstream_questions missing" in item for item in violations))
        self.assertTrue(any("catalyst_stage.value invalid" in item for item in violations))
        self.assertTrue(any("cannot directly generate" in item for item in violations))

    def test_functional_role_and_expectation_contracts(self):
        role = {
            "role": "CAPACITY_CORE",
            "role_status": "CONFIRMED",
            "entered_by_event": ["大成交主动带动"],
            "current_function": "承载大资金并稳定板块重心",
            "must_complete_next": ["分歧后继续推进"],
            "invalidated_by": ["只有成交无价格推进"],
            "previous_role": None,
            "possible_next_roles": ["TOTAL_CORE", "OLD_CORE_RESIDUAL"],
            "active_or_passive_relation": "INDEPENDENTLY_ACTIVE",
            "author_letter_label": "UNKNOWN",
        }
        self.assertEqual(contracts.validate_functional_role(role), [])
        bad_role = {**role, "role": "B", "possible_next_roles": ["C"]}
        self.assertTrue(any("role invalid" in item for item in
                            contracts.validate_functional_role(bad_role)))

        expectation = {
            field: "observed" for field in contracts.STOCK_EXPECTATION_FIELDS
        }
        expectation.update({
            "today_state": "POST_BREAKOUT_DIVERGENCE",
            "generation_order": list(contracts.EXPECTATION_GENERATION_ORDER),
        })
        self.assertEqual(contracts.validate_stock_expectation(expectation), [])
        bad_expectation = {**expectation, "today_state": "高开三点就买",
                           "auction_expectation": "固定高开3%"}
        violations = contracts.validate_stock_expectation(bad_expectation)
        self.assertTrue(any("today_state invalid" in item for item in violations))
        self.assertTrue(any("固定高开" in item for item in violations))

    def test_holding_exit_and_scenario_contracts(self):
        holding = {field: reasoned("answered") for field in contracts.HOLDING_CHECK_FIELDS}
        self.assertEqual(contracts.validate_holding_review(holding), [])
        self.assertTrue(any("missing" in item for item in
                            contracts.validate_holding_review({})))

        exit_review = {
            "exit_reason": "ROLE_REPLACED",
            "exit_style": "WAIT_FOR_STRUCTURE_BREAK",
            "reason": ["新核心先主动，旧核心只被动跟随"],
        }
        self.assertEqual(contracts.validate_exit_review(exit_review), [])
        bad_exit = {
            **exit_review,
            "exit_reason": "跌破五日线",
            "five_day_line_only": True,
            "reason": ["失败两项减仓"],
        }
        violations = contracts.validate_exit_review(bad_exit)
        self.assertTrue(any("exit_reason invalid" in item for item in violations))
        self.assertTrue(any("fixed-count" in item for item in violations))
        self.assertTrue(any("five-day line" in item for item in violations))

        scenario = {
            "scenario": "SECOND_WAVE",
            **{question: "answered" for question in contracts.SCENARIO_REFERENCE_QUESTIONS},
        }
        self.assertEqual(contracts.validate_scenario_reference(scenario), [])
        bad_scenario = {**scenario, "direct_action": True, "kline_shape_only": True}
        violations = contracts.validate_scenario_reference(bad_scenario)
        self.assertTrue(any("cannot directly generate" in item for item in violations))
        self.assertTrue(any("K-line-shape-only" in item for item in violations))

    def test_daily_ledger_contract_reports_missing_sections(self):
        entry = {section: None for section in contracts.DAILY_LEDGER_SECTIONS}
        entry["direction_lifecycle"] = []
        entry["stock_expectations"] = []
        entry["exit_reviews"] = []
        self.assertEqual(contracts.validate_daily_ledger(entry), [])

        violations = contracts.validate_daily_ledger({"direction_lifecycle": []})
        self.assertTrue(any("DailyLedger: missing section environment_transition" in item
                            for item in violations))

    def test_intraday_capture_schedule_includes_event_snapshots(self):
        jobs = schedule.daily_jobs("20260302")
        self.assertEqual(schedule.validate_schedule(jobs), [])
        ids = {job["job_id"] for job in jobs}
        self.assertIn("AUCTION_0915_INITIAL", ids)
        self.assertIn("AUCTION_0920_POST_CANCEL", ids)
        self.assertIn("OPENING_0925_MATCH", ids)
        self.assertIn("OPEN_0930_0935_CONTEXT", ids)
        self.assertIn("CLOSE_FINAL_STATE", ids)

        event_job = schedule.event_snapshot_job("20260302", "BROKEN_LIMIT", "10:31:08")
        self.assertEqual(event_job["phase"], "EVENT_SNAPSHOT")
        self.assertIn("trade_tick", event_job["datasets"])
        self.assertEqual(schedule.validate_schedule(jobs + [event_job]), [])
        with self.assertRaisesRegex(ValueError, "unsupported event"):
            schedule.event_snapshot_job("20260302", "KLINE_LOOKS_SIMILAR", "10:31:08")

    def test_eltdx_serializers_emit_fact_contract_columns(self):
        point = type("AuctionPoint", (), {
            "index": 1, "time_label": "09:15:01", "time_seconds": 33301,
            "price": 10.0, "matched_volume": 100,
            "matched_amount_estimated": 1000.0, "unmatched_volume": 200,
            "unmatched_signed_raw": 200, "unmatched_direction_raw": 1,
        })()
        snap = type("OpeningSnap", (), {
            "time_label": "09:25", "trade_datetime": None, "price": 10.5,
            "volume": 300, "order_count": 5, "trade_amount_yuan": 3150.0,
            "event_kind": "OPENING_MATCH",
        })()
        auction = type("Auction", (), {
            "series": type("Series", (), {"points": [point]})(),
            "snapshot_0925": snap,
            "pre_close_price": 10.0,
            "open_price": None,
            "open_change_pct": 5.0,
            "open_amount": None,
        })()
        minute = type("MinuteSeries", (), {
            "points": [type("Minute", (), {
                "index": 1, "time_label": "09:31", "time": "09:31",
                "price": 10.6, "avg_price": 10.55, "volume": 1000,
            })()]
        })()
        trades = type("TradePage", (), {
            "ticks": [type("Tick", (), {
                "absolute_index": 1, "index": 1, "time_label": "09:31:02",
                "trade_datetime": None, "price": 10.61, "volume": 100,
                "side": "B", "event_kind": "TRADE", "is_actual_trade": True,
                "order_count": 1, "trade_amount_yuan": 1061.0,
                "status_raw": "成交",
            })()]
        })()

        checks = [
            ("auction_point", serialize.serialize_auction(auction, "000001.SZ", "20260302")[0]),
            ("opening_match", serialize.serialize_opening(auction, "000001.SZ", "20260302")[0]),
            ("minute_bar", serialize.serialize_minutes(minute, "000001.SZ", "20260302")[0]),
            ("trade_tick", serialize.serialize_trades(trades, "000001.SZ", "20260302")[0]),
        ]
        for table, row in checks:
            with self.subTest(table=table):
                self.assertEqual(contracts.validate_fact_row(table, row), [])

    def test_real_20260302_block_scope_does_not_block_eod(self):
        facts = build_factpack("20260302", with_index=False)
        self.assertTrue(facts.get("available"))
        report = facts.get("block_scope_report") or {}
        self.assertEqual(report.get("status"), "PASS")
        self.assertFalse(report.get("eod_reasoning_blocked"))
        self.assertTrue(any(
            block.get("scope") in {"LOCAL_DOWNGRADE", "SYSTEM_BLOCK"}
            for block in report.get("blocks") or []
        ))
        blocked = {
            conclusion
            for block in report.get("blocks") or []
            for conclusion in block.get("blocked_conclusions") or []
        }
        self.assertTrue(
            {"完整委托队列变化", "撤单主体/队列意图确认"} & blocked
        )
        catalog = facts.get("fact_catalog") or {}
        self.assertTrue(any(
            row.get("fact_type") == "BLOCK_SCOPE_REPORT"
            for row in facts.get("context_facts") or []
        ))
        self.assertTrue(any(
            row.get("scope") == "CONTEXT"
            and row.get("fact_type") == "BLOCK_SCOPE_REPORT"
            for row in catalog.values()
        ))

    def test_warehouse_contract_report_passes_contract_shaped_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for contract in contracts.FACT_TABLES:
                row = {field: f"{field}-v" for field in contract.required_fields}
                row["source"] = contract.primary_source
                if "volume_unit" in row:
                    row["volume_unit"] = "share"
                table_dir = root / contract.table
                table_dir.mkdir(parents=True)
                pd.DataFrame([row]).to_parquet(table_dir / "all.parquet", index=False)
            report = validate_warehouse(root)
            self.assertEqual(report["status"], "PASS")
            self.assertTrue(all(row["status"] == "PASS" for row in report["tables"]))

    def test_contract_migration_upgrades_existing_legacy_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "stock_daily_bar").mkdir(parents=True)
            pd.DataFrame([{
                "thscode": "000001.SZ", "trade_date": "20260302",
                "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5,
                "volume": 1000, "turnover": 10500.0,
                "source": "financial_api_dump", "fetched_at": "2026-03-02T07:01:00Z",
            }]).to_parquet(root / "stock_daily_bar" / "all.parquet", index=False)
            (root / "auction_point" / "date=20260302").mkdir(parents=True)
            pd.DataFrame([{
                "trade_date": "20260302", "thscode": "000001.SZ",
                "time_label": "09:15:01", "time_seconds": 33301,
                "price": 10.1, "matched_volume": 100,
                "unmatched_volume": 200, "source": "eltdx",
                "fetched_at": "2026-03-02T01:15:02Z",
            }]).to_parquet(
                root / "auction_point" / "date=20260302" / "part.parquet",
                index=False,
            )

            dry = migrate(root, write=False)
            self.assertEqual(dry["status"], "PASS")
            written = migrate(root, write=True)
            self.assertEqual(written["status"], "PASS")
            report = validate_warehouse(root)
            rows = {row["table"]: row for row in report["tables"]}
            self.assertEqual(rows["stock_daily_bar"]["status"], "PASS")
            self.assertEqual(rows["auction_point"]["status"], "PASS")
            self.assertTrue((root / "_migration_backup" / "contract_v1"
                             / "stock_daily_bar" / "all.parquet").exists())


if __name__ == "__main__":
    unittest.main()
