"""Targeted capture: specific codes for ONE date (for next-day validation).

Bounded on purpose: only pulls the exact candidate codes for the single T+1
day, so the walk-forward stays lookahead-clean (no bulk pre-pull).

  python capture_codes.py --date 2026-09-09 --codes 600108.SH,600354.SH \
      --datasets auction_point,opening_match,minute_bar,trade_tick
"""
from __future__ import annotations

import argparse

from roubing_engine.collectors import intraday, storage
from roubing_engine.collectors.eltdx_client import client, to_eltdx_code
from roubing_engine.config import DATASETS


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--codes", required=True, help="comma thscodes e.g. 600108.SH,600354.SH")
    p.add_argument("--datasets", default=",".join(DATASETS))
    args = p.parse_args()

    date_dash = args.date
    yyyymmdd = date_dash.replace("-", "")
    codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    datasets = [d.strip() for d in args.datasets.split(",") if d.strip()]

    acc = {ds: [] for ds in datasets}
    counts = {ds: {"ok": 0, "empty": 0, "error": 0} for ds in datasets}
    with client() as c:
        for code in codes:
            ec = to_eltdx_code(code)
            data, status = intraday.capture_code(c, ec, date_dash, datasets)
            for ds in datasets:
                st = status.get(ds, "error:Missing")
                if st == "ok":
                    acc[ds].extend(data.get(ds, []))
                    counts[ds]["ok"] += 1
                elif st == "empty":
                    counts[ds]["empty"] += 1
                else:
                    counts[ds]["error"] += 1
            print(f"  {code}: " + " ".join(f"{ds}={status.get(ds)}" for ds in datasets))

    for ds in datasets:
        # A targeted pull is a patch to an existing partition, never a
        # replacement for all other stocks already captured that day.
        n_fetched = len(acc[ds])
        n = storage.write_dataset(ds, yyyymmdd, acc[ds], mode="merge")
        storage.append_manifest({
            "dataset": ds, "trade_date": yyyymmdd, "n_codes": len(codes),
            "capture_scope": "targeted", "write_mode": "merge",
            "n_rows": n, "n_rows_fetched": n_fetched,
            "n_ok": counts[ds]["ok"], "n_empty": counts[ds]["empty"],
            "n_error": counts[ds]["error"], "errors": f"targeted:{','.join(codes)}"[:2000],
        })
        print(f"{ds}: fetched {n_fetched} rows; partition now has {n} rows")


if __name__ == "__main__":
    main()
