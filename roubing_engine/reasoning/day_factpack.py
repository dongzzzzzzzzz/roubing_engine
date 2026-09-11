"""Assemble one agent-ready deterministic fact pack for a trade date.

Merges:
  - Stage A theme grouping / ladder / breadth (from universe)
  - auction/opening strength per limit code (竞价高开幅, 封单, 09:25 量额)
  - daily-bar features for a bounded candidate shortlist (lazy eltdx)

Still facts-only. No environment/mainstream/role inference (that is the agent's
job in Stage B/C).
"""
from __future__ import annotations

import pandas as pd

from roubing_engine.config import WAREHOUSE
from roubing_engine.reasoning.evidence_compiler import compile_day


def _read(dataset: str, yyyymmdd: str) -> pd.DataFrame:
    p = WAREHOUSE / dataset / f"date={yyyymmdd}" / "part.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def _clean(v):
    return None if (v is None or (isinstance(v, float) and pd.isna(v))) else v


def _auction_strength(yyyymmdd: str) -> dict:
    """thscode -> {open_change_pct, open_amount, matched} from opening_match."""
    df = _read("opening_match", yyyymmdd)
    out = {}
    for _, r in df.iterrows():
        out[r["thscode"]] = {
            "open_change_pct": _clean(r.get("open_change_pct")),
            "auction_volume": _clean(r.get("volume")),
            "auction_amount_yuan": _clean(r.get("trade_amount_yuan")),
        }
    return out


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
