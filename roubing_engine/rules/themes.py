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


def _active(definition: dict, as_of: str | None) -> bool:
    if not as_of:
        return True
    date = str(as_of)[:10].replace("-", "")
    valid_from = str(definition.get("valid_from") or "").replace("-", "")
    valid_to = str(definition.get("valid_to") or "").replace("-", "")
    return (not valid_from or date >= valid_from) and (not valid_to or date <= valid_to)


def canonical_theme(raw_reason: str | None, as_of: str | None = None) -> tuple[str, dict]:
    raw = (raw_reason or "(未标注)").strip()
    for canonical, definition in registry().get("themes", {}).items():
        if not _active(definition, as_of):
            continue
        aliases = {canonical, *(definition.get("aliases") or [])}
        if raw in aliases:
            return canonical, {
                "raw_reason": raw,
                "normalized_by": registry().get("version"),
                "evidence": definition.get("evidence") or [],
                "parent_theme": definition.get("parent_theme"),
                "valid_from": definition.get("valid_from"),
                "valid_to": definition.get("valid_to"),
                "merge_policy": definition.get("merge_policy", "EXACT_ONLY"),
            }
    return raw, {
        "raw_reason": raw,
        "normalized_by": "IDENTITY_NO_GUESS",
        "evidence": [],
        "parent_theme": None,
    }


def same_theme(raw_reason: str | None, requested: str | None,
               as_of: str | None = None) -> bool:
    if not requested:
        return True
    canonical, _ = canonical_theme(raw_reason, as_of)
    requested_canonical, _ = canonical_theme(requested, as_of)
    return canonical == requested_canonical


def hierarchy_for(themes: list[str], as_of: str) -> list[dict]:
    """Expose parent relationships without merging executable directions."""
    out = []
    for theme in themes:
        canonical, meta = canonical_theme(theme, as_of)
        out.append({
            "theme": canonical,
            "parent_theme": meta.get("parent_theme"),
            "evidence": meta.get("evidence") or [],
            "valid_from": meta.get("valid_from"),
            "valid_to": meta.get("valid_to"),
            "merge_policy": meta.get("merge_policy") or "EXACT_ONLY",
            "executable_merge_allowed": False,
        })
    return out
