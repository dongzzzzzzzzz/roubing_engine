"""Assemble one agent-ready deterministic fact pack for a trade date.

Merges:
  - Stage A theme grouping / ladder / breadth (from universe)
  - auction/opening strength per limit code (竞价高开幅, 封单, 09:25 量额)
  - daily-bar features for a bounded candidate shortlist (lazy eltdx)

Still facts-only. No environment/mainstream/role inference (that is the agent's
job in Stage B/C).
"""
from __future__ import annotations

import datetime as dt
import pandas as pd

from roubing_engine.config import WAREHOUSE
from roubing_engine.reasoning.evidence_compiler import compile_day, fact_id
from roubing_engine.warehouse.daily_loader import DAILY_BAR


def _read(dataset: str, yyyymmdd: str) -> pd.DataFrame:
    p = WAREHOUSE / dataset / f"date={yyyymmdd}" / "part.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def _clean(v):
    return None if (v is None or (isinstance(v, float) and pd.isna(v))) else v


def _attach_event_anchor_dates(yyyymmdd: str, observations: list[dict]) -> None:
    """Derive each limit run's start from its streak and trade calendar."""
    max_run = max((int(row.get("consecutive_limit_days") or 0)
                   for row in observations if row.get("event_status") == "limit_up"),
                  default=0)
    trade_dates: list[str] = []
    if max_run and DAILY_BAR.exists():
        day = dt.date(int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:]))
        start = (day - dt.timedelta(days=max(30, max_run * 4))).strftime("%Y%m%d")
        frame = pd.read_parquet(
            DAILY_BAR, columns=["trade_date"],
            filters=[("trade_date", ">=", start), ("trade_date", "<=", yyyymmdd)],
        )
        trade_dates = sorted({str(value) for value in frame["trade_date"].dropna()})
    for row in observations:
        streak = int(row.get("consecutive_limit_days") or 0)
        if row.get("event_status") == "limit_up" and streak >= 1 and len(trade_dates) >= streak:
            raw = trade_dates[-streak]
            row["event_anchor_date"] = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
            row["event_anchor_status"] = "DERIVED"
            row["event_anchor_basis"] = (
                "consecutive_limit_days + stock_daily_bar trading calendar")
        else:
            row["event_anchor_date"] = None
            row["event_anchor_status"] = "BLOCKED_DATA"
            row["event_anchor_basis"] = (
                "non-limit event, missing streak, or insufficient trading calendar")


def _auction_strength(yyyymmdd: str) -> dict:
    """thscode -> {open_change_pct, open_amount, matched} from opening_match."""
    df = _read("opening_match", yyyymmdd)
    # The normalized opening partition may contain only ``price`` when the
    # collector was produced by an older eltdx adapter.  Do not silently lose
    # that fact: use it as the 09:25 matching price and derive the percentage
    # below from the daily previous close when available.
    previous_close = _previous_close_map(yyyymmdd)
    out = {}
    for _, r in df.iterrows():
        code = str(r["thscode"])
        price = _clean(r.get("open_price")) or _clean(r.get("price"))
        pre_close = _clean(r.get("pre_close_price")) or previous_close.get(code)
        change = _clean(r.get("open_change_pct"))
        if change is None and price is not None and pre_close:
            change = round((float(price) / float(pre_close) - 1) * 100, 2)
        out[r["thscode"]] = {
            "open_price": price,
            "pre_close_price": pre_close,
            "open_change_pct": change,
            "auction_volume": _clean(r.get("volume")),
            "auction_amount_yuan": _clean(r.get("trade_amount_yuan")),
        }
    return out


def _previous_close_map(yyyymmdd: str) -> dict[str, float]:
    """Return the latest daily close strictly before ``yyyymmdd``."""
    try:
        from roubing_engine.warehouse.daily_loader import read_daily_asof
        raw = f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"
        frame = read_daily_asof(raw)
    except Exception:  # noqa: BLE001 - facts must remain buildable offline
        return {}
    if frame.empty:
        return {}
    frame = frame[frame["trade_date"].astype(str) < yyyymmdd]
    if frame.empty:
        return {}
    latest_date = frame["trade_date"].astype(str).max()
    frame = frame[frame["trade_date"].astype(str) == latest_date]
    return {
        str(row["thscode"]): float(row["close"])
        for _, row in frame.iterrows()
        if pd.notna(row.get("close")) and float(row["close"]) > 0
    }


def _previous_state(yyyymmdd: str) -> dict:
    """Load only the approved state strictly before the requested date."""
    try:
        from roubing_engine.state.ledger import load_prev_ledger
        return load_prev_ledger(yyyymmdd)
    except Exception:  # noqa: BLE001 - absence is represented as facts below
        return {}


def _attach_prior_state(facts: dict, yyyymmdd: str, observations: list[dict]) -> None:
    previous = _previous_state(yyyymmdd)
    try:
        from roubing_engine.state.ledger import previous_ledger_status
        ledger_status = previous_ledger_status(yyyymmdd)
    except Exception:  # noqa: BLE001
        ledger_status = {
            "available": False,
            "expected_previous_trade_date": None,
            "nearest_prior_ledger_date": None,
            "stale_prior_exists": False,
            "reason": "previous ledger status unavailable",
        }
    direction_by_theme = {
        item.get("theme"): item for item in (
            previous.get("direction_evaluations") or previous.get("mainstream_directions") or [])
    }
    role_by_code = {
        item.get("thscode"): item for item in (previous.get("roles") or [])
    }

    for direction in facts.get("direction_state_facts", []):
        old = direction_by_theme.get(direction.get("theme"))
        direction["previous_state"] = ({
            "available": True,
            "trade_date": previous.get("trade_date"),
            "stage": old.get("stage_today") or old.get("stage"),
            "supporting_fact_ids": old.get("supporting_fact_ids") or [],
        } if old else {
            "available": False,
            "reason": ledger_status.get("reason") or "no approved previous direction state",
            "expected_previous_trade_date": ledger_status.get("expected_previous_trade_date"),
            "nearest_prior_ledger_date": ledger_status.get("nearest_prior_ledger_date"),
        })

    for stock in observations:
        code = stock.get("thscode")
        daily = stock.get("daily") or {}
        old = role_by_code.get(code)
        stock["turnover_percentile_250d"] = daily.get("turnover_pctile_250d")
        stock["prior_high"] = daily.get("prior_high")
        stock["closed_above_prior_high"] = daily.get("is_close_above_prior_high")
        stock["previous_role_task"] = ({
            "available": True,
            "trade_date": previous.get("trade_date"),
            "role": old.get("new_role") or old.get("role"),
            "role_family": old.get("role_family"),
            "role_status": old.get("new_role_status") or old.get("role_status"),
            "execution_task": old.get("execution_task"),
            "must_continue_doing": old.get("must_continue_doing") or [],
            "loses_role_when": old.get("loses_role_when") or [],
            "output_tier": old.get("output_tier"),
        } if old else {
            "available": False,
            "reason": ledger_status.get("reason") or "no approved previous role/task state",
            "expected_previous_trade_date": ledger_status.get("expected_previous_trade_date"),
            "nearest_prior_ledger_date": ledger_status.get("nearest_prior_ledger_date"),
        })
        stock["fact_refs"] = list(dict.fromkeys([
            value for value in (stock.get("fact_id"), stock.get("direction_fact_id")) if value
        ]))

    facts["previous_state_summary"] = {
        **ledger_status,
        "available": bool(previous) and bool(ledger_status.get("available")),
        "trade_date": previous.get("trade_date"),
        "environment": previous.get("environment"),
        "direction_count": len(direction_by_theme),
        "role_count": len(role_by_code),
    }


def _build_fact_catalog(facts: dict, yyyymmdd: str) -> dict[str, dict]:
    catalog: dict[str, dict] = {}
    for index, item in enumerate(facts.get("environment_facts", [])):
        catalog[item["fact_id"]] = {
            "scope": "ENVIRONMENT", "path": f"environment_facts[{index}]",
        }
    for index, item in enumerate(facts.get("direction_state_facts", [])):
        catalog[item["fact_id"]] = {
            "scope": "DIRECTION", "theme": item.get("theme"),
            "path": f"direction_state_facts[{index}]",
        }
        feedback = item.get("previous_buyer_feedback") or {}
        if feedback.get("fact_id"):
            catalog[feedback["fact_id"]] = {
                "scope": "DIRECTION_FEEDBACK", "theme": item.get("theme"),
                "path": f"direction_state_facts[{index}].previous_buyer_feedback",
            }
    for index, item in enumerate(facts.get("stage_b_observation_universe", [])):
        item.setdefault("fact_id", fact_id(yyyymmdd, "STOCK", str(item.get("thscode"))))
        catalog[item["fact_id"]] = {
            "scope": "STOCK", "thscode": item.get("thscode"),
            "path": f"stage_b_observation_universe[{index}]",
        }
    for index, item in enumerate(facts.get("context_facts", [])):
        catalog[item["fact_id"]] = {
            "scope": "CONTEXT", "fact_type": item.get("fact_type"),
            "path": f"context_facts[{index}]",
        }
    return catalog


def _path_comparison_contract(facts: dict) -> dict:
    """Declare which data gaps block which level of Stage-B conclusion.

    This is a data-availability contract, not a theme ranking.  T-day event
    counts and ladders can support a relative execution-priority path even on
    the first ledger day.  Missing history prevents calling that path a
    historically confirmed mainstream/continuation, but must not erase a
    cross-sectional distinction that is already visible.
    """
    rows = facts.get("direction_state_facts") or []
    comparable = [
        row for row in rows
        if row.get("fact_id") and row.get("theme")
        and isinstance(row.get("event_counts"), dict)
        and isinstance(row.get("ladder_distribution"), dict)
    ]
    previous_state = facts.get("previous_state_summary") or {}
    previous_buyer = facts.get("previous_buyer_feedback") or {}
    return {
        "cross_section_comparison_available": len(comparable) >= 2,
        "comparable_direction_count": len(comparable),
        "historical_confirmation_available": bool(
            previous_state.get("available") or previous_buyer.get("available")
        ),
        "minimum_cross_section_fields": [
            "direction fact_id/theme", "event_counts", "ladder_distribution",
        ],
        "selection_semantics": (
            "SELECTED表示次日条件计划的相对优先路径候选，不等于正式主流、主升或历史延续已确认"
        ),
        "blocking_semantics": (
            "缺前日账本、昨日买方、板块扩散、公告或盘中委托流，只阻止对应历史/主动性确认；"
            "若当日方向结构已能按逐层淘汰拉开差异，不得仅因此写BLOCKED_DATA"
        ),
    }


def build(yyyymmdd: str, client=None, with_index: bool = True) -> dict:
    facts = compile_day(yyyymmdd)
    if not facts.get("available"):
        return facts

    strength = _auction_strength(yyyymmdd)

    # attach auction strength to each theme code
    for theme in facts["themes"]:
        for c in theme["codes"]:
            s = strength.get(c["thscode"])
            if s:
                c.update(s)

    # Stage B may inspect the complete captured limit/failure roster.  It must
    # not receive a fixed top-N shortlist that structurally removes capacity,
    # old-core, broken-board or low-position observations before a node exists.
    all_codes = [c for t in facts["themes"] for c in t["codes"]]
    failed = facts.get("failed_observations", [])
    observations = all_codes + failed
    _attach_event_anchor_dates(yyyymmdd, observations)

    # deterministic daily features from the full-market warehouse (anti-lookahead)
    as_of_dash = f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"
    try:
        from roubing_engine.features.stock_features import features_for
        feats = features_for([c["thscode"] for c in observations], as_of_dash)
        for c in observations:
            c["daily"] = feats.get(c["thscode"], {"available": False})
    except Exception as e:  # noqa: BLE001
        for c in observations:
            c["daily"] = {"available": False, "error": type(e).__name__}

    _attach_prior_state(facts, yyyymmdd, observations)

    facts["stage_b_observation_universe"] = observations
    facts["observation_universe_note"] = (
        "完整的当日涨停/炸板/跌停观察集合，无top-N截断；最终候选只能由节点生成器产生。")

    try:
        from roubing_engine.candidates.pools import attach_context
        facts["stage_b_observation_universe"] = attach_context(observations, as_of_dash)
    except Exception as exc:  # noqa: BLE001
        facts["context_data_gap"] = f"公告/题材上下文不可用:{type(exc).__name__}"

    # index context (fills the index/board-index gap Stage B needs)
    if with_index:
        try:
            from roubing_engine.features.index_ctx import index_context
            as_of_dash = f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"
            facts["index_context"] = index_context(as_of_dash)
        except Exception as e:  # noqa: BLE001
            facts["index_context"] = {"available": False, "error": type(e).__name__}
    else:
        facts["index_context"] = {"available": False, "reason": "disabled by --no-daily"}

    from roubing_engine.rules.regulatory import active_rules
    facts["regulatory_context"] = active_rules(as_of_dash)
    try:
        from roubing_engine.features.risk_ctx import risk_context
        facts["risk_context"] = risk_context(yyyymmdd,
                                               [c["thscode"] for c in observations])
    except Exception as e:  # noqa: BLE001
        facts["risk_context"] = {
            "as_of": yyyymmdd, "available": False,
            "datasets": {"status": "BLOCKED_DATA", "reason": type(e).__name__},
        }

    facts["context_facts"] = [
        {
            "fact_id": fact_id(yyyymmdd, "CTX", "INDEX_CONTEXT"),
            "fact_type": "INDEX_CONTEXT",
            "status": ("AVAILABLE" if any(
                isinstance(value, dict) and value.get("available")
                for value in (facts.get("index_context") or {}).values())
                       else "BLOCKED_DATA"),
            "value": facts.get("index_context"),
        },
        {
            "fact_id": fact_id(yyyymmdd, "CTX", "DATA_COMPLETENESS"),
            "fact_type": "DATA_COMPLETENESS",
            "status": "AVAILABLE",
            "value": facts.get("data_completeness"),
        },
        {
            "fact_id": fact_id(yyyymmdd, "CTX", "PREVIOUS_STATE_STATUS"),
            "fact_type": "PREVIOUS_STATE_STATUS",
            "status": ("AVAILABLE" if (facts.get("previous_state_summary") or {}).get("available")
                       else "BLOCKED_DATA"),
            "value": facts.get("previous_state_summary"),
        },
        {
            "fact_id": fact_id(yyyymmdd, "CTX", "REGULATORY_CONTEXT"),
            "fact_type": "REGULATORY_CONTEXT",
            "status": (facts.get("regulatory_context") or {}).get("status", "BLOCKED_DATA"),
            "value": facts.get("regulatory_context"),
        },
        {
            "fact_id": fact_id(yyyymmdd, "CTX", "RISK_CONTEXT"),
            "fact_type": "RISK_CONTEXT",
            "status": ("AVAILABLE" if (facts.get("risk_context") or {}).get("available")
                       else "BLOCKED_DATA"),
            "value": facts.get("risk_context"),
        },
    ]

    facts["fact_catalog"] = _build_fact_catalog(facts, yyyymmdd)
    facts["fact_contract"] = {
        "version": "1.0",
        "rule": "所有 Stage B/C 事实性结论必须引用 fact_catalog 中存在的 fact_id",
        "stable_identity": "trade_date + scope + immutable identity",
    }
    facts["path_comparison_contract"] = _path_comparison_contract(facts)

    return facts


if __name__ == "__main__":
    import json
    import sys
    from roubing_engine.collectors.eltdx_client import client as _client
    date = sys.argv[1] if len(sys.argv) > 1 else "20260908"
    with _client() as c:
        fp = build(date, client=c)
    print(f"themes={len(fp.get('themes', []))} observations="
          f"{len(fp.get('stage_b_observation_universe', []))}")
    print(json.dumps(fp.get("stage_b_observation_universe", [])[:3], ensure_ascii=False, indent=2))
