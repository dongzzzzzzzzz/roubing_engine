"""Retrieve roubing evidence units by kind/tag and render them for a task package."""
from __future__ import annotations

import json
import datetime as dt
from functools import lru_cache
from pathlib import Path

UNITS_PATH = Path(__file__).with_name("units.json")
HISTORICAL_VERSIONS_PATH = Path(__file__).with_name("historical_versions.json")


@lru_cache(maxsize=1)
def load_units() -> list[dict]:
    return json.loads(UNITS_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_historical_versions() -> dict:
    if not HISTORICAL_VERSIONS_PATH.exists():
        return {"units": {}}
    return json.loads(HISTORICAL_VERSIONS_PATH.read_text(encoding="utf-8"))


def _cutoff(value: str | None) -> dt.date | None:
    if not value:
        return None
    text = str(value).strip()[:10]
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return dt.date.fromisoformat(text)


def _sources_available(source_dates: list[str], cutoff: dt.date) -> bool:
    try:
        return bool(source_dates) and all(_cutoff(value) <= cutoff for value in source_dates)
    except (TypeError, ValueError):
        return False


def _materialize_as_of(unit: dict, as_of: str | None) -> dict | None:
    cutoff = _cutoff(as_of)
    if cutoff is None:
        return dict(unit)
    dates = unit.get("source_dates") or []
    if not dates:
        # Project-level anti-hindsight/fixed-score disciplines are timeless
        # execution constraints, not factual claims from an undated post.
        return dict(unit) if unit.get("kind") == "discipline" else None
    if _sources_available(dates, cutoff):
        result = dict(unit)
        result["version_id"] = result.get("version_id") or f"{unit.get('id')}@FULL"
        return result

    versions = (load_historical_versions().get("units") or {}).get(unit.get("id"), [])
    eligible = []
    for version in versions:
        valid_from = _cutoff(version.get("valid_from"))
        source_dates = version.get("source_dates") or []
        if valid_from and valid_from <= cutoff and _sources_available(source_dates, cutoff):
            eligible.append(version)
    if not eligible:
        return None
    version = max(eligible, key=lambda item: _cutoff(item["valid_from"]))
    result = dict(unit)
    result.update(version)
    result["source_dates"] = list(version.get("source_dates") or [])
    result["historical_snapshot"] = True
    return result


def select(kinds: list[str] | None = None, tags: list[str] | None = None,
           as_of: str | None = None) -> list[dict]:
    units = load_units()
    out = []
    tagset = set(tags or [])
    for u in units:
        materialized = _materialize_as_of(u, as_of)
        if materialized is None:
            continue
        if kinds and materialized["kind"] not in kinds:
            continue
        if tagset and not (tagset & set(materialized.get("tags", []))):
            continue
        out.append(materialized)
    return out


def render_markdown(units: list[dict]) -> str:
    lines = ["# roubing 规则检索片段（保留语境，禁止改写成固定阈值）", ""]
    for u in units:
        src = "、".join(u.get("source_dates", [])) or "跨帖归纳"
        lines += [
            f"## [{u['id']}] {u['title']}  （证据等级：{u['evidence_level']}）",
            f"- 来源：{src}",
        ]
        if u.get("version_id"):
            lines.append(f"- 规则版本：{u['version_id']}")
        lines.append(f"- 观察：{u['observation']}")
        if u.get("confirm"):
            lines.append(f"- 确认：{u['confirm']}")
        if u.get("cancel"):
            lines.append(f"- 取消：{u['cancel']}")
        if u.get("caveat"):
            lines.append(f"- 注意：{u['caveat']}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    print(f"total units: {len(load_units())}")
    for kind in ("environment", "node", "generator", "role", "exit", "primitive", "discipline"):
        print(f"  {kind}: {len(select(kinds=[kind]))}")
