"""Strict structural contracts for every reasoning stage.

The format is a deliberately small JSON-Schema subset implemented by
``runner.validate``.  Keeping it dependency-free makes the guardrail available
even in capture-only/offline environments.
"""

STRING = {"type": "string", "minLength": 1}
STRING_LIST = {"type": "array", "items": STRING}

ENVIRONMENTS = ["MAIN_TREND", "ROTATION", "DECLINE", "REGIME_SWITCH"]
GENERATORS = [f"G{i}" for i in range(1, 13)]
ROLES = [
    "总核心", "容量核心", "情绪核心", "分支核心", "助攻伴飞", "补涨",
    "低位伴生", "二波载体", "旧核心残余", "跟风", "UNKNOWN",
]
OUTPUT_TIERS = ["主候选", "待验证候选", "替代候选", "取消或不行动"]

STAGE_B_SCHEMA = {
    "type": "object",
    "required": ["as_of", "environment", "mainstream_directions", "nodes", "data_gaps"],
    "properties": {
        "as_of": STRING,
        "environment": {
            "type": "object",
            "required": ["candidate", "supporting", "counter", "migrated_from", "tomorrow_checks"],
            "properties": {
                "candidate": {"type": "string", "enum": ENVIRONMENTS},
                "supporting": STRING_LIST,
                "counter": STRING_LIST,
                "migrated_from": {"type": ["string", "null"]},
                "tomorrow_checks": STRING_LIST,
            },
        },
        "mainstream_directions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["theme", "stage", "supporting", "counter", "competitors"],
                "properties": {
                    "theme": STRING,
                    "stage": STRING,
                    "supporting": STRING_LIST,
                    "counter": STRING_LIST,
                    "competitors": STRING_LIST,
                },
            },
        },
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["node_type", "anchor_date", "theme", "trigger_facts",
                             "generator", "candidate_ids", "confirm", "cancel"],
                "properties": {
                    "node_type": STRING,
                    "anchor_date": {"type": "string", "format": "date"},
                    "theme": {"type": ["string", "null"]},
                    "trigger_facts": STRING_LIST,
                    "generator": {"type": ["string", "null"], "enum": GENERATORS + [None]},
                    "candidate_ids": STRING_LIST,
                    "confirm": STRING_LIST,
                    "cancel": STRING_LIST,
                },
            },
        },
        "data_gaps": STRING_LIST,
    },
}

CANDIDATE_REQUIRED = [
    "thscode", "theme", "node", "generator", "anchor_date", "role",
    "letter_carrier", "competition_group", "competitors", "observed_state",
    "tomorrow_must_do", "acceptable_variants", "failure_signals", "cancel_if",
    "output_tier", "evidence",
]

_CANDIDATE = {
    "type": "object",
    "required": CANDIDATE_REQUIRED,
    "properties": {
        "thscode": STRING,
        "theme": STRING,
        "node": STRING,
        "generator": {"type": "string", "enum": GENERATORS},
        "anchor_date": {"type": "string", "format": "date"},
        "role": {"type": "string", "enum": ROLES},
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
    },
}

_COMPETITION_GROUP = {
    "type": "object",
    "required": ["group_id", "comparison_basis", "members", "not_comparable_with",
                 "leader_state", "pairwise_relations", "next_confirmation"],
    "properties": {
        "group_id": STRING,
        "comparison_basis": {"type": "array", "minItems": 1, "items": STRING},
        "members": {"type": "array", "minItems": 1, "items": STRING},
        "not_comparable_with": STRING_LIST,
        "leader_state": STRING,
        "pairwise_relations": STRING_LIST,
        "next_confirmation": STRING_LIST,
    },
}

_EXCLUDED_CANDIDATE = {
    "type": "object",
    "required": ["thscode", "generator", "anchor_date", "reason"],
    "properties": {
        "thscode": STRING,
        "generator": {"type": "string", "enum": GENERATORS},
        "anchor_date": {"type": "string", "format": "date"},
        "reason": STRING,
    },
}

STAGE_C_SCHEMA = {
    "type": "object",
    "required": ["as_of", "paths", "competition_groups", "candidates",
                 "excluded_candidates", "unknowns"],
    "properties": {
        "as_of": STRING,
        "competition_groups": {"type": "array", "items": _COMPETITION_GROUP},
        "candidates": {"type": "array", "items": _CANDIDATE},
        "excluded_candidates": {"type": "array", "items": _EXCLUDED_CANDIDATE},
        "paths": {
            "type": "object",
            "required": ["primary", "alternative", "no_action"],
            "properties": {
                "primary": {
                    "type": "object", "required": ["desc", "confirm", "cancel"],
                    "properties": {"desc": STRING, "confirm": STRING_LIST, "cancel": STRING_LIST},
                },
                "alternative": {
                    "type": "object", "required": ["desc", "trigger", "cancel"],
                    "properties": {"desc": STRING, "trigger": STRING_LIST, "cancel": STRING_LIST},
                },
                "no_action": {
                    "type": "object", "required": ["trigger"],
                    "properties": {"trigger": STRING_LIST},
                },
            },
        },
        "unknowns": STRING_LIST,
    },
}

STAGE_D_SCHEMA = {
    "type": "object",
    "required": ["tplus1", "snapshot", "as_of", "market_check", "candidate_results",
                 "path_outcome", "unknowns"],
    "properties": {
        "tplus1": STRING,
        "snapshot": {"type": "string", "enum": ["AUCTION_0925", "OPEN_0935"]},
        "as_of": STRING,
        "market_check": {
            "type": "object", "required": ["index_held", "note"],
            "properties": {"index_held": {"type": ["boolean", "null"]}, "note": STRING},
        },
        "candidate_results": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["thscode", "plan_tier", "auction_conclusion",
                             "open5m_conclusion", "final_status", "observed", "vs_plan", "reason"],
                "properties": {
                    "thscode": STRING, "plan_tier": STRING,
                    "auction_conclusion": {"type": "string", "enum": [
                        "AUCTION_CONFIRMED", "AUCTION_NEEDS_OPEN_VALIDATION",
                        "AUCTION_DOWNGRADED", "ALTERNATIVE_TAKES_OVER", "CANCELLED",
                        "DATA_INSUFFICIENT"]},
                    "open5m_conclusion": {"type": "string", "enum": [
                        "CONFIRMED", "CONTINUE_OBSERVE", "DOWNGRADED", "REPLACED",
                        "CANCELLED", "DATA_INSUFFICIENT"]},
                    "final_status": {"type": "string", "enum": [
                        "确认", "降级", "替代接管", "取消", "数据不足", "继续观察"]},
                    "observed": STRING_LIST,
                    "vs_plan": STRING, "reason": STRING_LIST,
                },
            },
        },
        "path_outcome": {
            "type": "object", "required": ["primary", "alternative", "no_action"],
            "properties": {"primary": STRING, "alternative": STRING, "no_action": STRING},
        },
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
