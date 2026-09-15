"""Strict structural contracts for every reasoning stage.

The format is a deliberately small JSON-Schema subset implemented by
``runner.validate``.  Keeping it dependency-free makes the guardrail available
even in capture-only/offline environments.
"""

from roubing_engine.reasoning import contracts

STRING = {"type": "string", "minLength": 1}
STRING_LIST = {"type": "array", "items": STRING}
TRACE_STATUSES = ["APPLICABLE", "NOT_APPLICABLE", "DATA_INSUFFICIENT"]

_EVIDENCE_REF = {
    "type": "object",
    "required": ["id", "evidence_kind", "source_field"],
    "properties": {
        "id": STRING,
        "evidence_kind": {"type": "string", "enum": list(contracts.EVIDENCE_KINDS)},
        "source_field": STRING,
        "note": STRING,
    },
}
EVIDENCE_REFS = {
    "type": "array", "items": _EVIDENCE_REF,
}
REQUIRED_EVIDENCE_REFS = {
    "type": "array", "minItems": 1, "items": _EVIDENCE_REF,
}

_METHOD_TRACE_ROW = {
    "type": "object",
    "required": ["step_id", "status", "fact_ids", "counter_fact_ids", "reason_code", "judgment",
                 "downstream_effect", "forbidden_conclusions", "audit_status"],
    "properties": {
        "step_id": STRING,
        "status": {"type": "string", "enum": TRACE_STATUSES},
        "fact_ids": STRING_LIST,
        "counter_fact_ids": STRING_LIST,
        "reason_code": STRING,
        "judgment": STRING,
        "downstream_effect": STRING_LIST,
        "forbidden_conclusions": STRING_LIST,
        "audit_status": {"type": "string", "enum": ["PASS", "REVISE"]},
    },
}

_ENVIRONMENT_HYPOTHESIS = {
    "type": "object",
    "required": ["environment", "status", "supporting_fact_ids",
                 "counter_fact_ids", "unknowns", "downstream_effect",
                 "forbidden_conclusions"],
    "properties": {
        "environment": {"type": "string", "enum": [
            "MAIN_TREND", "ROTATION", "DECLINE", "REGIME_SWITCH"]},
        "status": {"type": "string", "enum": TRACE_STATUSES},
        "supporting_fact_ids": STRING_LIST,
        "counter_fact_ids": STRING_LIST,
        "unknowns": STRING_LIST,
        "downstream_effect": STRING_LIST,
        "forbidden_conclusions": STRING_LIST,
    },
}

ENVIRONMENTS = ["MAIN_TREND", "ROTATION", "DECLINE", "REGIME_SWITCH", "DATA_INSUFFICIENT"]
GENERATORS = [f"G{i}" for i in range(1, 13)]
ROLES = [
    "总核心", "容量核心", "情绪核心", "分支核心", "助攻伴飞", "补涨",
    "低位伴生", "二波载体", "旧核心残余", "跟风", "UNKNOWN",
]
ROLE_FAMILIES = ["核心", "容量", "补涨", "伴飞", "二波伴生", "旧核心残余", "跟风", "UNKNOWN"]
ROLE_STATUSES = ["CANDIDATE", "PROVISIONAL", "CONFIRMED", "REPLACED", "CANCELLED", "UNKNOWN"]
ROLE_TO_FAMILY = {
    "总核心": "核心", "情绪核心": "核心", "分支核心": "核心",
    "容量核心": "容量", "补涨": "补涨", "低位伴生": "补涨",
    "助攻伴飞": "伴飞", "二波载体": "二波伴生", "旧核心残余": "旧核心残余",
    "跟风": "跟风", "UNKNOWN": "UNKNOWN",
}
OUTPUT_TIERS = ["主候选", "待验证候选", "替代候选", "取消或不行动"]
PAIR_EVIDENCE_FAMILIES = [
    "TASK_COMPLETION_PRESTATE", "INDEPENDENCE_AND_EVENT_ORDER",
    "DIRECTION_RESPONSE", "DIVERGENCE_TOLERANCE", "CAPACITY_CARRYING",
    "ROLE_CONTINUITY_OR_MIGRATION",
]

_REASONED_FIELD = {
    "type": "object",
    "required": ["status", "evidence_kind", "value", "observed", "inference",
                 "supporting_fact_ids", "counter_fact_ids", "rule_ids", "unknowns"],
    "properties": {
        "status": {"type": "string", "enum": TRACE_STATUSES},
        "evidence_kind": {"type": "string", "enum": list(contracts.EVIDENCE_KINDS)},
        "value": {},
        "observed": STRING_LIST,
        "inference": STRING,
        "supporting_fact_ids": STRING_LIST,
        "counter_fact_ids": STRING_LIST,
        "rule_ids": STRING_LIST,
        "unknowns": STRING_LIST,
    },
}

_REASONED_LIFECYCLE_STAGE = {
    **_REASONED_FIELD,
    "properties": {
        **_REASONED_FIELD["properties"],
        "value": {"type": ["string", "null"], "enum": list(contracts.LIFECYCLE_STAGES) + [None]},
    },
}

_REASONED_CATALYST_TYPE = {
    **_REASONED_FIELD,
    "properties": {
        **_REASONED_FIELD["properties"],
        "value": {"type": "string", "enum": list(contracts.CATALYST_TYPES)},
    },
}

_REASONED_CATALYST_STAGE = {
    **_REASONED_FIELD,
    "properties": {
        **_REASONED_FIELD["properties"],
        "value": {"type": "string", "enum": list(contracts.CATALYST_STAGES)},
    },
}

_CATALYST_STATE = {
    "type": "object",
    "required": list(contracts.CATALYST_FIELDS),
    "properties": {
        "catalyst_type": _REASONED_CATALYST_TYPE,
        "catalyst_stage": _REASONED_CATALYST_STAGE,
        "first_seen_or_repeated": _REASONED_FIELD,
        "keyword_only_stocks": _REASONED_FIELD,
        "capital_selected_stocks": _REASONED_FIELD,
        "reason_continuity": _REASONED_FIELD,
        "next_day_buyer_premium": _REASONED_FIELD,
        "post_divergence_repair": _REASONED_FIELD,
    },
}

_MAINSTREAM_QUESTIONS = {
    "type": "object",
    "required": list(contracts.MAINSTREAM_QUESTIONS),
    "properties": {key: _REASONED_FIELD for key in contracts.MAINSTREAM_QUESTIONS},
}

_DIRECTION_LIFECYCLE_PROPERTIES = {
    "first_candidate_date": _REASONED_FIELD,
    "current_day_index": _REASONED_FIELD,
    "stage_yesterday": _REASONED_LIFECYCLE_STAGE,
    "stage_today": _REASONED_LIFECYCLE_STAGE,
    "stage_change": _REASONED_FIELD,
    "pioneer_state": _REASONED_FIELD,
    "capacity_state": _REASONED_FIELD,
    "back_row_feedback": _REASONED_FIELD,
    "board_index_state": _REASONED_FIELD,
    "buyer_feedback": _REASONED_FIELD,
    "first_divergence_date": _REASONED_FIELD,
    "divergence_order": _REASONED_FIELD,
    "repair_history": _REASONED_FIELD,
    "repair_quality": _REASONED_FIELD,
    "catalyst_state": _CATALYST_STATE,
    "regulatory_constraints": _REASONED_FIELD,
    "upgrade_conditions": _REASONED_FIELD,
    "downgrade_conditions": _REASONED_FIELD,
    "tomorrow_validation": _REASONED_FIELD,
    "mainstream_questions": _MAINSTREAM_QUESTIONS,
}

STAGE_B_SCHEMA = {
    "type": "object",
    "required": ["as_of", "environment", "direction_evaluations", "primary_path",
                 "direction_comparisons", "nodes", "data_gaps"],
    "properties": {
        "as_of": STRING,
        "environment": {
            "type": "object",
            "required": ["status", "reasoning", "supporting_fact_ids", "counter_fact_ids",
                         "rule_ids", "migrated_from", "tomorrow_checks"],
            "properties": {
                "status": {"type": "string", "enum": ENVIRONMENTS},
                "reasoning": {"type": "array", "minItems": 1, "items": STRING},
                "supporting_fact_ids": STRING_LIST,
                "counter_fact_ids": STRING_LIST,
                "rule_ids": STRING_LIST,
                "migrated_from": {"type": ["string", "null"]},
                "tomorrow_checks": STRING_LIST,
            },
        },
        "direction_evaluations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["theme", "direction_fact_id", "stage", "market_relation",
                             "path_status", "observed_facts", "inferences",
                             "supporting_fact_ids", "counter_fact_ids", "rule_ids", "competitors",
                             "data_gaps", "first_candidate_date", "current_day_index",
                             "stage_yesterday", "stage_today", "stage_change",
                             "pioneer_state", "capacity_state", "back_row_feedback",
                             "board_index_state", "buyer_feedback", "first_divergence_date",
                             "divergence_order", "repair_history", "repair_quality",
                             "catalyst_state", "regulatory_constraints",
                             "upgrade_conditions", "downgrade_conditions",
                             "tomorrow_validation", "mainstream_questions"],
                "properties": {
                    "theme": STRING,
                    "direction_fact_id": STRING,
                    "stage": STRING,
                    **_DIRECTION_LIFECYCLE_PROPERTIES,
                    "market_relation": {"type": "string", "enum": [
                        "LEADS", "CONFIRMS", "FOLLOWS", "WEAKENS", "ISOLATED", "UNRESOLVED"]},
                    "path_status": {"type": "string", "enum": [
                        "PRIMARY", "COMPETITOR", "OBSERVATION", "REJECTED", "BLOCKED_DATA"]},
                    "observed_facts": {"type": "array", "minItems": 1, "items": STRING},
                    "inferences": STRING_LIST,
                    "supporting_fact_ids": STRING_LIST,
                    "counter_fact_ids": STRING_LIST,
                    "rule_ids": STRING_LIST,
                    "competitors": STRING_LIST,
                    "data_gaps": STRING_LIST,
                },
            },
        },
        "direction_comparisons": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["left_theme", "right_theme", "dimensions", "relation",
                             "reasoning", "supporting_fact_ids", "counter_fact_ids",
                             "rule_ids"],
                "properties": {
                    "left_theme": STRING,
                    "right_theme": STRING,
                    "dimensions": {"type": "array", "minItems": 2, "items": STRING},
                    "relation": {"type": "string", "enum": [
                        "LEFT_DOMINATES", "RIGHT_DOMINATES", "INCOMPARABLE", "BOTH_REJECTED"]},
                    "reasoning": {"type": "array", "minItems": 1, "items": STRING},
                    "supporting_fact_ids": STRING_LIST,
                    "counter_fact_ids": STRING_LIST,
                    "rule_ids": STRING_LIST,
                },
            },
        },
        "primary_path": {
            "type": "object",
            "required": ["status", "theme", "direction_fact_id", "selection_logic",
                         "supporting_fact_ids", "counter_fact_ids", "rule_ids", "competitor_themes",
                         "cancel_conditions"],
            "properties": {
                "status": {"type": "string", "enum": ["SELECTED", "NONE", "BLOCKED_DATA"]},
                "theme": {"type": ["string", "null"]},
                "direction_fact_id": {"type": ["string", "null"]},
                "selection_logic": {"type": "array", "minItems": 1, "items": STRING},
                "supporting_fact_ids": STRING_LIST,
                "counter_fact_ids": STRING_LIST,
                "rule_ids": STRING_LIST,
                "competitor_themes": STRING_LIST,
                "cancel_conditions": STRING_LIST,
            },
        },
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["node_type", "anchor_date", "theme", "trigger_facts",
                             "trigger_fact_ids", "method_reasoning", "generator",
                             "node_id", "action_status", "candidate_scope",
                             "candidate_ids", "rule_ids", "confirm", "cancel"],
                "properties": {
                    "node_id": STRING,
                    "node_type": STRING,
                    "action_status": {"type": "string", "enum": [
                        "ACTION_READY", "OBSERVATION_ONLY", "BLOCKED"]},
                    "anchor_date": {"type": "string", "format": "date"},
                    "theme": {"type": ["string", "null"]},
                    "trigger_facts": STRING_LIST,
                    "trigger_fact_ids": STRING_LIST,
                    "method_reasoning": {"type": "array", "minItems": 1, "items": STRING},
                    "generator": {"type": ["string", "null"], "enum": GENERATORS + [None]},
                    "candidate_scope": {
                        "type": "object",
                        "required": ["event_statuses", "board_levels", "sub_directions",
                                     "candidate_ids", "validation_ids", "scope_reason"],
                        "properties": {
                            "event_statuses": STRING_LIST,
                            "board_levels": {"type": "array", "items": {"type": "integer"}},
                            "sub_directions": STRING_LIST,
                            "candidate_ids": STRING_LIST,
                            "validation_ids": STRING_LIST,
                            "scope_reason": STRING,
                        },
                    },
                    "candidate_ids": STRING_LIST,
                    "rule_ids": STRING_LIST,
                    "confirm": STRING_LIST,
                    "cancel": STRING_LIST,
                },
            },
        },
        "data_gaps": STRING_LIST,
    },
}

M1_SCHEMA = {
    "type": "object",
    "required": ["as_of", "environment", "environment_hypotheses",
                 "direction_evaluations", "direction_comparisons",
                 "primary_path", "method_trace", "data_gaps"],
    "properties": {
        "as_of": STRING,
        "environment": STAGE_B_SCHEMA["properties"]["environment"],
        "environment_hypotheses": {
            "type": "array", "minItems": 4, "items": _ENVIRONMENT_HYPOTHESIS,
        },
        "direction_evaluations": STAGE_B_SCHEMA["properties"]["direction_evaluations"],
        "direction_comparisons": STAGE_B_SCHEMA["properties"]["direction_comparisons"],
        "primary_path": STAGE_B_SCHEMA["properties"]["primary_path"],
        "method_trace": {
            "type": "array", "minItems": 10, "items": _METHOD_TRACE_ROW,
        },
        "data_gaps": STRING_LIST,
    },
}

_GENERATOR_APPLICABILITY = {
    "type": "object",
    "required": ["generator", "status", "prior_state", "prior_resistance",
                 "changed_facts", "benefited_function", "anchor_date",
                 "natural_candidate_scope", "confirm", "cancel",
                 "fact_ids", "counter_fact_ids", "rule_ids"],
    "properties": {
        "generator": {"type": "string", "enum": GENERATORS},
        "status": {"type": "string", "enum": TRACE_STATUSES},
        "prior_state": STRING,
        "prior_resistance": STRING,
        "changed_facts": STRING_LIST,
        "benefited_function": STRING,
        "anchor_date": {"type": ["string", "null"]},
        "natural_candidate_scope": STRING,
        "confirm": STRING_LIST,
        "cancel": STRING_LIST,
        "fact_ids": STRING_LIST,
        "counter_fact_ids": STRING_LIST,
        "rule_ids": STRING_LIST,
    },
}

_NODE_QUESTIONS = {
    "type": "object",
    "required": ["prior_state", "prior_resistance", "changed_facts",
                 "benefited_function", "anchor_date", "natural_candidate_scope",
                 "confirm", "cancel"],
    "properties": {
        "prior_state": STRING,
        "prior_resistance": STRING,
        "changed_facts": STRING_LIST,
        "benefited_function": STRING,
        "anchor_date": {"type": ["string", "null"]},
        "natural_candidate_scope": STRING,
        "confirm": STRING_LIST,
        "cancel": STRING_LIST,
    },
}

_M2_NODE = {
    **STAGE_B_SCHEMA["properties"]["nodes"]["items"],
    "required": STAGE_B_SCHEMA["properties"]["nodes"]["items"]["required"] + [
        "node_questions",
    ],
    "properties": {
        **STAGE_B_SCHEMA["properties"]["nodes"]["items"]["properties"],
        "node_questions": _NODE_QUESTIONS,
    },
}

M2_SCHEMA = {
    "type": "object",
    "required": ["as_of", "generator_applicability", "nodes",
                 "method_trace", "data_gaps"],
    "properties": {
        "as_of": STRING,
        "generator_applicability": {
            "type": "array", "minItems": 12, "items": _GENERATOR_APPLICABILITY,
        },
        "nodes": {
            **STAGE_B_SCHEMA["properties"]["nodes"],
            "items": _M2_NODE,
        },
        "method_trace": {
            "type": "array", "minItems": 12, "items": _METHOD_TRACE_ROW,
        },
        "data_gaps": STRING_LIST,
    },
}

CANDIDATE_REQUIRED = [
    "thscode", "name", "theme", "task_id", "observed_function", "task_relation",
    "node", "node_id", "generator", "anchor_date", "stock_start_date",
    "role", "role_family", "role_status",
    "capacity_tasks", "agency_event_model",
    "letter_carrier", "competition_group", "competitors", "observed_state",
    "tomorrow_must_do", "acceptable_variants", "failure_signals", "cancel_if",
    "output_tier", "evidence",
]

_CANDIDATE = {
    "type": "object",
    "required": CANDIDATE_REQUIRED + ["evidence_refs"],
    "properties": {
        "thscode": STRING,
        "name": STRING,
        "theme": STRING,
        "task_id": STRING,
        "observed_function": STRING,
        "task_relation": {"type": "string", "enum": [
            "ACTION_COMPETITOR", "VALIDATION_ONLY", "NOT_RELEVANT"]},
        "node": STRING,
        "node_id": STRING,
        "generator": {"type": ["string", "null"], "enum": GENERATORS + [None]},
        "anchor_date": {"type": "string", "format": "date"},
        "stock_start_date": {"type": ["string", "null"]},
        "role": {"type": "string", "enum": ROLES},
        "role_family": {"type": "string", "enum": ROLE_FAMILIES},
        "role_status": {"type": "string", "enum": ROLE_STATUSES},
        "capacity_tasks": {
            "type": "object",
            "required": ["price_progression", "pullback_recovery", "sector_leadership",
                         "center_of_gravity", "replacement_state"],
            "properties": {
                "price_progression": STRING,
                "pullback_recovery": STRING,
                "sector_leadership": STRING,
                "center_of_gravity": STRING,
                "replacement_state": STRING,
            },
        },
        "agency_event_model": {
            "type": "object",
            "required": ["reference", "event_sequence", "target_behavior",
                         "data_sufficiency", "conclusion", "relation_state",
                         "reference_task_id", "role_replacement_basis"],
            "properties": {
                "reference": STRING,
                "reference_task_id": {"type": ["string", "null"]},
                "event_sequence": {"type": "array", "minItems": 1, "items": STRING},
                "target_behavior": STRING,
                "data_sufficiency": {"type": "string", "enum": ["SUFFICIENT", "PARTIAL", "INSUFFICIENT", "UNKNOWN"]},
                "conclusion": {"type": "string", "enum": ["ACTIVE", "PASSIVE", "UNKNOWN"]},
                "relation_state": {"type": "string", "enum": [
                    "INDEPENDENTLY_ACTIVE", "INDEPENDENCE_NOT_CONFIRMED",
                    "PUSHED_BY_REFERENCE", "ROLE_REPLACED", "UNKNOWN"]},
                "role_replacement_basis": STRING_LIST,
            },
        },
        "letter_carrier": {"type": "string", "enum": ["UNKNOWN"]},
        "competition_group": STRING,
        "competitors": STRING_LIST,
        "observed_state": {"type": "array", "minItems": 1, "items": STRING},
        "tomorrow_must_do": {"type": "array", "minItems": 1, "items": STRING},
        "acceptable_variants": STRING_LIST,
        "failure_signals": {"type": "array", "minItems": 1, "items": STRING},
        "cancel_if": {"type": "array", "minItems": 1, "items": STRING},
        "output_tier": {"type": "string", "enum": OUTPUT_TIERS},
        "evidence": {"type": "array", "minItems": 1, "items": STRING},
        "evidence_refs": REQUIRED_EVIDENCE_REFS,
    },
}

_LEADER_STATE = {
    "type": "object",
    "required": ["status", "thscode", "evidence", "evidence_refs"],
    "properties": {
        "status": {"type": "string", "enum": [
            "UNRESOLVED", "PROVISIONAL", "CONFIRMED", "REPLACED", "CANCELLED"]},
        "thscode": {"type": ["string", "null"]},
        "evidence": STRING_LIST,
        "evidence_refs": EVIDENCE_REFS,
    },
}

_PAIRWISE_RELATION = {
    "type": "object",
    "required": ["left_thscode", "right_thscode", "left_event_time",
                 "right_event_time", "relation", "evidence", "evidence_refs"],
    "properties": {
        "left_thscode": STRING,
        "right_thscode": STRING,
        "left_event_time": {"type": ["string", "null"]},
        "right_event_time": {"type": ["string", "null"]},
        "relation": {"type": "string", "enum": [
            "LEFT_EARLIER", "RIGHT_EARLIER", "SAME_TIME", "UNRESOLVED", "NOT_COMPARABLE"]},
        "evidence": STRING_LIST,
        "evidence_refs": EVIDENCE_REFS,
    },
}

_COMPETITION_GROUP = {
    "type": "object",
    "required": ["group_id", "generator", "anchor_date", "theme",
                 "comparison_basis", "members", "not_comparable_with",
                 "leader_state", "pairwise_relations", "next_confirmation",
                 "coverage_status", "next_day_tasks", "uniqueness_status"],
    "properties": {
        "group_id": STRING,
        "generator": {"type": ["string", "null"], "enum": GENERATORS + [None]},
        "anchor_date": {"type": "string", "format": "date"},
        "theme": STRING,
        "comparison_basis": {"type": "array", "minItems": 1, "items": STRING},
        "members": {"type": "array", "minItems": 1, "items": STRING},
        "not_comparable_with": STRING_LIST,
        "leader_state": _LEADER_STATE,
        "pairwise_relations": {"type": "array", "items": _PAIRWISE_RELATION},
        "next_confirmation": STRING_LIST,
        "coverage_status": {"type": "string", "enum": ["COMPLETE", "PARTIAL", "MISSING"]},
        "next_day_tasks": STRING_LIST,
        "rule_ids": STRING_LIST,
        "uniqueness_status": {"type": "string", "enum": ["UNRESOLVED", "CONFIRMED", "REPLACED", "CANCELLED"]},
    },
}

_EXCLUDED_CANDIDATE = {
    "type": "object",
    "required": ["thscode", "name", "theme", "task_id", "generator",
                 "anchor_date", "reason"],
    "properties": {
        "thscode": STRING,
        "name": STRING,
        "theme": STRING,
        "task_id": STRING,
        "generator": {"type": ["string", "null"], "enum": GENERATORS + [None]},
        "anchor_date": {"type": "string", "format": "date"},
        "reason": STRING,
    },
}

_PATH_CLAIM = {
    "type": "object",
    "required": ["status", "statement", "evidence", "evidence_refs"],
    "properties": {
        "status": {"type": "string", "enum": ["SUPPORTED", "HYPOTHESIS", "UNKNOWN"]},
        "statement": STRING,
        "evidence": STRING_LIST,
        "evidence_refs": EVIDENCE_REFS,
    },
}

_PATH_COMMON = {
    "observed_facts": {"type": "array", "minItems": 1, "items": STRING},
    "ai_inferences": STRING_LIST,
    "unknowns": STRING_LIST,
    "capital_source": _PATH_CLAIM,
    "buyer": _PATH_CLAIM,
    "seller": _PATH_CLAIM,
    "destination_layer": _PATH_CLAIM,
    "successor": _PATH_CLAIM,
}

_PATH_REQUIRED = [
    "observed_facts", "ai_inferences", "unknowns", "capital_source", "buyer",
    "seller", "destination_layer", "successor",
]

_EXECUTION_TASK = {
    "type": "object",
    "required": ["status", "task_id", "task_type", "theme", "missing_function",
                 "selection_logic", "supporting_fact_ids", "rejected_task_ids"],
    "properties": {
        "status": {"type": "string", "enum": ["SELECTED", "NONE", "BLOCKED_DATA"]},
        "task_id": {"type": ["string", "null"]},
        "task_type": {"type": ["string", "null"]},
        "theme": {"type": ["string", "null"]},
        "missing_function": STRING,
        "selection_logic": {"type": "array", "minItems": 1, "items": STRING},
        "supporting_fact_ids": STRING_LIST,
        "rule_ids": STRING_LIST,
        "rejected_task_ids": STRING_LIST,
    },
}

_ACTION_GROUP = {
    "type": "object",
    "required": ["task_id", "members", "validation_objects", "comparison_basis",
                 "resolved_out", "unresolved"],
    "properties": {
        "task_id": {"type": ["string", "null"]},
        "members": STRING_LIST,
        "validation_objects": STRING_LIST,
        "comparison_basis": STRING_LIST,
        "resolved_out": STRING_LIST,
        "unresolved": STRING_LIST,
        "rule_ids": STRING_LIST,
    },
}

_PAIRWISE_ACTION = {
    "type": "object",
    "required": ["left_thscode", "right_thscode", "comparison_dimensions",
                 "left_advantages", "right_advantages", "unresolved",
                 "conclusion", "fact_ids", "evidence_refs", "evidence_families"],
    "properties": {
        "left_thscode": STRING,
        "right_thscode": STRING,
        "comparison_dimensions": {"type": "array", "minItems": 1, "items": STRING},
        "left_advantages": STRING_LIST,
        "right_advantages": STRING_LIST,
        "unresolved": STRING_LIST,
        "conclusion": {"type": "string", "enum": [
            "LEFT_PRIMARY", "RIGHT_PRIMARY", "CONDITIONAL", "NO_EDGE"]},
        "fact_ids": STRING_LIST,
        "evidence_refs": EVIDENCE_REFS,
        "evidence_families": {
            "type": "array", "minItems": 1,
            "items": {"type": "string", "enum": PAIR_EVIDENCE_FAMILIES},
        },
        "rule_ids": STRING_LIST,
    },
}

_ACTION_LEAF = {
    "type": ["object", "null"],
    "required": ["thscode", "task_id", "path_kind", "task_to_complete", "auction_conditions",
                 "open_conditions", "downgrade_conditions", "direct_fail_conditions"],
    "properties": {
        "thscode": STRING,
        "task_id": STRING,
        "path_kind": {"type": "string", "enum": ["PRIMARY", "ALTERNATIVE"]},
        "task_to_complete": STRING,
        "auction_conditions": {"type": "array", "minItems": 1, "items": STRING},
        "open_conditions": {"type": "array", "minItems": 1, "items": STRING},
        "downgrade_conditions": {"type": "array", "minItems": 1, "items": STRING},
        "direct_fail_conditions": {"type": "array", "minItems": 1, "items": STRING},
        "action_type": {"type": "string", "enum": [
            "LOW_ABSORB", "BREAKOUT_FOLLOW", "RESEAL",
            "TAIL_CONFIRMATION", "NO_ACTION", "DATA_INSUFFICIENT"]},
        "tail_event_trigger": STRING,
        "required_board_reflux": STRING,
        "required_breakout_state": STRING,
        "regulatory_condition": STRING,
        "latest_valid_time": STRING,
        "cancel_conditions": STRING_LIST,
    },
}

_ACTION_PLAN = {
    "type": "object",
    "required": ["status", "task_id", "primary", "backup", "validation_objects",
                 "switch_rule", "no_action_conditions"],
    "properties": {
        "status": {"type": "string", "enum": ["SINGLE", "CONDITIONAL_PAIR", "NO_ACTION"]},
        "task_id": {"type": ["string", "null"]},
        "primary": _ACTION_LEAF,
        "backup": _ACTION_LEAF,
        "validation_objects": STRING_LIST,
        "rule_ids": STRING_LIST,
        "switch_rule": STRING,
        "no_action_conditions": {"type": "array", "minItems": 1, "items": STRING},
    },
}

_TASK_SELECTION = {
    "type": "object",
    "required": ["path_kind", "status", "task_id", "task_type", "theme", "node_id",
                 "missing_function", "selection_logic", "supporting_fact_ids", "rule_ids",
                 "rejected_task_ids"],
    "properties": {
        "path_kind": {"type": "string", "enum": ["PRIMARY", "ALTERNATIVE"]},
        "status": {"type": "string", "enum": ["SELECTED", "NONE", "BLOCKED_DATA"]},
        "task_id": {"type": ["string", "null"]},
        "task_type": {"type": ["string", "null"]},
        "theme": {"type": ["string", "null"]},
        "node_id": {"type": ["string", "null"]},
        "missing_function": STRING,
        "selection_logic": {"type": "array", "minItems": 1, "items": STRING},
        "supporting_fact_ids": STRING_LIST,
        "rule_ids": STRING_LIST,
        "rejected_task_ids": STRING_LIST,
    },
}

STAGE_C1_SCHEMA = {
    "type": "object",
    "required": ["as_of", "decision_order", "primary_task", "alternative_task",
                 "no_action_conditions", "unknowns"],
    "properties": {
        "as_of": STRING,
        "decision_order": {"type": "array", "minItems": 4, "items": STRING},
        "primary_task": _TASK_SELECTION,
        "alternative_task": _TASK_SELECTION,
        "no_action_conditions": {"type": "array", "minItems": 1, "items": STRING},
        "unknowns": STRING_LIST,
    },
}

_PATH_ANALYSIS = {
    "type": "object",
    "required": _PATH_REQUIRED + ["confirm", "trigger", "cancel"],
    "properties": {**_PATH_COMMON, "confirm": STRING_LIST,
                   "trigger": STRING_LIST, "cancel": STRING_LIST},
}

_PATH_PLAN = {
    "type": "object",
    "required": ["path_kind", "execution_task", "path_analysis", "competition_group",
                 "pairwise_comparison", "action_plan", "candidates",
                 "excluded_candidates", "unknowns"],
    "properties": {
        "path_kind": {"type": "string", "enum": ["PRIMARY", "ALTERNATIVE"]},
        "execution_task": _EXECUTION_TASK,
        "path_analysis": _PATH_ANALYSIS,
        "competition_group": _COMPETITION_GROUP,
        "pairwise_comparison": {"type": "array", "items": _PAIRWISE_ACTION},
        "action_plan": _ACTION_PLAN,
        "candidates": {"type": "array", "items": _CANDIDATE},
        "excluded_candidates": {"type": "array", "items": _EXCLUDED_CANDIDATE},
        "unknowns": STRING_LIST,
    },
}

_ACTION_REF = {
    "type": ["object", "null"],
    "required": ["path_kind", "task_id", "thscode"],
    "properties": {
        "path_kind": {"type": "string", "enum": ["PRIMARY", "ALTERNATIVE"]},
        "task_id": STRING,
        "thscode": STRING,
    },
}

_FINAL_ACTION_PLAN = {
    "type": "object",
    "required": ["status", "primary_ref", "backup_ref", "switch_rule",
                 "no_action_conditions", "rule_ids"],
    "properties": {
        "status": {"type": "string", "enum": ["SINGLE", "CONDITIONAL_PAIR", "NO_ACTION"]},
        "primary_ref": _ACTION_REF,
        "backup_ref": _ACTION_REF,
        "switch_rule": STRING,
        "no_action_conditions": {"type": "array", "minItems": 1, "items": STRING},
        "rule_ids": STRING_LIST,
    },
}

STAGE_C_SCHEMA = {
    "type": "object",
    "required": ["as_of", "task_selection", "path_plans", "final_action_plan",
                 "unknowns"],
    "properties": {
        "as_of": STRING,
        "task_selection": {
            "type": "object",
            "required": ["primary_task", "alternative_task", "no_action_conditions"],
            "properties": {
                "primary_task": _TASK_SELECTION,
                "alternative_task": _TASK_SELECTION,
                "no_action_conditions": {"type": "array", "minItems": 1, "items": STRING},
            },
        },
        "path_plans": {"type": "array", "items": _PATH_PLAN},
        "final_action_plan": _FINAL_ACTION_PLAN,
        "unknowns": STRING_LIST,
    },
}

_STAGE_D_REASONING_TRACE = {
    "type": "object",
    "required": ["step_order", "market_and_path", "execution_node", "execution_nodes"],
    "properties": {
        "step_order": {"type": "array", "minItems": 3, "items": STRING},
        "market_and_path": {
            "type": "object", "required": ["status", "observed"],
            "properties": {
                "status": {"type": "string", "enum": [
                    "SUPPORTED", "REJECTED", "DATA_INSUFFICIENT"]},
                "observed": {"type": "array", "minItems": 1, "items": STRING},
            },
        },
        "execution_node": {
            "type": "object",
            "required": ["status", "task_id", "task_type", "theme", "anchor_date", "observed"],
            "properties": {
                "status": {"type": "string", "enum": [
                    "SUPPORTED", "REJECTED", "DATA_INSUFFICIENT"]},
                "task_id": {"type": ["string", "null"]},
                "task_type": {"type": ["string", "null"]},
                "theme": {"type": ["string", "null"]},
                "anchor_date": {"type": ["string", "null"]},
                "observed": {"type": "array", "minItems": 1, "items": STRING},
            },
        },
        "execution_nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["path_kind", "status", "task_id", "task_type", "theme",
                             "node_id", "anchor_date", "observed"],
                "properties": {
                    "path_kind": {"type": ["string", "null"]},
                    "status": {"type": "string", "enum": [
                        "SUPPORTED", "REJECTED", "DATA_INSUFFICIENT"]},
                    "task_id": {"type": ["string", "null"]},
                    "task_type": {"type": ["string", "null"]},
                    "theme": {"type": ["string", "null"]},
                    "node_id": {"type": ["string", "null"]},
                    "anchor_date": {"type": ["string", "null"]},
                    "observed": {"type": "array", "minItems": 1, "items": STRING},
                },
            },
        },
    },
}


STAGE_D_SCHEMA = {
    "type": "object",
    "required": ["tplus1", "snapshot", "as_of", "market_check", "reasoning_trace",
                 "auction_pair_comparison",
                 "context_check", "path_context_checks", "leaf_results",
                 "condition_tree_hit", "current_action_candidate", "next_stage",
                 "decision", "unknowns"],
    "properties": {
        "tplus1": STRING,
        "snapshot": {"type": "string", "enum": ["AUCTION_0925", "OPEN_0935"]},
        "as_of": STRING,
        "market_check": {
            "type": "object", "required": ["index_held", "note"],
            "properties": {"index_held": {"type": ["boolean", "null"]}, "note": STRING},
        },
        "reasoning_trace": _STAGE_D_REASONING_TRACE,
        "auction_pair_comparison": {
            "type": "object",
            "required": ["status", "stronger_code", "weaker_code", "comparison_text"],
            "properties": {
                "status": {"type": "string", "enum": [
                    "AVAILABLE", "DATA_INSUFFICIENT", "NOT_APPLICABLE"]},
                "stronger_code": {"type": ["string", "null"]},
                "weaker_code": {"type": ["string", "null"]},
                "comparison_text": STRING,
            },
        },
        "context_check": {
            "type": "object",
            "required": ["validation_objects", "status", "observed"],
            "properties": {
                "validation_objects": STRING_LIST,
                "status": {"type": "string", "enum": [
                    "CONFIRMS", "REJECTS", "UNRESOLVED", "DATA_INSUFFICIENT",
                    "NOT_REQUIRED"]},
                "observed": STRING_LIST,
            },
        },
        "path_context_checks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["path_kind", "task_id", "node_id", "validation_objects",
                             "status", "observed"],
                "properties": {
                    "path_kind": {"type": ["string", "null"]},
                    "task_id": STRING,
                    "node_id": {"type": ["string", "null"]},
                    "validation_objects": STRING_LIST,
                    "status": {"type": "string", "enum": [
                        "CONFIRMS", "REJECTS", "UNRESOLVED", "DATA_INSUFFICIENT",
                        "NOT_REQUIRED"]},
                    "observed": STRING_LIST,
                },
            },
        },
        "leaf_results": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["thscode", "leaf_id", "tier", "task_id", "anchor_date",
                             "current_function", "entry_event", "exit_conditions", "leaf_state",
                             "observed", "vs_plan", "reason"],
                "properties": {
                    "thscode": STRING, "leaf_id": STRING,
                    "tier": {"type": "string", "enum": ["PRIMARY", "BACKUP"]},
                    "path_kind": {"type": ["string", "null"]},
                    "task_id": STRING,
                    "node_id": {"type": ["string", "null"]},
                    "anchor_date": {"type": "string", "format": "date"},
                    "stock_start_date": {"type": ["string", "null"]},
                    "current_function": STRING,
                    "entry_event": {"type": "array", "minItems": 1, "items": STRING},
                    "exit_conditions": {"type": "array", "minItems": 1, "items": STRING},
                    "leaf_state": {"type": "string", "enum": [
                        "MEETS_AUCTION_TASK", "NEEDS_OPEN_VALIDATION", "DOWNGRADED",
                        "DIRECT_FAIL", "MEETS_OPEN_TASK", "OPEN_TASK_FAILED",
                        "DATA_INSUFFICIENT"]},
                    "observed": STRING_LIST,
                    "vs_plan": STRING, "reason": STRING_LIST,
                },
            },
        },
        "condition_tree_hit": {
            "type": "object", "required": ["branch", "primary_state", "backup_state",
                                             "reasoning"],
            "properties": {
                "branch": {"type": "string", "enum": [
                    "PRIMARY_CONTINUES", "PRIMARY_DIRECT_FAIL_BACKUP_CONTINUES",
                    "PRIMARY_DOWNGRADED_NO_SWITCH", "BOTH_FAIL", "DATA_BLOCKED",
                    "CONTEXT_REJECTS", "OPEN_CONFIRM", "OPEN_REJECT", "NO_CANDIDATE"]},
                "primary_state": {"type": ["string", "null"]},
                "backup_state": {"type": ["string", "null"]},
                "reasoning": {"type": "array", "minItems": 1, "items": STRING},
            },
        },
        "current_action_candidate": {"type": ["string", "null"]},
        "next_stage": {"type": "string", "enum": ["OPEN_0935", "STOP", "COMPLETE"]},
        "decision": {"type": "string", "enum": [
            "WAIT_OPEN_VALIDATION", "BUY", "NO_ACTION", "DATA_INSUFFICIENT"]},
        "unknowns": STRING_LIST,
    },
}

_VALIDATION_TRACE_ROW = {
    "type": "object",
    "required": ["step_id", "status", "observed", "fact_ids", "judgment"],
    "properties": {
        "step_id": STRING,
        "status": {"type": "string", "enum": [
            "CONFIRMS", "PARTIAL", "REJECTS", "DATA_INSUFFICIENT",
            "NOT_APPLICABLE"]},
        "observed": STRING_LIST,
        "fact_ids": STRING_LIST,
        "judgment": STRING,
    },
}

M4_AUCTION_SCHEMA = {
    "type": "object",
    "required": ["tplus1", "snapshot", "as_of", "auction_read_order",
                 "path_results", "backup_independence_check",
                 "condition_tree_hit", "current_action_candidate", "next_stage",
                 "decision", "method_trace", "unknowns"],
    "properties": {
        "tplus1": STRING,
        "snapshot": {"type": "string", "enum": ["AUCTION_0925"]},
        "as_of": STRING,
        "auction_read_order": {
            "type": "array", "minItems": 3, "items": {"type": "string", "enum": [
                "09:15_INITIAL_DISPLAY", "09:20_ORDER_RETENTION_DECAY",
                "09:25_FINAL_MATCH"]}
        },
        "path_results": {
            "type": "array", "items": {
                "type": "object",
                "required": ["thscode", "tier", "path_kind", "task_id",
                             "auction_status", "self_vs_yesterday",
                             "same_group_opponents", "board_capacity_context",
                             "tradability", "observed", "reject_reasons"],
                "properties": {
                    "thscode": STRING,
                    "tier": {"type": "string", "enum": ["PRIMARY", "BACKUP"]},
                    "path_kind": {"type": ["string", "null"]},
                    "task_id": STRING,
                    "auction_status": {"type": "string", "enum": [
                        "AUCTION_CONFIRMS_PATH", "AUCTION_NEEDS_OPEN_VALIDATION",
                        "AUCTION_REJECTS_PATH", "DATA_INSUFFICIENT"]},
                    "self_vs_yesterday": STRING_LIST,
                    "same_group_opponents": STRING_LIST,
                    "board_capacity_context": STRING_LIST,
                    "tradability": STRING_LIST,
                    "observed": STRING_LIST,
                    "reject_reasons": STRING_LIST,
                },
            },
        },
        "backup_independence_check": {
            "type": "object", "required": ["available", "status", "observed"],
            "properties": {
                "available": {"type": "boolean"},
                "status": {"type": "string", "enum": [
                    "INDEPENDENTLY_ESTABLISHED", "NOT_ESTABLISHED",
                    "NOT_APPLICABLE", "DATA_INSUFFICIENT"]},
                "observed": STRING_LIST,
            },
        },
        "condition_tree_hit": STAGE_D_SCHEMA["properties"]["condition_tree_hit"],
        "current_action_candidate": {"type": ["string", "null"]},
        "next_stage": {"type": "string", "enum": ["OPEN_0935", "STOP"]},
        "decision": {"type": "string", "enum": [
            "WAIT_OPEN_VALIDATION", "NO_ACTION", "DATA_INSUFFICIENT"]},
        "method_trace": {"type": "array", "minItems": 4, "items": _VALIDATION_TRACE_ROW},
        "unknowns": STRING_LIST,
    },
}

M5_OPEN_ACTION_SCHEMA = {
    "type": "object",
    "required": ["tplus1", "snapshot", "as_of", "current_action_candidate",
                 "open_validation", "action_trigger", "decision",
                 "method_trace", "unknowns"],
    "properties": {
        "tplus1": STRING,
        "snapshot": {"type": "string", "enum": ["OPEN_0935"]},
        "as_of": STRING,
        "current_action_candidate": {"type": ["string", "null"]},
        "open_validation": {
            "type": "object",
            "required": ["sell_pressure_path", "stop_weakening",
                         "same_group_event_order", "board_response", "conclusion"],
            "properties": {
                "sell_pressure_path": STRING_LIST,
                "stop_weakening": STRING_LIST,
                "same_group_event_order": STRING_LIST,
                "board_response": STRING_LIST,
                "conclusion": {"type": "string", "enum": [
                    "OPEN_CONFIRMS", "NEEDS_FURTHER_VALIDATION",
                    "OPEN_REJECTS", "DATA_INSUFFICIENT"]},
            },
        },
        "action_trigger": {
            "type": "object",
            "required": ["method", "method_trace", "thscode", "reason"],
            "properties": {
                "method": {"type": "string", "enum": [
                    "LOW_ABSORB", "BREAKOUT_FOLLOW", "RESEAL",
                    "TAIL_CONFIRMATION", "CLOSE_CONFIRM", "NONE"]},
                "method_trace": STRING_LIST,
                "thscode": {"type": ["string", "null"]},
                "reason": STRING_LIST,
            },
        },
        "decision": {"type": "string", "enum": [
            "BUY", "NO_ACTION", "WAIT_CLOSE_CONFIRM", "DATA_INSUFFICIENT"]},
        "method_trace": {"type": "array", "minItems": 5, "items": _VALIDATION_TRACE_ROW},
        "unknowns": STRING_LIST,
    },
}

CLOSE_REVIEW_SCHEMA = {
    "type": "object",
    "required": ["tplus1", "plan_date", "task_results", "role_migrations",
                 "holding_reviews", "exit_reviews", "next_ledger_patch", "unknowns"],
    "properties": {
        "tplus1": STRING,
        "plan_date": STRING,
        "task_results": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["thscode", "task_id", "status", "evidence",
                             "evidence_refs", "failed_conditions"],
                "properties": {
                    "thscode": STRING,
                    "task_id": STRING,
                    "status": {"type": "string", "enum": [
                        "COMPLETED", "FAILED", "CANCELLED", "DATA_INSUFFICIENT",
                        "NOT_TRIGGERED"]},
                    "evidence": STRING_LIST,
                    "evidence_refs": EVIDENCE_REFS,
                    "failed_conditions": STRING_LIST,
                },
            },
        },
        "role_migrations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["thscode", "previous_role", "new_role", "status",
                             "evidence", "evidence_refs", "counter_evidence",
                             "counter_evidence_refs"],
                "properties": {
                    "thscode": STRING,
                    "previous_role": {"type": ["string", "null"]},
                    "new_role": {"type": ["string", "null"]},
                    "status": {"type": "string", "enum": [
                        "UNCHANGED", "UPGRADED", "DOWNGRADED", "REPLACED",
                        "CANCELLED", "DATA_INSUFFICIENT"]},
                    "evidence": STRING_LIST,
                    "evidence_refs": EVIDENCE_REFS,
                    "counter_evidence": STRING_LIST,
                    "counter_evidence_refs": EVIDENCE_REFS,
                },
            },
        },
        "holding_reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["thscode", "task_id"] + list(contracts.HOLDING_CHECK_FIELDS),
                "properties": {
                    "thscode": STRING,
                    "task_id": STRING,
                    **{field: _REASONED_FIELD for field in contracts.HOLDING_CHECK_FIELDS},
                },
            },
        },
        "exit_reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["thscode", "decision", "exit_reason", "exit_style",
                             "reason", "rule_ids"],
                "properties": {
                    "thscode": STRING,
                    "decision": {"type": "string", "enum": [
                        "HOLD", "EXIT", "REDUCE", "NO_POSITION", "DATA_INSUFFICIENT"]},
                    "exit_reason": {"type": "string", "enum": list(contracts.EXIT_REASONS)},
                    "exit_style": {"type": "string", "enum": list(contracts.EXIT_STYLES)},
                    "reason": STRING_LIST,
                    "rule_ids": STRING_LIST,
                },
            },
        },
        "next_ledger_patch": {
            "type": "object",
            "required": ["environment", "directions", "nodes", "roles",
                         "competition_groups", "no_action_conditions"],
            "properties": {
                "environment": {"type": ["object", "null"]},
                "directions": {"type": "array", "items": {"type": "object"}},
                "nodes": {"type": "array", "items": {"type": "object"}},
                "roles": {"type": "array", "items": {"type": "object"}},
                "competition_groups": {"type": "array", "items": {"type": "object"}},
                "no_action_conditions": STRING_LIST,
            },
        },
        "unknowns": STRING_LIST,
    },
}

VTAIL_SCHEMA = {
    "type": "object",
    "required": ["tplus1", "snapshot", "as_of", "current_action_candidate",
                 "tail_event_validation", "decision", "method_trace", "unknowns"],
    "properties": {
        "tplus1": STRING,
        "snapshot": {"type": "string", "enum": ["VTAIL"]},
        "as_of": STRING,
        "current_action_candidate": {"type": ["string", "null"]},
        "tail_event_validation": {
            "type": "object",
            "required": ["tail_event_trigger", "required_board_reflux",
                         "required_breakout_state", "regulatory_condition",
                         "latest_valid_time", "cancel_conditions", "conclusion",
                         "observed"],
            "properties": {
                "tail_event_trigger": STRING,
                "required_board_reflux": STRING,
                "required_breakout_state": STRING,
                "regulatory_condition": STRING,
                "latest_valid_time": STRING,
                "cancel_conditions": STRING_LIST,
                "conclusion": {"type": "string", "enum": [
                    "TAIL_CONFIRMS", "TAIL_REJECTS", "DATA_INSUFFICIENT"]},
                "observed": STRING_LIST,
            },
        },
        "decision": {"type": "string", "enum": [
            "BUY", "NO_ACTION", "DATA_INSUFFICIENT"]},
        "method_trace": {"type": "array", "minItems": 4, "items": _VALIDATION_TRACE_ROW},
        "unknowns": STRING_LIST,
    },
}

AUDIT_SCHEMA = {
    "type": "object",
    "required": ["verdict", "violations", "counter_arguments"],
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "NEEDS_REVISION"]},
        "violations": STRING_LIST,
        "counter_arguments": STRING_LIST,
    },
}
