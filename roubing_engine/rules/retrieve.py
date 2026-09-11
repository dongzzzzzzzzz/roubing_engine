"""Retrieve roubing evidence units by kind/tag and render them for a task package."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

UNITS_PATH = Path(__file__).with_name("units.json")


@lru_cache(maxsize=1)
def load_units() -> list[dict]:
    return json.loads(UNITS_PATH.read_text(encoding="utf-8"))


def select(kinds: list[str] | None = None, tags: list[str] | None = None) -> list[dict]:
    units = load_units()
    out = []
    tagset = set(tags or [])
    for u in units:
        if kinds and u["kind"] not in kinds:
            continue
        if tagset and not (tagset & set(u.get("tags", []))):
            continue
        out.append(u)
    return out


def render_markdown(units: list[dict]) -> str:
    lines = ["# roubing 规则检索片段（保留语境，禁止改写成固定阈值）", ""]
    for u in units:
        src = "、".join(u.get("source_dates", [])) or "跨帖归纳"
        lines += [
            f"## [{u['id']}] {u['title']}  （证据等级：{u['evidence_level']}）",
            f"- 来源：{src}",
            f"- 观察：{u['observation']}",
        ]
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
