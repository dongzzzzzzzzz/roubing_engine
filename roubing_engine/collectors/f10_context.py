"""Serialize F10 announcements and topic facts with historical availability."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from roubing_engine.config import TZ


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_shanghai(value) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y%m%d"):
        try:
            return dt.datetime.strptime(text, fmt).replace(tzinfo=ZoneInfo(TZ))
        except ValueError:
            continue
    return None


def _as_of_close(trade_date: str) -> dt.datetime:
    raw = trade_date.replace("-", "")
    return dt.datetime(int(raw[:4]), int(raw[4:6]), int(raw[6:8]), 15, 0,
                       tzinfo=ZoneInfo(TZ))


def serialize_announcements(response, thscode: str, trade_date: str) -> list[dict]:
    fetched = _now()
    cutoff = _as_of_close(trade_date)
    rows = []
    for source_row in (getattr(response, "rows", None) or []):
        row = dict(source_row)
        published = _parse_shanghai(row.get("redistime") or row.get("issue_date"))
        if published is None or published > cutoff:
            continue
        event = _parse_shanghai(row.get("issue_date")) or published
        rows.append({
            "thscode": thscode,
            "trade_date": trade_date.replace("-", ""),
            "rec_id": row.get("rec_id"),
            "title": row.get("title"),
            "announcement_type": row.get("typename"),
            "type_code": row.get("typecode"),
            "url": row.get("url"),
            "publisher_source": row.get("source"),
            "event_time": event.isoformat(),
            "available_at": published.isoformat(),
            "source": "eltdx_f10",
            "fetched_at": fetched.isoformat(),
        })
    return rows


def serialize_hot_topics(response, thscode: str, trade_date: str) -> list[dict]:
    fetched = _now()
    # F10 topic membership is a current snapshot.  Its availability is fetch
    # time, never backdated to a historical replay date.
    rows = []
    for source_row in (getattr(response, "rows", None) or []):
        row = dict(source_row)
        rows.append({
            "thscode": thscode,
            "trade_date": trade_date.replace("-", ""),
            "topic_id": row.get("id"),
            "topic_name": row.get("ztmc"),
            "topic_detail": row.get("ztnr"),
            "relation_strength_raw": row.get("gld"),
            "event_time": fetched.isoformat(),
            "available_at": fetched.isoformat(),
            "source": "eltdx_f10_current_snapshot",
            "fetched_at": fetched.isoformat(),
            "historical_safe": False,
            "discipline": "当前题材快照不得回填 fetched_at 之前的历史日期",
        })
    return rows


def capture_code(client, thscode: str, trade_date: str,
                 datasets: list[str]) -> tuple[dict[str, list[dict]], dict[str, str]]:
    numeric_code = thscode.split(".", 1)[0]
    data: dict[str, list[dict]] = {}
    status: dict[str, str] = {}
    if "announcement" in datasets:
        try:
            response = client.f10.announcements(numeric_code)
            rows = serialize_announcements(response, thscode, trade_date)
            data["announcement"] = rows
            status["announcement"] = "ok" if rows else "empty"
        except Exception as exc:  # noqa: BLE001
            status["announcement"] = f"error:{type(exc).__name__}"
    if "hot_topic" in datasets:
        try:
            response = client.f10.hot_topics(numeric_code)
            rows = serialize_hot_topics(response, thscode, trade_date)
            data["hot_topic"] = rows
            status["hot_topic"] = "ok" if rows else "empty"
        except Exception as exc:  # noqa: BLE001
            status["hot_topic"] = f"error:{type(exc).__name__}"
    return data, status

