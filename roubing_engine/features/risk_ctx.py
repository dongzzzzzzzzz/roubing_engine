"""Deterministic suspension/monitor/risk-notice context.

These datasets are optional captures.  The module reports raw rows and
coverage only; it never infers that a stock is safe, restricted, or close to a
regulatory threshold.
"""
from __future__ import annotations

import pandas as pd

from roubing_engine.config import WAREHOUSE


DATASETS = {
    "suspension": "suspension",
    "special_monitor": "special_monitor",
    "risk_notice": "risk_notice",
}


def risk_context(yyyymmdd: str, codes: list[str] | None = None) -> dict:
    requested = set(codes or [])
    out = {}
    for label, dataset in DATASETS.items():
        path = WAREHOUSE / dataset / f"date={yyyymmdd.replace('-', '')}" / "part.parquet"
        if not path.exists():
            out[label] = {
                "status": "BLOCKED_DATA", "available": False, "n_rows": 0,
                "rows": [], "reason": "未采集该类当日数据",
            }
            continue
        try:
            frame = pd.read_parquet(path)
        except Exception as exc:  # noqa: BLE001
            out[label] = {
                "status": "BLOCKED_DATA", "available": False, "n_rows": 0,
                "rows": [], "reason": f"读取失败:{type(exc).__name__}",
            }
            continue
        if requested and "thscode" in frame.columns:
            frame = frame[frame["thscode"].astype(str).isin(requested)]
        rows = frame.to_dict("records")
        out[label] = {
            "status": "READY" if rows else "EMPTY",
            "available": bool(rows),
            "n_rows": len(rows),
            "rows": rows,
            "reason": None if rows else "分区存在但没有匹配记录",
        }
    return {
        "as_of": yyyymmdd,
        "datasets": out,
        "available": all(item["available"] for item in out.values()),
    }
