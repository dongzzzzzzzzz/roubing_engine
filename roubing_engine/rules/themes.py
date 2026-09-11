"""Versioned, evidence-backed theme-name normalization.

The safe default is identity.  This intentionally avoids guessing that two
similar-looking limit reasons represent the same short-term money relationship.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

REGISTRY_PATH = Path(__file__).with_name("theme_registry.json")


@lru_cache(maxsize=1)
def registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def canonical_theme(raw_reason: str | None) -> tuple[str, dict]:
    raw = (raw_reason or "(未标注)").strip()
    for canonical, definition in registry().get("themes", {}).items():
        aliases = {canonical, *(definition.get("aliases") or [])}
        if raw in aliases:
            return canonical, {
                "raw_reason": raw,
                "normalized_by": registry().get("version"),
                "evidence": definition.get("evidence") or [],
                "parent_theme": definition.get("parent_theme"),
            }
    return raw, {
        "raw_reason": raw,
        "normalized_by": "IDENTITY_NO_GUESS",
        "evidence": [],
        "parent_theme": None,
    }


def same_theme(raw_reason: str | None, requested: str | None) -> bool:
    if not requested:
        return True
    canonical, _ = canonical_theme(raw_reason)
    requested_canonical, _ = canonical_theme(requested)
    return canonical == requested_canonical

