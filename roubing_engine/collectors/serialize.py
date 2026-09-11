"""Convert eltdx objects to plain list[dict] rows with discipline columns.

Discipline columns (per the plan's immutable-fact layer):
  thscode, trade_date, source, fetched_at
Object-native event time is preserved (event_time / time_label).
"""
from __future__ import annotations

from datetime import datetime, timezone

from roubing_engine.collectors.eltdx_client import to_thscode
from roubing_engine.warehouse.timebox import iso_at, row_seconds, session_type


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pick(obj, fields):
    return {f: getattr(obj, f, None) for f in fields}


def _stamp(rows, thscode, trade_date, default_seconds: int | None = None):
    fetched = _now_iso()
    for r in rows:
        r["thscode"] = thscode
        r["trade_date"] = trade_date
        r["source"] = "eltdx"
        r["fetched_at"] = fetched
        seconds = row_seconds(r)
        if seconds is None:
            seconds = default_seconds
        if seconds is not None:
            r["event_time"] = iso_at(trade_date, seconds)
            # Exchange data is knowable no earlier than its own event time.
            r["available_at"] = r["event_time"]
    return rows


AUCTION_FIELDS = [
    "index", "time_label", "time_seconds", "price",
    "matched_volume", "matched_amount_estimated",
    "unmatched_volume", "unmatched_signed_raw", "unmatched_direction_raw",
]
OPENING_FIELDS = [
    "time_label", "trade_datetime", "price", "volume", "order_count",
    "trade_amount_yuan", "event_kind",
]
MINUTE_FIELDS = ["index", "time_label", "time", "price", "avg_price", "volume"]
TRADE_FIELDS = [
    "absolute_index", "index", "time_label", "trade_datetime", "price",
    "volume", "side", "event_kind", "is_actual_trade", "order_count",
    "trade_amount_yuan", "status_raw",
]
UNIVERSE_FIELDS = [
    "full_code", "code", "name", "status", "board_level", "highest_board_level",
    "consecutive_limit_days", "industry", "reason", "limit_reason_extra",
    "seal_amount", "limit_time", "broken_count",
]


def serialize_auction(auction, thscode, trade_date):
    rows = []
    if auction and auction.series and auction.series.points:
        rows = [_pick(p, AUCTION_FIELDS) for p in auction.series.points]
        for row in rows:
            row["session_type"] = session_type(row_seconds(row))
    return _stamp(rows, thscode, trade_date)


def serialize_opening(auction, thscode, trade_date):
    rows = []
    snap = getattr(auction, "snapshot_0925", None) if auction else None
    if snap and getattr(snap, "price", None) is not None:
        row = _pick(snap, OPENING_FIELDS)
        # enrich with auction-level context needed for 竞价高开幅/强度
        row["pre_close_price"] = getattr(auction, "pre_close_price", None)
        row["open_price"] = getattr(auction, "open_price", None)
        row["open_change_pct"] = getattr(auction, "open_change_pct", None)
        row["open_amount"] = getattr(auction, "open_amount", None)
        rows = [row]
    return _stamp(rows, thscode, trade_date, default_seconds=9 * 3600 + 25 * 60)


def serialize_minutes(minute_series, thscode, trade_date):
    rows = []
    if minute_series and getattr(minute_series, "points", None):
        rows = [_pick(p, MINUTE_FIELDS) for p in minute_series.points]
    return _stamp(rows, thscode, trade_date)


def serialize_trades(trade_page, thscode, trade_date):
    rows = []
    if trade_page and getattr(trade_page, "ticks", None):
        rows = [_pick(t, TRADE_FIELDS) for t in trade_page.ticks]
    return _stamp(rows, thscode, trade_date)


def serialize_universe(rows_obj, trade_date):
    out = []
    for r in (rows_obj or []):
        d = _pick(r, UNIVERSE_FIELDS)
        full = d.get("full_code")
        d["thscode"] = to_thscode(full) if full else None
        d["trade_date"] = trade_date
        d["source"] = "eltdx"
        d["fetched_at"] = _now_iso()
        # The daily limit roster is only used by the close-stage reasoning.
        d["event_time"] = iso_at(trade_date, 15 * 3600)
        d["available_at"] = d["event_time"]
        out.append(d)
    return out
