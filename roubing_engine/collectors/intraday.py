"""Per-(code, date) intraday capture and per-day universe capture."""
from __future__ import annotations

from roubing_engine.collectors import serialize
from roubing_engine.collectors.eltdx_client import with_retry


def get_universe(client, yyyymmdd: str):
    """Full limit-up/broken/limit-down roster for a day (survivorship-safe)."""
    ladder = with_retry(client.f10.limit_up_down_list, yyyymmdd, include_summary=True)
    return getattr(ladder, "rows", None) or []


def capture_code(client, eltdx_code: str, date_dash: str, datasets: list[str]):
    """Capture requested datasets for one code+date.

    Returns (data, status):
      data:   {dataset: list[dict]}
      status: {dataset: "ok"|"empty"|"error:<Type>"}
    """
    data: dict[str, list[dict]] = {}
    status: dict[str, str] = {}
    thscode = None  # filled from serialize via to_thscode not needed; use full code
    from roubing_engine.collectors.eltdx_client import to_thscode
    thscode = to_thscode(eltdx_code)

    auction = None
    if "auction_point" in datasets or "opening_match" in datasets:
        try:
            auction = with_retry(client.helpers.auction_data, eltdx_code, date_dash)
        except Exception as e:  # noqa: BLE001
            for ds in ("auction_point", "opening_match"):
                if ds in datasets:
                    status[ds] = f"error:{type(e).__name__}"

    if "auction_point" in datasets and "auction_point" not in status:
        rows = serialize.serialize_auction(auction, thscode, date_dash.replace("-", ""))
        data["auction_point"] = rows
        status["auction_point"] = "ok" if rows else "empty"

    if "opening_match" in datasets and "opening_match" not in status:
        rows = serialize.serialize_opening(auction, thscode, date_dash.replace("-", ""))
        data["opening_match"] = rows
        status["opening_match"] = "ok" if rows else "empty"

    if "minute_bar" in datasets:
        try:
            m = with_retry(client.minutes.history, eltdx_code, date_dash)
            rows = serialize.serialize_minutes(m, thscode, date_dash.replace("-", ""))
            data["minute_bar"] = rows
            status["minute_bar"] = "ok" if rows else "empty"
        except Exception as e:  # noqa: BLE001
            status["minute_bar"] = f"error:{type(e).__name__}"

    if "trade_tick" in datasets:
        try:
            t = with_retry(client.trades.all_history, eltdx_code, date_dash)
            rows = serialize.serialize_trades(t, thscode, date_dash.replace("-", ""))
            data["trade_tick"] = rows
            status["trade_tick"] = "ok" if rows else "empty"
        except Exception as e:  # noqa: BLE001
            status["trade_tick"] = f"error:{type(e).__name__}"

    return data, status
