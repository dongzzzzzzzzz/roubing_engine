"""Intraday capture schedule contract for roubing replay/live collection."""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class CaptureJob:
    job_id: str
    phase: str
    scheduled_time: str
    datasets: tuple[str, ...]
    scope: str
    trigger: str
    reason: str

    def to_dict(self) -> dict:
        row = asdict(self)
        row["datasets"] = list(self.datasets)
        return row


DAILY_CAPTURE_TIMELINE: tuple[CaptureJob, ...] = (
    CaptureJob(
        "PREMARKET_PREV_CLOSE", "PREMARKET", "08:45:00",
        ("stock_daily_bar", "index_daily_bar", "limit_event", "theme_fact_daily",
         "board_membership_snapshot", "announcement", "rule_version"),
        "previous_trade_day_full_market",
        "scheduled",
        "补齐上一交易日日线、涨跌停、涨停原因、板块、公告和有效规则",
    ),
    CaptureJob(
        "AUCTION_0915_INITIAL", "AUCTION", "09:15:00",
        ("auction_point",),
        "frozen_candidates_and_same_task_peers",
        "scheduled",
        "冻结初始竞价强度和同组排名",
    ),
    CaptureJob(
        "AUCTION_0920_POST_CANCEL", "AUCTION", "09:20:00",
        ("auction_point", "depth_snapshot"),
        "frozen_candidates_and_same_task_peers",
        "scheduled",
        "保存撤单后状态、匹配量、未匹配量和排名迁移",
    ),
    CaptureJob(
        "OPENING_0925_MATCH", "OPENING_MATCH", "09:25:01",
        ("opening_match", "auction_point"),
        "frozen_candidates_same_task_peers_and_validation_objects",
        "scheduled",
        "保存正式开盘价、量、额和最终竞价结构",
    ),
    CaptureJob(
        "OPEN_0930_0935_CONTEXT", "OPEN_WINDOW", "09:35:00",
        ("minute_bar", "trade_tick", "depth_snapshot", "index_daily_bar"),
        "candidates_peers_validation_board_capacity",
        "scheduled",
        "保存候选及对手分钟、成交、五档、板块和容量响应",
    ),
    CaptureJob(
        "CLOSE_FINAL_STATE", "CLOSE", "15:05:00",
        ("stock_daily_bar", "index_daily_bar", "limit_event", "theme_fact_daily",
         "board_membership_snapshot", "announcement"),
        "full_market_and_active_directions",
        "scheduled",
        "保存最终日线、板块、市场宽度、涨跌停、原因和公告",
    ),
)

EVENT_SNAPSHOT_TRIGGERS = {
    "LIMIT_UP": ("minute_bar", "trade_tick", "depth_snapshot"),
    "BROKEN_LIMIT": ("minute_bar", "trade_tick", "depth_snapshot"),
    "RESEAL": ("minute_bar", "trade_tick", "depth_snapshot"),
    "BOARD_SPIKE": ("minute_bar", "trade_tick", "depth_snapshot", "index_daily_bar"),
    "BOARD_DUMP": ("minute_bar", "trade_tick", "depth_snapshot", "index_daily_bar"),
}


def event_snapshot_job(trade_date: str, event_type: str, event_time: str,
                       scope: str = "event_code_and_related_board") -> dict:
    datasets = EVENT_SNAPSHOT_TRIGGERS.get(event_type)
    if datasets is None:
        raise ValueError(f"unsupported event snapshot trigger: {event_type}")
    return CaptureJob(
        f"EVENT_{trade_date}_{event_type}_{event_time.replace(':', '')}",
        "EVENT_SNAPSHOT",
        event_time,
        datasets,
        scope,
        event_type,
        "上板、炸板、回封、板块急拉急跌时保存事件快照",
    ).to_dict()


def daily_jobs(trade_date: str) -> list[dict]:
    rows = []
    for job in DAILY_CAPTURE_TIMELINE:
        row = job.to_dict()
        row["trade_date"] = trade_date
        rows.append(row)
    return rows


def validate_schedule(jobs: list[dict]) -> list[str]:
    required_ids = {job.job_id for job in DAILY_CAPTURE_TIMELINE}
    seen = {job.get("job_id") for job in jobs}
    missing = sorted(required_ids - seen)
    violations = [f"capture schedule missing {job_id}" for job_id in missing]
    for job in jobs:
        if job.get("phase") == "EVENT_SNAPSHOT" and job.get("trigger") not in EVENT_SNAPSHOT_TRIGGERS:
            violations.append(f"unsupported event snapshot trigger: {job.get('trigger')}")
        if not job.get("datasets"):
            violations.append(f"{job.get('job_id')}: datasets cannot be empty")
        if not job.get("scheduled_time"):
            violations.append(f"{job.get('job_id')}: scheduled_time required")
    return violations
