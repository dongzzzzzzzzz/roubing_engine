"""Effective-date selector for official regulatory rules."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

REGISTRY_PATH = Path(__file__).with_name("regulatory_registry.json")


@lru_cache(maxsize=1)
def registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def active_rules(as_of: str, market: str | None = None,
                 board: str | None = None) -> dict:
    date = as_of.replace("-", "")[:8]
    selected = []
    for rule in registry().get("rules", []):
        start = str(rule.get("effective_from") or "00000000").replace("-", "")
        end = str(rule.get("effective_to") or "99999999").replace("-", "")
        if not (start <= date <= end):
            continue
        if market and rule.get("market") not in (None, market):
            continue
        if board and rule.get("board") not in (None, board):
            continue
        selected.append(rule)
    return {
        "available": bool(selected),
        "status": "READY" if selected else "BLOCKED_DATA",
        "numeric_thresholds_available": bool(selected) and all(
            rule.get("numeric_thresholds_verified", False) for rule in selected
        ),
        "as_of": as_of,
        "registry_version": registry().get("version"),
        "last_verified_at": registry().get("last_verified_at"),
        "rules": selected,
        "official_sources": registry().get("official_sources") or [],
        "data_block": (None if selected and all(rule.get("numeric_thresholds_verified", False)
                                               for rule in selected)
                       else "官方规则背景已登记，但精确异动阈值条款尚未逐条核验；不得计算异动距离"),
    }
