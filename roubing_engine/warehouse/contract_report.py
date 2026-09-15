"""Validate on-disk warehouse datasets against the roubing fact contracts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from roubing_engine.config import WAREHOUSE
from roubing_engine.reasoning.contracts import FACT_TABLES


def _dataset_path(root: Path, table: str) -> Path | None:
    flat = root / table / "all.parquet"
    if flat.exists():
        return flat
    partition_dir = root / table
    if partition_dir.exists() and any(partition_dir.glob("**/*.parquet")):
        return partition_dir
    return None


def _schema_columns(path: Path) -> list[str]:
    if path.is_file():
        return pq.read_schema(path).names
    first = next(path.glob("**/*.parquet"))
    return pq.read_schema(first).names


def _sample_source_values(path: Path, columns: list[str]) -> dict[str, Any]:
    wanted = [col for col in ("source", "interface", "request_id", "volume_unit")
              if col in columns]
    if not wanted:
        return {}
    parquet = path if path.is_file() else next(path.glob("**/*.parquet"))
    table = pq.read_table(parquet, columns=wanted)
    out = {}
    for col in wanted:
        values = table.column(col).to_pylist()[:50]
        out[col] = sorted({str(value) for value in values if value is not None})[:5]
    return out


def validate_warehouse(root: Path = WAREHOUSE) -> dict[str, Any]:
    """Return a real schema/source report for all twelve fact tables.

    Missing historical intraday datasets are not silently treated as valid; the
    caller decides whether the missing table is a local downgrade or a true
    replay blocker for the conclusion being attempted.
    """
    tables = []
    for contract in FACT_TABLES:
        path = _dataset_path(root, contract.table)
        if path is None:
            tables.append({
                "table": contract.table,
                "status": "MISSING_DATASET",
                "primary_source": contract.primary_source,
                "path": None,
                "missing_columns": list(contract.required_fields),
                "extra_columns": [],
                "sample_values": {},
            })
            continue
        columns = _schema_columns(path)
        missing = [field for field in contract.required_fields if field not in columns]
        sample_values = _sample_source_values(path, columns)
        source_values = sample_values.get("source") or []
        source_ok = contract.primary_source in source_values if source_values else False
        status = "PASS" if not missing and source_ok else "NEEDS_MIGRATION"
        tables.append({
            "table": contract.table,
            "status": status,
            "primary_source": contract.primary_source,
            "path": str(path),
            "missing_columns": missing,
            "extra_columns": [column for column in columns
                              if column not in contract.required_fields],
            "sample_values": sample_values,
            "source_ok": source_ok,
        })
    return {
        "status": "PASS" if all(row["status"] == "PASS" for row in tables)
        else "NEEDS_MIGRATION",
        "root": str(root),
        "tables": tables,
    }


def main() -> None:
    print(json.dumps(validate_warehouse(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
