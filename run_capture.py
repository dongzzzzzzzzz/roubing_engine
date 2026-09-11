"""Orchestrator: freeze 2026 intraday process data for the daily candidate universe.

Priority: auction_point is a ~12-month rolling window in eltdx and must be
frozen promptly; minute_bar / trade_tick have multi-year history.

Examples:
  # validate on one day, auction + opening only, cap 20 codes
  python run_capture.py --dates 2026-09-08 --datasets auction_point,opening_match --max-codes 20

  # full-year auction+opening for the whole limit roster
  python run_capture.py --start 2026-01-01 --end 2026-09-09 \
      --datasets auction_point,opening_match

  # add minutes + trades (heavy)
  python run_capture.py --dates 2026-09-08 --datasets minute_bar,trade_tick
"""
from __future__ import annotations

import argparse
import time

from roubing_engine.collectors import intraday, storage
from roubing_engine.collectors.calendar import trading_days
from roubing_engine.collectors.eltdx_client import client, to_eltdx_code
from roubing_engine.collectors.serialize import serialize_universe
from roubing_engine.config import DATASETS


def parse_args():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dates", help="comma list YYYY-MM-DD")
    g.add_argument("--start", help="range start YYYY-MM-DD (needs --end)")
    p.add_argument("--end", help="range end YYYY-MM-DD")
    p.add_argument("--datasets", default="auction_point,opening_match",
                   help=f"comma subset of {DATASETS}")
    p.add_argument("--max-codes", type=int, default=0, help="cap codes per day (0 = all)")
    p.add_argument("--year", type=int, default=2026)
    return p.parse_args()


def resolve_dates(c, args):
    if args.dates:
        return [d.strip() for d in args.dates.split(",") if d.strip()]
    days = trading_days(c, year=args.year)
    return [d for d in days if args.start <= d <= args.end]


def main():
    args = parse_args()
    datasets = [d.strip() for d in args.datasets.split(",") if d.strip()]
    for ds in datasets:
        if ds not in DATASETS:
            raise SystemExit(f"unknown dataset: {ds}")

    with client() as c:
        dates = resolve_dates(c, args)
        print(f"dates to capture: {len(dates)} | datasets={datasets} "
              f"| max_codes={args.max_codes or 'all'}")

        for date_dash in dates:
            yyyymmdd = date_dash.replace("-", "")
            t0 = time.time()

            # 1) universe (survivorship-safe roster of the day)
            rows_obj = intraday.get_universe(c, yyyymmdd)
            uni_rows = serialize_universe(rows_obj, yyyymmdd)
            n_uni = storage.write_dataset("universe", yyyymmdd, uni_rows) if uni_rows else 0
            storage.append_manifest({
                "dataset": "universe", "trade_date": yyyymmdd,
                "capture_scope": "full", "write_mode": "replace",
                "n_codes": n_uni, "n_rows": n_uni,
                "n_ok": n_uni, "n_empty": 0, "n_error": 0, "errors": "",
            })
            if not uni_rows:
                print(f"{date_dash}: empty universe (non-trading day?) skip")
                continue

            codes = [r["full_code"] for r in uni_rows if r.get("full_code")]
            if args.max_codes:
                codes = codes[: args.max_codes]

            # 2) per-code intraday, accumulate per dataset for one write/day
            acc = {ds: [] for ds in datasets}
            counts = {ds: {"ok": 0, "empty": 0, "error": 0, "errors": {}} for ds in datasets}
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
                        counts[ds]["errors"][code] = st

            # 3) write partitions + manifest
            for ds in datasets:
                # --max-codes is a targeted diagnostic capture and must not
                # erase a previously complete partition.
                mode = "merge" if args.max_codes else "replace"
                n_fetched = len(acc[ds])
                n_rows = storage.write_dataset(ds, yyyymmdd, acc[ds], mode=mode)
                c_ = counts[ds]
                storage.append_manifest({
                    "dataset": ds, "trade_date": yyyymmdd,
                    "capture_scope": "targeted" if args.max_codes else "full",
                    "write_mode": mode, "n_codes": len(codes), "n_rows": n_rows,
                    "n_rows_fetched": n_fetched,
                    "n_ok": c_["ok"], "n_empty": c_["empty"], "n_error": c_["error"],
                    "errors": str(c_["errors"])[:2000],
                })

            dt = time.time() - t0
            summary = " ".join(
                f"{ds}:{counts[ds]['ok']}ok/{counts[ds]['empty']}e/{counts[ds]['error']}x"
                for ds in datasets
            )
            print(f"{date_dash}: {len(codes)} codes | {summary} | {dt:.1f}s")


if __name__ == "__main__":
    main()
