"""Local Parquet warehouse writer + capture manifest.

Layout:
  data/warehouse/<dataset>/date=YYYYMMDD/part.parquet
  data/warehouse/capture_manifest.parquet   (append-only log)

Full captures may replace a partition.  Targeted/backfill captures must merge
on the dataset's business key, so fetching six validation candidates cannot
delete facts previously captured for the rest of the market.
"""
from __future__ import annotations

from datetime import datetime, timezone
import uuid

import pandas as pd

from roubing_engine.config import MANIFEST_PATH, WAREHOUSE


DATASET_KEYS = {
    "universe": ["trade_date", "thscode", "source"],
    "auction_point": ["trade_date", "thscode", "time_seconds", "index", "source"],
    "opening_match": ["trade_date", "thscode", "source"],
    "minute_bar": ["trade_date", "thscode", "time_label", "source"],
    "trade_tick": ["trade_date", "thscode", "absolute_index", "source"],
    "announcement": ["thscode", "rec_id", "source"],
    "hot_topic": ["thscode", "topic_id", "source"],
}


def _part_path(dataset: str, yyyymmdd: str):
    d = WAREHOUSE / dataset / f"date={yyyymmdd}"
    d.mkdir(parents=True, exist_ok=True)
    return d / "part.parquet"


def _atomic_write(df: pd.DataFrame, path) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    df.to_parquet(tmp, engine="pyarrow", index=False)
    tmp.replace(path)


def _archive_capture(dataset: str, yyyymmdd: str, frame: pd.DataFrame) -> str | None:
    """Append the exact incoming batch to the immutable raw capture history."""
    if frame.empty:
        return None
    capture_id = (
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-"
        f"{uuid.uuid4().hex[:8]}"
    )
    directory = WAREHOUSE / "_captures" / dataset / f"date={yyyymmdd}"
    directory.mkdir(parents=True, exist_ok=True)
    raw = frame.copy()
    raw["capture_id"] = capture_id
    _atomic_write(raw, directory / f"capture={capture_id}.parquet")
    return capture_id


def write_dataset(dataset: str, yyyymmdd: str, rows: list[dict], *,
                  mode: str = "replace", key_columns: list[str] | None = None) -> int:
    """Write one date partition and return the final partition row count.

    ``replace`` is reserved for a known full capture. ``merge`` preserves rows
    outside a targeted capture and replaces only rows with the same business
    key.  Empty merge batches are a no-op.
    """
    if mode not in {"replace", "merge"}:
        raise ValueError(f"unsupported write mode: {mode}")
    path = _part_path(dataset, yyyymmdd)
    new = pd.DataFrame(rows)
    if mode == "merge" and new.empty:
        return len(pd.read_parquet(path)) if path.exists() else 0

    _archive_capture(dataset, yyyymmdd, new)

    if mode == "merge" and path.exists():
        old = pd.read_parquet(path)
        out = pd.concat([old, new], ignore_index=True, sort=False)
        keys = key_columns or DATASET_KEYS.get(dataset)
        if not keys:
            raise ValueError(f"merge keys are not defined for dataset: {dataset}")
        missing = [key for key in keys if key not in out.columns]
        if missing:
            raise ValueError(f"{dataset} merge missing key columns: {missing}")
        out = out.drop_duplicates(subset=keys, keep="last")
    else:
        out = new

    _atomic_write(out, path)
    return len(out)


def partition_profile(dataset: str, yyyymmdd: str,
                      codes: list[str] | None = None) -> dict:
    """Return auditable row/code/time coverage for a partition."""
    path = WAREHOUSE / dataset / f"date={yyyymmdd}" / "part.parquet"
    if not path.exists():
        return {"available": False, "n_rows": 0, "n_codes": 0}
    df = pd.read_parquet(path)
    if codes is not None and "thscode" in df.columns:
        df = df[df["thscode"].isin(codes)]
    result = {
        "available": not df.empty,
        "n_rows": int(len(df)),
        "n_codes": int(df["thscode"].nunique()) if "thscode" in df.columns else None,
    }
    if "time_label" in df.columns and not df.empty:
        result["first_time"] = str(df["time_label"].dropna().min()) if df["time_label"].notna().any() else None
        result["last_time"] = str(df["time_label"].dropna().max()) if df["time_label"].notna().any() else None
    if dataset == "auction_point" and not df.empty:
        from roubing_engine.warehouse.timebox import row_seconds, session_type
        def resolve_session(row):
            value = row.get("session_type")
            return value if value in {"OPENING_AUCTION", "CLOSING_AUCTION", "OTHER"} \
                else session_type(row_seconds(row))
        sessions = df.apply(resolve_session, axis=1)
        result["opening_auction_rows"] = int((sessions == "OPENING_AUCTION").sum())
        result["closing_auction_rows"] = int((sessions == "CLOSING_AUCTION").sum())
    return result


def append_manifest(entry: dict) -> None:
    entry = {**entry, "logged_at": datetime.now(timezone.utc).isoformat()}
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame([entry])
    if MANIFEST_PATH.exists():
        old = pd.read_parquet(MANIFEST_PATH)
        out = pd.concat([old, new], ignore_index=True)
    else:
        out = new
    out.to_parquet(MANIFEST_PATH, engine="pyarrow", index=False)


def read_manifest() -> pd.DataFrame:
    if MANIFEST_PATH.exists():
        return pd.read_parquet(MANIFEST_PATH)
    return pd.DataFrame()
