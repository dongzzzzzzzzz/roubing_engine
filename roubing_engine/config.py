"""Global config for the roubing capture/reasoning engine.

Only data-collection settings live here for now. Storage is local Parquet
under data/warehouse, partitioned by trade_date, following the plan's
"immutable fact layer" discipline (append/version, never overwritten by AI).
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT / "data"
WAREHOUSE = DATA_ROOT / "warehouse"
MANIFEST_PATH = WAREHOUSE / "capture_manifest.parquet"

# All datasets we can capture per (code, date).
DATASETS = ["auction_point", "opening_match", "minute_bar", "trade_tick"]
F10_DATASETS = ["announcement", "hot_topic"]

# Time-sensitive datasets: eltdx only retains the intraday auction *process*
# for ~12 months (verified 2026-09). These must be frozen promptly.
ROLLING_DATASETS = ["auction_point"]

TZ = "Asia/Shanghai"
DEFAULT_TIMEOUT = 5

# A liquid reference used to derive the trading-day calendar.
CALENDAR_REF_CODE = "sh600000"
