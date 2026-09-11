"""Capture candidate announcements/current F10 topic snapshots for one as-of date."""
from __future__ import annotations

import argparse

from roubing_engine.collectors import storage
from roubing_engine.collectors.eltdx_client import client
from roubing_engine.collectors.f10_context import capture_code
from roubing_engine.config import F10_DATASETS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="as-of YYYY-MM-DD")
    parser.add_argument("--codes", required=True, help="comma-separated THS codes")
    parser.add_argument("--datasets", default=",".join(F10_DATASETS))
    args = parser.parse_args()
    codes = [value.strip() for value in args.codes.split(",") if value.strip()]
    datasets = [value.strip() for value in args.datasets.split(",") if value.strip()]
    unknown = sorted(set(datasets) - set(F10_DATASETS))
    if unknown:
        raise SystemExit(f"unknown F10 datasets: {unknown}")

    accumulated = {dataset: [] for dataset in datasets}
    counts = {dataset: {"ok": 0, "empty": 0, "error": 0} for dataset in datasets}
    with client() as connection:
        for code in codes:
            data, statuses = capture_code(connection, code, args.date, datasets)
            for dataset in datasets:
                state = statuses.get(dataset, "error:Missing")
                if state == "ok":
                    accumulated[dataset].extend(data.get(dataset, []))
                    counts[dataset]["ok"] += 1
                elif state == "empty":
                    counts[dataset]["empty"] += 1
                else:
                    counts[dataset]["error"] += 1

    date_key = args.date.replace("-", "")
    for dataset in datasets:
        rows = accumulated[dataset]
        total = storage.write_dataset(dataset, date_key, rows, mode="merge")
        storage.append_manifest({
            "dataset": dataset, "trade_date": date_key,
            "capture_scope": "targeted_context", "write_mode": "merge",
            "n_codes": len(codes), "n_rows": total, "n_rows_fetched": len(rows),
            "n_ok": counts[dataset]["ok"], "n_empty": counts[dataset]["empty"],
            "n_error": counts[dataset]["error"], "errors": "",
        })
        print(f"{dataset}: fetched {len(rows)} rows; partition now has {total} rows")


if __name__ == "__main__":
    main()
