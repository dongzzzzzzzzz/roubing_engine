"""Canonical roubing full-logic contracts.

This module is intentionally boring: it names the fixed rails from the merged
implementation plan so prompts, schemas, audits and ledger code do not each
carry slightly different versions of the business contract.

It does not decide market semantics.  The model still reasons about whether a
direction is mainstream, repaired, passive, active, etc.  These helpers only
check that the model answered the required questions in the approved shape and
did not smuggle unsupported states into the pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FactTableContract:
    table: str
    primary_source: str
    required_fields: tuple[str, ...]
    notes: tuple[str, ...] = ()


EVIDENCE_KINDS = (
    "OBSERVED_FACT",
    "AUTHOR_INTERPRETATION",
    "MODEL_INFERENCE",
    "DATA_INSUFFICIENT",
    "POST_ASOF_OUTCOME",
)

TRACE_STATUSES = ("APPLICABLE", "NOT_APPLICABLE", "DATA_INSUFFICIENT")

RULE_PROVENANCE_KINDS = (
    "AUTHOR_EXPLICIT",
    "CROSS_POST_SYNTHESIS",
    "RESEARCH_DISCIPLINE",
    "UNRESOLVED",
)

FACT_TABLES: tuple[FactTableContract, ...] = (
    FactTableContract(
        "stock_daily_bar", "Financial-API",
        ("trade_date", "thscode", "eltdx_code", "open", "high", "low", "close",
         "adj_open", "adj_high", "adj_low", "adj_close", "volume", "volume_unit",
         "amount", "change_pct", "event_time", "fetched_at", "source", "interface",
         "request_id"),
        ("daily price fields keep raw and adjusted prices",),
    ),
    FactTableContract(
        "index_daily_bar", "Financial-API",
        ("trade_date", "index_code", "index_name", "open", "high", "low", "close",
         "volume", "volume_unit", "amount", "change_pct", "event_time",
         "fetched_at", "source", "interface", "request_id"),
    ),
    FactTableContract(
        "board_membership_snapshot", "Financial-API",
        ("trade_date", "board_code", "board_name", "thscode", "eltdx_code",
         "member_name", "snapshot_time", "event_time", "fetched_at", "source",
         "interface", "request_id"),
        ("historical membership must come from an as-of snapshot, never current backfill",),
    ),
    FactTableContract(
        "limit_event", "Financial-API",
        ("trade_date", "thscode", "eltdx_code", "event_type", "board_level",
         "seal_amount", "open_board_count", "limit_reason", "event_time",
         "fetched_at", "source", "interface", "request_id"),
    ),
    FactTableContract(
        "theme_fact_daily", "Financial-API",
        ("trade_date", "thscode", "eltdx_code", "limit_reason", "f10_theme",
         "reason_source", "f10_source", "event_time", "fetched_at", "source",
         "interface", "request_id"),
        ("daily trading narrative and F10 company association must stay separated",),
    ),
    FactTableContract(
        "auction_point", "eltdx",
        ("trade_date", "thscode", "eltdx_code", "auction_time", "price",
         "matched_volume", "unmatched_volume", "rank_in_group", "event_time",
         "fetched_at", "source", "interface", "request_id"),
    ),
    FactTableContract(
        "opening_match", "eltdx",
        ("trade_date", "thscode", "eltdx_code", "open_price", "open_volume",
         "open_amount", "event_time", "fetched_at", "source", "interface",
         "request_id"),
    ),
    FactTableContract(
        "minute_bar", "eltdx",
        ("trade_date", "thscode", "eltdx_code", "minute", "open", "high", "low",
         "close", "avg_price", "volume", "volume_unit", "amount", "event_time",
         "fetched_at", "source", "interface", "request_id"),
    ),
    FactTableContract(
        "trade_tick", "eltdx",
        ("trade_date", "thscode", "eltdx_code", "tick_time", "price", "volume",
         "volume_unit", "amount", "side", "event_time", "fetched_at", "source",
         "interface", "request_id"),
    ),
    FactTableContract(
        "depth_snapshot", "eltdx",
        ("trade_date", "thscode", "eltdx_code", "snapshot_time", "bid_levels",
         "ask_levels", "event_time", "fetched_at", "source", "interface",
         "request_id"),
    ),
    FactTableContract(
        "announcement", "Financial-API",
        ("trade_date", "thscode", "eltdx_code", "announcement_time",
         "announcement_type", "title", "url", "event_time", "fetched_at",
         "source", "interface", "request_id"),
    ),
    FactTableContract(
        "rule_version", "Financial-API",
        ("rule_id", "market", "rule_name", "effective_from", "effective_to",
         "rule_provenance", "event_time", "fetched_at", "source", "interface",
         "request_id"),
        ("select by effective window; never apply future regulatory rules backwards",),
    ),
)

FACT_TABLE_BY_NAME = {contract.table: contract for contract in FACT_TABLES}

SOURCE_PRIORITY_RULES = {
    table.table: table.primary_source for table in FACT_TABLES
}

FORBIDDEN_CONFLICT_RESOLUTION = (
    "average",
    "mean",
    "silent_overwrite",
    "last_write_wins",
    "fill_zero",
)

LOCAL_DOWNGRADE_RULES = {
    "ONLY_0925_AVAILABLE": (
        "can_judge_official_open",
        "cannot_judge_cancel_order_decay_or_full_rank_migration",
    ),
    "MINUTE_WITHOUT_TICKS": (
        "can_judge_minute_acceptance",
        "cannot_confirm_second_level_active_order",
    ),
    "TICKS_WITHOUT_ORDER_QUEUE": (
        "can_judge_trade_sequence",
        "cannot_confirm_canceller_or_full_order_intent",
    ),
    "MISSING_INTRADAY": (
        "must_not_block_environment_direction_daily_role_or_eod_reasoning",
    ),
}

SYSTEM_BLOCK_REASONS = (
    "FULL_HISTORICAL_AUCTION_UNRECOVERABLE",
    "HISTORICAL_DEPTH_AND_ORDER_QUEUE_UNRECOVERABLE",
    "FULL_ORDER_TICK_AND_CANCEL_UNRECOVERABLE",
)

LIFECYCLE_STAGES = (
    "RANDOM_HOTSPOT",
    "LAUNCH_TEST",
    "CONTINUATION_CANDIDATE",
    "MAINSTREAM_CONFIRMED",
    "FIRST_OR_MAJOR_DIVERGENCE",
    "REPAIR",
    "OSCILLATION_OR_SECOND_WAVE",
    "DECLINE_OR_ENDED",
)

LIFECYCLE_FIELDS = (
    "theme",
    "first_candidate_date",
    "current_day_index",
    "stage_yesterday",
    "stage_today",
    "stage_change",
    "pioneer_state",
    "capacity_state",
    "back_row_feedback",
    "board_index_state",
    "buyer_feedback",
    "first_divergence_date",
    "divergence_order",
    "repair_history",
    "repair_quality",
    "catalyst_state",
    "regulatory_constraints",
    "upgrade_conditions",
    "downgrade_conditions",
    "tomorrow_validation",
)

MAINSTREAM_QUESTIONS = (
    "startup_continuation_divergence",
    "front_capacity_diffusion_layers",
    "board_index_strength_or_breakout",
    "major_divergence_core_capacity_repair",
    "internal_takeover_after_core_constraint",
)

CATALYST_TYPES = ("EVENT", "POLICY", "INDUSTRY", "EARNINGS", "UNKNOWN")
CATALYST_STAGES = (
    "NEW",
    "CONTINUING",
    "DIFFUSING",
    "REPEATED",
    "REALIZATION_RISK",
    "INVALIDATED",
)
CATALYST_FIELDS = (
    "catalyst_type",
    "catalyst_stage",
    "first_seen_or_repeated",
    "keyword_only_stocks",
    "capital_selected_stocks",
    "reason_continuity",
    "next_day_buyer_premium",
    "post_divergence_repair",
)

REASONED_FIELD_REQUIRED = (
    "status",
    "evidence_kind",
    "value",
    "observed",
    "inference",
    "supporting_fact_ids",
    "counter_fact_ids",
    "rule_ids",
    "unknowns",
)

FUNCTIONAL_ROLES = (
    "TOTAL_CORE",
    "EMOTION_HEIGHT_CORE",
    "CAPACITY_CORE",
    "BRANCH_CORE",
    "ASSIST_OR_COMPANION",
    "CATCH_UP",
    "LOW_LEVEL_SYMBIOSIS",
    "SECOND_WAVE_CARRIER",
    "OLD_CORE_RESIDUAL",
    "FOLLOWER",
    "UNKNOWN",
)

FUNCTIONAL_ROLE_FIELDS = (
    "role",
    "role_status",
    "entered_by_event",
    "current_function",
    "must_complete_next",
    "invalidated_by",
    "previous_role",
    "possible_next_roles",
    "active_or_passive_relation",
)

ROLE_INVALIDATION_CONTRACTS = {
    "TOTAL_CORE": "loses organization, space opening or board-assist/capacity leadership",
    "EMOTION_HEIGHT_CORE": "one-word height cannot continue after turnover",
    "CAPACITY_CORE": "large amount without price progression or board center support",
    "BRANCH_CORE": "sub-branch stops responding with the main direction",
    "ASSIST_OR_COMPANION": "no premium, competition failure or no diffusion",
    "CATCH_UP": "not anchored to total-core break day or fails next-day competition",
    "LOW_LEVEL_SYMBIOSIS": "no high-low overflow or persistence from second-wave divergence",
    "SECOND_WAVE_CARRIER": "only old-popularity rebound or lower structure",
    "OLD_CORE_RESIDUAL": "no renewed active leadership; passively pushed by new core",
    "FOLLOWER": "no independent leadership, capacity or stage uniqueness",
    "UNKNOWN": "role evidence not yet sufficient",
}

AUTHOR_LETTER_LABELS = ("A", "B", "D", "UNKNOWN")

STOCK_EXPECTATION_FIELDS = (
    "current_role",
    "today_state",
    "self_benchmark",
    "peer_benchmark",
    "environment_benchmark",
    "auction_expectation",
    "open_expectation",
    "board_response_expectation",
    "role_task",
    "minimum_confirmation",
    "direct_cancel",
    "regulatory_constraint",
)

TODAY_STATES = (
    "ONE_WORD_LIMIT",
    "FAST_LIMIT",
    "TURNOVER_LIMIT",
    "HEAVY_BROKEN_LIMIT",
    "RALLY_AND_FADE",
    "LIMIT_DOWN",
    "FIRST_MAJOR_DIVERGENCE",
    "POST_BREAKOUT_DIVERGENCE",
    "BELOW_RESISTANCE_DIVERGENCE",
    "HIGH_LEVEL_ADVANCE_FAILURE",
    "OTHER_OBSERVED",
)

EXPECTATION_GENERATION_ORDER = (
    "T_DAY_ROLE",
    "T_DAY_PERFORMANCE",
    "T_DAY_BOARD_STATE",
    "SAME_GROUP_SECOND_PLACE",
    "CURRENT_REGULATION_AND_REMAINING_SPACE",
)

EXPECTATION_MAPPINGS = {
    "WEAK_MAINSTREAM_PIONEER_CAPACITY_TEST": {
        "must": "pioneer advances, capacity rebounds or continues a large positive bar, board strengthens",
        "fail": "pioneer breaks and capacity does not rebound; treat as one-day theme",
    },
    "DIVERGENCE_DAY_STRONGEST_AGENCY": {
        "must": "continues stronger than same-group second place",
        "fail": "falls behind at auction; prior active role is cancelled",
    },
    "TURNOVER_CORE_ON_BOARD_EXPLOSION": {
        "must": "continues and competes for consecutive limit",
        "fail": "slightly opens down and cannot quickly turn strong",
    },
    "PREVIOUS_ONE_WORD_OR_EXTREME_ACCELERATION": {
        "must": "strength matches prior inertia or quickly reseals after divergence",
        "fail": "seal decays and cannot open according to its role",
    },
    "MAIN_TREND_CORE_FIRST_POST_BREAKOUT_DIVERGENCE": {
        "must": "recovers selling pressure, touches limit or continues progression",
        "fail": "diverges under resistance, cannot recover, role task unfinished",
    },
    "EXTERNAL_ENVIRONMENT_FADE": {
        "must": "when environment repairs, rebounds first",
        "fail": "environment repairs while target still lags",
    },
    "PANIC_DAY_RESISTANT_OR_COUNTER_TREND_LIMIT": {
        "must": "attacks first when index stabilizes",
        "fail": "only follows passive index rebound",
    },
    "BOARD_SURGE_CORE_SHOULD_LEAD": {
        "must": "core stabilizes, accelerates and keeps leading",
        "fail": "rally fades and lags followers",
    },
    "SECOND_WAVE_SHOULD_PROGRESS": {
        "must": "touches limit, chains limit or remains same-group first",
        "fail": "replaced by new core or continues weakening",
    },
    "OVERSOLD_INTRADAY_LEADER": {
        "must": "first check next-day premium; only extend when exceeding expectation",
        "fail": "next day weak means it ends; do not treat as reversal",
    },
}

HOLDING_CHECK_FIELDS = (
    "total_core_lead_repair_board_assist",
    "capacity_core_progression_after_volume",
    "assist_and_low_level_premium_ladder",
    "regulation_and_abnormal_space_valid",
    "repair_high_quality_board_response_decay",
    "buyer_profit_cushion",
    "best_assist_continuation",
    "ladder_integrity",
    "real_capital_takeover_after_divergence",
    "diffusion_next_day_reward",
)

EXIT_REASONS = (
    "FAILED_EXPECTATION",
    "ROLE_REPLACED",
    "BOARD_ORDER_DETERIORATED",
    "HIGH_LEVEL_ADVANCE_FAILED",
    "STRUCTURE_BROKEN",
    "CATALYST_REGULATION_ENV_INVALIDATED",
)

EXIT_STYLES = (
    "EARLY_RISK_REDUCTION",
    "WAIT_FOR_STRUCTURE_BREAK",
)

CONCEPT_GUARDRAILS = {
    "ANTI_HUMAN_NATURE": "requires inertia expectation, opposite real behavior, intact logic/role/structure and post-selling confirmation",
    "DIVERGENCE": "classify by location, external relation and subsequent feedback; not a buy point by itself",
    "UNIQUENESS": "requires anchor date, candidate pool, comparison dimensions and invalidation conditions",
    "RESONANCE": "must name synchronized objects; do not write empty resonance",
    "SEPARATION": "declare comparison object first; target must independently advance while external/old core weakens",
    "UPTREND_PAUSE": "await classification; do not call top or second wave from a doji alone",
    "HUGE_VOLUME": "judge relative to own history, location and role; no universal multiple",
    "WASH_OR_DISTRIBUTION": "write observable facts only; do not infer main-force intent",
    "ICE_SWORD": "write defense and exit before every attack",
    "BOTTLE_BOTTOM": "medium-cycle research only; cannot directly generate short-term buy point",
}

SCENARIO_REFERENCE_QUESTIONS = (
    "environment_similarity",
    "node_similarity",
    "role_similarity",
    "competition_similarity",
    "key_differences",
    "confirmation",
    "cancellation",
)

SCENARIOS = {
    "SUPER_MAINSTREAM_BOARD_WEAK_TO_STRONG": {"reference_only": True},
    "MAINSTREAM_MAJOR_DIVERGENCE_TO_CONSENSUS": {"reference_only": True},
    "EARLY_BREAKOUT": {"reference_only": True},
    "UNIQUENESS_BREAKTHROUGH": {"reference_only": True},
    "MAINSTREAM_INTERNAL_STRENGTH_SWITCH": {"reference_only": True},
    "SECOND_WAVE": {"reference_only": True},
    "BOTTOM_OR_OVERSOLD_REPAIR": {"reference_only": True},
    "PROFIT_EFFECT_REPLICATION": {"reference_only": True},
    "HIGH_LEVEL_REALIZATION": {"reference_only": True},
}

DAILY_LEDGER_SECTIONS = (
    "environment_transition",
    "direction_lifecycle",
    "catalyst_state",
    "divergence_and_repair_history",
    "nodes_and_maturity",
    "execution_tasks",
    "unselected_tasks",
    "competition_groups",
    "failed_same_period_candidates",
    "roles",
    "author_letter_labels",
    "role_migrations",
    "stock_expectations",
    "m4_results",
    "m5_results",
    "vtail_results",
    "trade_decision",
    "holding_reviews",
    "exit_reviews",
    "data_gaps",
    "unknowns",
    "fact_rule_source_levels",
    "run_id",
    "model_config",
    "code_version",
)


def _missing_required(row: dict[str, Any], required: tuple[str, ...]) -> list[str]:
    return [field for field in required if field not in row]


def validate_fact_row(table: str, row: dict[str, Any]) -> list[str]:
    """Validate one raw fact row against the table/source/as-of contract."""
    contract = FACT_TABLE_BY_NAME.get(table)
    if not contract:
        return [f"unknown fact table: {table}"]
    violations = [f"{table}: missing {field}" for field in _missing_required(row, contract.required_fields)]
    if row.get("source") != contract.primary_source:
        violations.append(
            f"{table}: source must be {contract.primary_source}, got {row.get('source')!r}")
    if row.get("volume_unit") and row.get("volume_unit") not in {"share", "hand"}:
        violations.append(f"{table}: volume_unit must be share/hand")
    if any(field.endswith("_pct") for field in row) and any(
            abs(float(row[field])) > 100 for field in row
            if field.endswith("_pct") and isinstance(row.get(field), (int, float))):
        violations.append(f"{table}: _pct fields must not be silently multiplied by 100")
    if "event_time" in row and row.get("event_time") is None:
        violations.append(f"{table}: event_time null cannot be coerced or accepted")
    if "fetched_at" in row and row.get("fetched_at") is None:
        violations.append(f"{table}: fetched_at null cannot be coerced or accepted")
    if not row.get("request_id"):
        violations.append(f"{table}: request_id/raw record id is required")
    return violations


def validate_rule_record(record: dict[str, Any]) -> list[str]:
    provenance = record.get("rule_provenance")
    if provenance not in RULE_PROVENANCE_KINDS:
        return [f"rule_provenance must be one of {RULE_PROVENANCE_KINDS}"]
    if not record.get("effective_from"):
        return ["rule_version: effective_from is required"]
    return []


def validate_source_conflict(table: str, record: dict[str, Any]) -> list[str]:
    """Validate dual-source conflict handling for one logical fact.

    The plan does not allow averaging or overwriting two raw vendors into one
    value.  If both sources exist and disagree, the record must keep raw
    source-specific fields plus an explicit conflict status.
    """
    primary = SOURCE_PRIORITY_RULES.get(table)
    if primary is None:
        return [f"unknown fact table: {table}"]
    violations = []
    resolution = record.get("conflict_resolution")
    if resolution in FORBIDDEN_CONFLICT_RESOLUTION:
        violations.append(f"{table}: forbidden conflict_resolution={resolution}")
    source_values = record.get("source_values") or {}
    if not source_values:
        return violations
    if primary not in source_values:
        violations.append(f"{table}: primary source {primary} missing from source_values")
    for field, values in (record.get("field_conflicts") or {}).items():
        if not isinstance(values, dict) or len(values) < 2:
            violations.append(f"{table}.{field}: field_conflicts must keep per-source raw values")
            continue
        unique_values = {repr(value) for value in values.values()}
        if len(unique_values) > 1:
            split_fields = record.get("raw_split_fields") or {}
            field_splits = split_fields.get(field) or []
            expected = {f"{source}_{field}" for source in values}
            if set(field_splits) != expected:
                violations.append(
                    f"{table}.{field}: conflicting raw values must be split as {sorted(expected)}")
            if record.get("conflict_status") not in {"CONFLICT_RETAINED", "PRIMARY_SELECTED_RAW_RETAINED"}:
                violations.append(f"{table}.{field}: conflict_status must explicitly retain conflict")
    return violations


def validate_evidence_refs(label: str, refs: Any) -> list[str]:
    if not isinstance(refs, list) or not refs:
        return [f"{label}: evidence_refs must be a non-empty list"]
    violations = []
    for index, ref in enumerate(refs):
        path = f"{label}.evidence_refs[{index}]"
        if not isinstance(ref, dict):
            violations.append(f"{path}: must be object")
            continue
        if not ref.get("id"):
            violations.append(f"{path}: id required")
        if ref.get("evidence_kind") not in EVIDENCE_KINDS:
            violations.append(f"{path}: evidence_kind invalid: {ref.get('evidence_kind')!r}")
        if not ref.get("source_field"):
            violations.append(f"{path}: source_field required")
        if ref.get("evidence_kind") == "POST_ASOF_OUTCOME":
            violations.append(f"{path}: post-as-of outcome cannot support current plan")
    return violations


def _reasoned_value(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) else value


def validate_reasoned_field(label: str, field: Any) -> list[str]:
    if not isinstance(field, dict):
        return [f"{label}: must be a reasoned object, not {type(field).__name__}"]
    violations = [f"{label}: missing {key}"
                  for key in _missing_required(field, REASONED_FIELD_REQUIRED)]
    status = field.get("status")
    if status not in TRACE_STATUSES:
        violations.append(f"{label}.status invalid: {status!r}")
    evidence_kind = field.get("evidence_kind")
    if evidence_kind not in EVIDENCE_KINDS:
        violations.append(f"{label}.evidence_kind invalid: {evidence_kind!r}")
    if status == "DATA_INSUFFICIENT" and evidence_kind != "DATA_INSUFFICIENT":
        violations.append(f"{label}: DATA_INSUFFICIENT status requires evidence_kind=DATA_INSUFFICIENT")
    if status == "APPLICABLE" and evidence_kind == "POST_ASOF_OUTCOME":
        violations.append(f"{label}: applicable reasoning cannot use post-as-of outcome as evidence")
    if status == "APPLICABLE":
        if not field.get("observed"):
            violations.append(f"{label}: APPLICABLE requires observed facts")
        if not field.get("supporting_fact_ids"):
            violations.append(f"{label}: APPLICABLE requires supporting_fact_ids")
        if not field.get("rule_ids"):
            violations.append(f"{label}: APPLICABLE requires rule_ids")
    if status == "DATA_INSUFFICIENT" and not field.get("unknowns"):
        violations.append(f"{label}: DATA_INSUFFICIENT requires unknowns")
    return violations


def validate_lifecycle_row(row: dict[str, Any]) -> list[str]:
    violations = [f"direction_lifecycle: missing {field}"
                  for field in _missing_required(row, LIFECYCLE_FIELDS)]
    for field in LIFECYCLE_FIELDS:
        if field == "theme" or field not in row or field == "catalyst_state":
            continue
        violations.extend(validate_reasoned_field(f"direction_lifecycle.{field}", row.get(field)))
    stage_today = _reasoned_value(row.get("stage_today"))
    stage_yesterday = _reasoned_value(row.get("stage_yesterday"))
    if stage_today not in LIFECYCLE_STAGES:
        violations.append(f"direction_lifecycle.stage_today.value invalid: {stage_today!r}")
    if stage_yesterday not in (*LIFECYCLE_STAGES, None):
        violations.append(
            f"direction_lifecycle.stage_yesterday.value invalid: {stage_yesterday!r}")
    answers = row.get("mainstream_questions") or {}
    missing_questions = [key for key in MAINSTREAM_QUESTIONS if key not in answers]
    if missing_questions:
        violations.append(f"direction_lifecycle.mainstream_questions missing {missing_questions}")
    for key in MAINSTREAM_QUESTIONS:
        if key in answers:
            violations.extend(validate_reasoned_field(
                f"direction_lifecycle.mainstream_questions.{key}", answers.get(key)))
    catalyst = row.get("catalyst_state")
    if isinstance(catalyst, dict):
        violations.extend(validate_catalyst_state(catalyst))
    elif "catalyst_state" in row:
        violations.append("catalyst_state: must be an object")
    return violations


def validate_catalyst_state(row: dict[str, Any]) -> list[str]:
    violations = [f"catalyst_state: missing {field}"
                  for field in _missing_required(row, CATALYST_FIELDS)]
    for field in CATALYST_FIELDS:
        if field in row:
            violations.extend(validate_reasoned_field(f"catalyst_state.{field}", row.get(field)))
    catalyst_type = _reasoned_value(row.get("catalyst_type"))
    catalyst_stage = _reasoned_value(row.get("catalyst_stage"))
    if catalyst_type not in CATALYST_TYPES:
        violations.append(f"catalyst_type.value invalid: {catalyst_type!r}")
    if catalyst_stage not in CATALYST_STAGES:
        violations.append(f"catalyst_stage.value invalid: {catalyst_stage!r}")
    if row.get("direct_buy_signal") is True:
        violations.append("catalyst_state: catalyst cannot directly generate a buy signal")
    return violations


def validate_functional_role(row: dict[str, Any]) -> list[str]:
    violations = [f"functional_role: missing {field}"
                  for field in _missing_required(row, FUNCTIONAL_ROLE_FIELDS)]
    role = row.get("role")
    if role not in FUNCTIONAL_ROLES:
        violations.append(f"functional_role.role invalid: {role!r}")
    for next_role in row.get("possible_next_roles") or []:
        if next_role not in FUNCTIONAL_ROLES:
            violations.append(f"functional_role.possible_next_roles invalid: {next_role!r}")
    letter = row.get("author_letter_label")
    if letter is not None and letter not in AUTHOR_LETTER_LABELS:
        violations.append(f"author_letter_label invalid: {letter!r}")
    if letter in {"A", "B", "D"} and role == "UNKNOWN":
        # Allowed, but must not be treated as a functional role.
        return violations
    if letter in {"A", "B", "D"} and row.get("role") == letter:
        violations.append("functional role must not be derived from author A/B/D label")
    return violations


def validate_stock_expectation(row: dict[str, Any]) -> list[str]:
    violations = [f"stock_expectation: missing {field}"
                  for field in _missing_required(row, STOCK_EXPECTATION_FIELDS)]
    if row.get("today_state") not in TODAY_STATES:
        violations.append(f"today_state invalid: {row.get('today_state')!r}")
    order = tuple(row.get("generation_order") or ())
    if order and order != EXPECTATION_GENERATION_ORDER:
        violations.append("stock_expectation.generation_order must follow role/performance/board/peer/regulation")
    text = " ".join(str(row.get(key, "")) for key in row)
    forbidden = ("固定预期分数", "固定高开", "固定封单", "通用量能倍数")
    for marker in forbidden:
        if marker in text:
            violations.append(f"stock_expectation uses forbidden fixed expectation marker: {marker}")
    return violations


def validate_holding_review(row: dict[str, Any]) -> list[str]:
    violations = [f"holding_review: missing {field}"
                  for field in _missing_required(row, HOLDING_CHECK_FIELDS)]
    for field in HOLDING_CHECK_FIELDS:
        if field in row:
            violations.extend(validate_reasoned_field(f"holding_review.{field}", row.get(field)))
    return violations


def validate_exit_review(row: dict[str, Any]) -> list[str]:
    violations = []
    if row.get("exit_reason") not in EXIT_REASONS:
        violations.append(f"exit_reason invalid: {row.get('exit_reason')!r}")
    if row.get("exit_style") not in EXIT_STYLES:
        violations.append(f"exit_style invalid: {row.get('exit_style')!r}")
    text = " ".join(str(value) for value in row.values())
    if any(marker in text for marker in ("失败两项", "三项清仓", "满足两项减仓")):
        violations.append("exit_review must not use fixed-count exit counters")
    if row.get("five_day_line_only") is True:
        violations.append("five-day line can only be structural reference, not sole exit rule")
    return violations


def validate_scenario_reference(row: dict[str, Any]) -> list[str]:
    scenario = row.get("scenario")
    violations = []
    if scenario not in SCENARIOS:
        violations.append(f"unknown scenario: {scenario!r}")
    elif SCENARIOS[scenario].get("reference_only") is not True:
        violations.append(f"scenario {scenario} must be reference_only")
    for question in SCENARIO_REFERENCE_QUESTIONS:
        if question not in row:
            violations.append(f"scenario_reference: missing {question}")
    if row.get("direct_action") is True:
        violations.append("scenario cannot directly generate an action")
    if row.get("kline_shape_only") is True:
        violations.append("scenario match must reject K-line-shape-only similarity")
    return violations


def validate_daily_ledger(entry: dict[str, Any]) -> list[str]:
    violations = [f"DailyLedger: missing section {field}"
                  for field in DAILY_LEDGER_SECTIONS if field not in entry]
    for index, row in enumerate(entry.get("direction_lifecycle") or []):
        for item in validate_lifecycle_row(row):
            violations.append(f"direction_lifecycle[{index}]: {item}")
    for index, row in enumerate(entry.get("stock_expectations") or []):
        for item in validate_stock_expectation(row):
            violations.append(f"stock_expectations[{index}]: {item}")
    for index, row in enumerate(entry.get("exit_reviews") or []):
        for item in validate_exit_review(row):
            violations.append(f"exit_reviews[{index}]: {item}")
    return violations


def validate_block_scope(block: dict[str, Any]) -> list[str]:
    """Distinguish true system BLOCK from local DATA_INSUFFICIENT downgrade."""
    scope = block.get("scope")
    reason = block.get("reason")
    if scope == "SYSTEM_BLOCK":
        if reason not in SYSTEM_BLOCK_REASONS:
            return [f"SYSTEM_BLOCK reason invalid: {reason!r}"]
        return []
    if scope == "LOCAL_DOWNGRADE":
        if reason not in LOCAL_DOWNGRADE_RULES:
            return [f"LOCAL_DOWNGRADE reason invalid: {reason!r}"]
        if not block.get("blocked_conclusions"):
            return ["LOCAL_DOWNGRADE must list blocked conclusions"]
        if block.get("blocks_eod_reasoning") is True and reason == "MISSING_INTRADAY":
            return ["missing intraday data must not block environment/direction/EOD reasoning"]
        return []
    return ["block scope must be SYSTEM_BLOCK or LOCAL_DOWNGRADE"]
