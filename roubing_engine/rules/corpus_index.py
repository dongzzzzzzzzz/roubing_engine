"""Lightweight full-corpus index over all 282 raw posts (no LLM).

Builds retrievable reference units (date/title/snippet/hash/url) so reasoning can
surface original text by keyword, complementing the 37 curated operational units.
"""
from __future__ import annotations

import hashlib
import json
import datetime as dt
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = Path(
    os.environ.get("ROUBING_CORPUS_DIR", REPO_ROOT / "reference" / "corpus")
).expanduser()
SOURCES = [
    CORPUS_ROOT / "roubing_2026_articles_raw.json",
    CORPUS_ROOT / "roubing_pre2026_articles_raw.json",
]
OUT = Path(__file__).with_name("corpus_units.json")
CASE_OUT = Path(__file__).with_name("corpus_case_cards.json")

_DATE = ["date", "publish_date", "post_date", "created_at", "time", "ptime"]
_TITLE = ["title", "subject", "name", "topic_title"]
_TEXT = ["content", "text", "body", "content_text", "raw", "article"]
_URL = ["url", "link", "topic_url", "source_url"]


def _first(d, keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k):
            return d[k]
    return None


def _iter_records(obj):
    if isinstance(obj, list):
        yield from obj
    elif isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, list):
                yield from v
                return
        yield obj


def build_index() -> dict:
    units = []
    for src in SOURCES:
        if not src.exists():
            continue
        data = json.loads(src.read_text(encoding="utf-8"))
        for rec in _iter_records(data):
            if not isinstance(rec, dict):
                continue
            text = _first(rec, _TEXT) or ""
            text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
            source_hash = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
            units.append({
                "case_id": f"RAW_{source_hash}",
                "date": _first(rec, _DATE),
                "title": _first(rec, _TITLE),
                "url": _first(rec, _URL),
                "text": text,
                "snippet": text[:400],
                "len": len(text),
                "hash": source_hash,
                "source_file": src.name,
                "evidence_level": "RAW_POST",
                "applicable_conditions": [],
                "counterexamples": [],
            })
    OUT.write_text(json.dumps(units, ensure_ascii=False, indent=2), encoding="utf-8")
    # Case cards intentionally retain the complete source text while exposing
    # a stable traceability envelope for downstream evidence manifests.  The
    # fields are empty until a curated rule compiler establishes conditions or
    # counterexamples; no LLM is allowed to invent them here.
    CASE_OUT.write_text(json.dumps(units, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"n_units": len(units), "with_date": sum(1 for u in units if u["date"]),
            "with_title": sum(1 for u in units if u["title"]), "out": str(OUT)}


def _excerpt(text: str, keywords: list[str], radius: int = 600) -> str:
    positions = [text.find(keyword) for keyword in keywords if text.find(keyword) >= 0]
    if not positions:
        return text[: radius * 2]
    center = min(positions)
    start = max(0, center - radius)
    end = min(len(text), center + radius)
    return text[start:end]


def _published_by(value, as_of: str | None) -> bool:
    if as_of is None:
        return True
    if not value:
        return False
    try:
        cutoff_text = str(as_of).strip()[:10]
        if len(cutoff_text) == 8 and cutoff_text.isdigit():
            cutoff_text = f"{cutoff_text[:4]}-{cutoff_text[4:6]}-{cutoff_text[6:]}"
        value_text = str(value).strip()[:10]
        if len(value_text) == 8 and value_text.isdigit():
            value_text = f"{value_text[:4]}-{value_text[4:6]}-{value_text[6:]}"
        return dt.date.fromisoformat(value_text) <= dt.date.fromisoformat(cutoff_text)
    except (TypeError, ValueError):
        return False


def search(keywords: list[str], limit: int = 8,
           as_of: str | None = None) -> list[dict]:
    if not OUT.exists():
        build_index()
    units = json.loads(OUT.read_text(encoding="utf-8"))
    scored = []
    for u in units:
        if not _published_by(u.get("date"), as_of):
            continue
        hay = f"{u.get('title') or ''}{u.get('text') or u.get('snippet') or ''}"
        score = sum(hay.count(k) for k in keywords)
        if score:
            scored.append((score, u))
    scored.sort(key=lambda x: -x[0])
    out = []
    for score, unit in scored[:limit]:
        item = {key: value for key, value in unit.items() if key != "text"}
        item["score"] = score
        item["excerpt"] = _excerpt(unit.get("text") or unit.get("snippet") or "", keywords)
        out.append(item)
    return out


def render_search(keywords: list[str], limit: int = 8,
                  as_of: str | None = None) -> str:
    lines = ["# 原帖检索证据（原文节选，不得脱离上下文推广个案数字）", ""]
    for unit in search(keywords, limit=limit, as_of=as_of):
        lines += [
            f"## {unit.get('date') or '日期未知'}｜{unit.get('title') or '无标题'}",
            f"- source_hash: {unit.get('hash')}",
            f"- source_url: {unit.get('url') or '无'}",
            "",
            unit.get("excerpt") or "",
            "",
        ]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    print(json.dumps(build_index(), ensure_ascii=False))
    if len(sys.argv) > 1:
        for u in search(sys.argv[1:]):
            print(f"  {u.get('date')} | {str(u.get('title'))[:40]} | {u['hash']}")
