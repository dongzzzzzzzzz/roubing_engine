"""Reasoning-pack protocol definitions for the roubing model pipeline.

The protocol layer names the questions every model pack must answer.  It does
not encode market answers; schemas and audits use these ids to verify coverage.
"""
from __future__ import annotations

from dataclasses import dataclass


TRACE_STATUSES = ["APPLICABLE", "NOT_APPLICABLE", "DATA_INSUFFICIENT"]

ENVIRONMENT_HYPOTHESES = [
    "MAIN_TREND",
    "ROTATION",
    "DECLINE",
    "REGIME_SWITCH",
]

STAGE1_OBSERVATIONS = [
    ("S1-INDEX-TREND", "指数处于上升、震荡还是快速下跌"),
    ("S1-TOTAL_TURNOVER_SUPPORT", "总成交是否支持大资金持续进攻"),
    ("S1-LARGE_CAP_BUYER_FEEDBACK", "大成交股票是否持续给买方正反馈"),
    ("S1-YESTERDAY_STRONG_FEEDBACK", "昨日强势股是延续、分化、被核还是连续跌停"),
    ("S1-PROFIT_EFFECT_SPREAD", "赚钱效应集中在核心还是向板块扩散"),
    ("S1-OLD_NEW_TAKEOVER", "旧主流是否有承接，新方向是否形成替代"),
]

LIFECYCLE_STAGES = [
    "RANDOM_HOTSPOT",
    "LAUNCH_TEST",
    "CONTINUATION_CANDIDATE",
    "MAINSTREAM_CONFIRMED",
    "FIRST_OR_MAJOR_DIVERGENCE",
    "REPAIR",
    "OSCILLATION_OR_SECOND_WAVE",
    "DECLINE_OR_ENDED",
]

GENERATORS = [
    ("G1", "持续退潮后的情绪高度破局"),
    ("G2", "G1形成日的低位伴飞"),
    ("G3", "首波伴飞升级为二波载体"),
    ("G4", "总龙首次断板日补涨"),
    ("G5", "二波首次分歧日低位伴生"),
    ("G6", "已有主流大分歧后的修复核心"),
    ("G7", "大成交后仍推进并带动的容量核心"),
    ("G8", "同起算日、同功能候选的唯一性"),
    ("G9", "主线仍有效时旧新核心切换"),
    ("G10", "高位受限后的高低与空间迁移"),
    ("G11", "恐慌、底部修复中的主动带动者"),
    ("G12", "已突破核心的第一次主动分歧"),
]

NODE_QUESTION_FIELDS = [
    "prior_state",
    "prior_resistance",
    "changed_facts",
    "benefited_function",
    "anchor_date",
    "natural_candidate_scope",
    "confirm",
    "cancel",
]


@dataclass(frozen=True)
class ReasoningPack:
    pack_id: str
    name: str
    stage_range: str
    core_reasoning_effort: str
    audit_reasoning_effort: str


PACKS = {
    "M1": ReasoningPack("M1", "环境+方向", "Stage 0-2", "high", "medium"),
    "M2": ReasoningPack("M2", "节点", "Stage 3", "high", "medium"),
    "M3": ReasoningPack("M3", "角色+竞争+计划", "Stage 4-7", "high", "medium"),
    "M4": ReasoningPack("M4", "竞价", "Stage 8", "high", "medium"),
    "M5": ReasoningPack("M5", "开盘+动作", "Stage 9-10", "high", "medium"),
    "M6": ReasoningPack("M6", "收盘复盘", "Stage 11", "high", "medium"),
}


def expected_stage1_step_ids() -> list[str]:
    ids = [item[0] for item in STAGE1_OBSERVATIONS]
    ids.extend(f"S1-HYPOTHESIS-{name}" for name in ENVIRONMENT_HYPOTHESES)
    return ids


def expected_generator_ids() -> list[str]:
    return [item[0] for item in GENERATORS]
