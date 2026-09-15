"""One-way, recoverable warehouse contract migration helpers.

The migration only enriches datasets whose raw rows already exist.  It never
manufactures unavailable primary-source facts; missing Financial-API tables
remain missing in ``contract_report`` until captured from a valid source.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Callable

import pandas as pd

from roubing_engine.config import WAREHOUSE
from roubing_engine.reasoning.contracts import FACT_TABLE_BY_NAME
from roubing_engine.warehouse.timebox import iso_at, row_seconds


MIGRATABLE_TABLES = (
    "stock_daily_bar",
    "auction_point",
    "opening_match",
    "minute_bar",
    "trade_tick",
)


def _eltdx_code(thscode) -> str | None:
    if thscode is None or pd.isna(thscode):
        return None
    return str(thscode).split(".")[0]


def _ensure(df: pd.DataFrame, column: str, value) -> None:
    if column not in df.columns:
        df[column] = value


def _event_time_from_row(row: pd.Series, trade_date: str, default_seconds: int | None):
    seconds = row_seconds(row)
    if seconds is None:
        seconds = default_seconds
    return iso_at(trade_date, seconds) if seconds is not None else None


def migrate_stock_daily_bar(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["thscode"] = out["thscode"].astype(str)
    out["trade_date"] = out["trade_date"].astype(str)
    out["eltdx_code"] = out["thscode"].map(_eltdx_code)
    for raw, adj in (("open", "adj_open"), ("high", "adj_high"),
                     ("low", "adj_low"), ("close", "adj_close")):
        _ensure(out, adj, out[raw] if raw in out.columns else pd.NA)
    if "amount" not in out.columns:
        out["amount"] = out["turnover"] if "turnover" in out.columns else pd.NA
    _ensure(out, "volume_unit", "share")
    out["source"] = "Financial-API"
    _ensure(out, "interface", "daily_k.dump")
    out["request_id"] = (
        "financial-api-daily-k:"
        + out["thscode"].astype(str) + ":" + out["trade_date"].astype(str)
    )
    _ensure(out, "event_time", None)
    out["event_time"] = out["event_time"].where(
        out["event_time"].notna(),
        out["trade_date"].map(lambda d: f"{d[:4]}-{d[4:6]}-{d[6:8]} 15:00:00 Asia/Shanghai"),
    )
    out = out.sort_values(["thscode", "trade_date"])
    if "change_pct" not in out.columns:
        prev_close = out.groupby("thscode")["close"].shift(1)
        out["change_pct"] = ((out["close"] / prev_close - 1) * 100).round(4)
        out.loc[prev_close.isna() | (prev_close == 0), "change_pct"] = pd.NA
    return out


def _migrate_intraday_common(df: pd.DataFrame, table: str,
                             default_seconds: int | None = None) -> pd.DataFrame:
    out = df.copy()
    out["thscode"] = out["thscode"].astype(str)
    out["trade_date"] = out["trade_date"].astype(str)
    out["eltdx_code"] = out["thscode"].map(_eltdx_code)
    out["source"] = "eltdx"
    _ensure(out, "interface", table)
    _ensure(out, "request_id", None)
    if "event_time" not in out.columns:
        out["event_time"] = [
            _event_time_from_row(row, str(row["trade_date"]), default_seconds)
            for _, row in out.iterrows()
        ]
    if "available_at" not in out.columns:
        out["available_at"] = out["event_time"]
    out["request_id"] = out["request_id"].where(
        out["request_id"].notna(),
        "eltdx:" + table + ":" + out["thscode"].astype(str) + ":"
        + out["trade_date"].astype(str) + ":"
        + out.get("time_label", out.index.to_series()).astype(str),
    )
    return out


def migrate_auction_point(df: pd.DataFrame) -> pd.DataFrame:
    out = _migrate_intraday_common(df, "auction_point")
    if "auction_time" not in out.columns:
        out["auction_time"] = out["time_label"] if "time_label" in out.columns else pd.NA
    _ensure(out, "rank_in_group", pd.NA)
    return out


def migrate_opening_match(df: pd.DataFrame) -> pd.DataFrame:
    out = _migrate_intraday_common(df, "opening_match", 9 * 3600 + 25 * 60)
    if "open_price" not in out.columns:
        out["open_price"] = out["price"] if "price" in out.columns else pd.NA
    if "open_volume" not in out.columns:
        out["open_volume"] = out["volume"] if "volume" in out.columns else pd.NA
    if "open_amount" not in out.columns:
        out["open_amount"] = (
            out["trade_amount_yuan"] if "trade_amount_yuan" in out.columns else pd.NA
        )
    return out


def migrate_minute_bar(df: pd.DataFrame) -> pd.DataFrame:
    out = _migrate_intraday_common(df, "minute_bar")
    if "minute" not in out.columns:
        out["minute"] = out["time_label"] if "time_label" in out.columns else out.get("time")
    price = out["price"] if "price" in out.columns else pd.NA
    for column in ("open", "high", "low", "close"):
        _ensure(out, column, price)
    _ensure(out, "volume_unit", "share")
    _ensure(out, "amount", pd.NA)
    return out


def migrate_trade_tick(df: pd.DataFrame) -> pd.DataFrame:
    out = _migrate_intraday_common(df, "trade_tick")
    if "tick_time" not in out.columns:
        out["tick_time"] = (
            out["time_label"] if "time_label" in out.columns else out.get("trade_datetime")
        )
    _ensure(out, "volume_unit", "share")
    if "amount" not in out.columns:
        out["amount"] = out["trade_amount_yuan"] if "trade_amount_yuan" in out.columns else pd.NA
    return out


MIGRATORS: dict[str, Callable[[pd.DataFrame], pd.DataFrame]] = {
    "stock_daily_bar": migrate_stock_daily_bar,
    "auction_point": migrate_auction_point,
    "opening_match": migrate_opening_match,
    "minute_bar": migrate_minute_bar,
    "trade_tick": migrate_trade_tick,
}


def _paths_for(root: Path, table: str) -> list[Path]:
    flat = root / table / "all.parquet"
    if flat.exists():
        return [flat]
    base = root / table
    return sorted(base.glob("**/*.parquet")) if base.exists() else []


def _violations(table: str, df: pd.DataFrame) -> list[str]:
    contract = FACT_TABLE_BY_NAME[table]
    missing = [field for field in contract.required_fields if field not in df.columns]
    source_ok = "source" in df.columns and set(df["source"].dropna().astype(str)) == {
        contract.primary_source
    }
    return missing + ([] if source_ok else [f"source must be {contract.primary_source}"])


def migrate(root: Path = WAREHOUSE, *, write: bool = False,
            backup_root: Path | None = None) -> dict:
    backup_root = backup_root or root / "_migration_backup" / "contract_v1"
    reports = []
    for table in MIGRATABLE_TABLES:
        paths = _paths_for(root, table)
        for path in paths:
            before = pd.read_parquet(path)
            after = MIGRATORS[table](before)
            violations = _violations(table, after)
            report = {
                "table": table,
                "path": str(path),
                "rows": int(len(after)),
                "write": write,
                "status": "PASS" if not violations else "NEEDS_REVIEW",
                "violations": violations,
                "added_columns": sorted(set(after.columns) - set(before.columns)),
            }
            if write and not violations:
                backup = backup_root / path.relative_to(root)
                backup.parent.mkdir(parents=True, exist_ok=True)
                if not backup.exists():
                    shutil.copy2(path, backup)
                tmp = path.with_name(f".{path.name}.contract.tmp")
                after.to_parquet(tmp, engine="pyarrow", index=False)
                tmp.replace(path)
                report["backup"] = str(backup)
            reports.append(report)
    return {
        "root": str(root),
        "write": write,
        "backup_root": str(backup_root),
        "tables": reports,
        "status": "PASS" if all(row["status"] == "PASS" for row in reports)
        else "NEEDS_REVIEW",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=WAREHOUSE)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    print(json.dumps(migrate(args.root, write=args.write), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
