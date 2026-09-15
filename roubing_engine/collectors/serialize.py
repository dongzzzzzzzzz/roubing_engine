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


def _eltdx_code(thscode: str) -> str:
    return str(thscode).split(".")[0]


def _stamp(rows, thscode, trade_date, dataset: str,
           default_seconds: int | None = None):
    fetched = _now_iso()
    for index, r in enumerate(rows):
        r["thscode"] = thscode
        r["eltdx_code"] = _eltdx_code(thscode)
        r["trade_date"] = trade_date
        r["source"] = "eltdx"
        r["interface"] = dataset
        r["fetched_at"] = fetched
        r["request_id"] = (
            f"eltdx:{dataset}:{thscode}:{trade_date}:"
            f"{r.get('time_label') or r.get('trade_datetime') or index}"
        )
        if "volume" in r and "volume_unit" not in r:
            r["volume_unit"] = "share"
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
            row["auction_time"] = row.get("time_label")
            row["rank_in_group"] = None
            row["session_type"] = session_type(row_seconds(row))
    return _stamp(rows, thscode, trade_date, "auction_point")


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
        # eltdx versions differ: some expose the normalized names above while
        # older responses only expose the 09:25 snapshot price.  Preserve the
        # raw price as the canonical opening-match field; downstream code can
        # derive the change percentage from the previous daily close.
        if row.get("open_price") is None:
            row["open_price"] = row.get("price")
        row["open_volume"] = row.get("volume")
        if row.get("open_amount") is None:
            row["open_amount"] = row.get("trade_amount_yuan")
        rows = [row]
    return _stamp(rows, thscode, trade_date, "opening_match",
                  default_seconds=9 * 3600 + 25 * 60)


def serialize_minutes(minute_series, thscode, trade_date):
    rows = []
    if minute_series and getattr(minute_series, "points", None):
        rows = [_pick(p, MINUTE_FIELDS) for p in minute_series.points]
        for row in rows:
            row["minute"] = row.get("time_label") or row.get("time")
            price = row.get("price")
            row.setdefault("open", price)
            row.setdefault("high", price)
            row.setdefault("low", price)
            row.setdefault("close", price)
            row["amount"] = None
    return _stamp(rows, thscode, trade_date, "minute_bar")


def serialize_trades(trade_page, thscode, trade_date):
    rows = []
    if trade_page and getattr(trade_page, "ticks", None):
        rows = [_pick(t, TRADE_FIELDS) for t in trade_page.ticks]
        for row in rows:
            row["tick_time"] = row.get("time_label") or row.get("trade_datetime")
            row["amount"] = row.get("trade_amount_yuan")
    return _stamp(rows, thscode, trade_date, "trade_tick")


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
