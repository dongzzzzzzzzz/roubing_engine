"""Complete walk-forward driver with physically separated information stages.

For each trading day D:
  1. capture D facts;
  2. validate the approved previous plan at AUCTION_0925 and OPEN_0935;
  3. write D-close outcomes into evaluation only;
  4. build and audit D's new EOD plan.

Outcome files are never inputs to Stage B/C/D.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from roubing_engine.collectors import intraday, storage
from roubing_engine.collectors.calendar import trading_days
from roubing_engine.collectors.eltdx_client import client, to_eltdx_code
from roubing_engine.collectors.serialize import serialize_universe
from roubing_engine.config import PROJECT_ROOT
from roubing_engine.evaluation.outcome import evaluate_candidates
from roubing_engine.reasoning.eod_pipeline import run_pipeline
from roubing_engine.reasoning.validate_pipeline import run_validation
from roubing_engine.state.ledger import append_followup

RUNS = PROJECT_ROOT / "runs"


def _capture_day(c, date_dash: str, datasets):
    yyyymmdd = date_dash.replace("-", "")
    rows_obj = intraday.get_universe(c, yyyymmdd)
    universe = serialize_universe(rows_obj, yyyymmdd)
    if not universe:
        return 0
    n_universe = storage.write_dataset("universe", yyyymmdd, universe, mode="replace")
    storage.append_manifest({
        "dataset": "universe", "trade_date": yyyymmdd,
        "capture_scope": "full", "write_mode": "replace",
        "n_codes": n_universe, "n_rows": n_universe, "n_rows_fetched": len(universe),
        "n_ok": n_universe, "n_empty": 0, "n_error": 0, "errors": "",
    })

    codes = [row["full_code"] for row in universe if row.get("full_code")]
    acc = {dataset: [] for dataset in datasets}
    counts = {dataset: {"ok": 0, "empty": 0, "error": 0} for dataset in datasets}
    for code in codes:
        data, status = intraday.capture_code(c, to_eltdx_code(code), date_dash, datasets)
        for dataset in datasets:
            state = status.get(dataset, "error:Missing")
            if state == "ok":
                acc[dataset].extend(data.get(dataset, []))
                counts[dataset]["ok"] += 1
            elif state == "empty":
                counts[dataset]["empty"] += 1
            else:
                counts[dataset]["error"] += 1
    for dataset in datasets:
        rows = acc[dataset]
        total = storage.write_dataset(dataset, yyyymmdd, rows, mode="replace") if rows else 0
        storage.append_manifest({
            "dataset": dataset, "trade_date": yyyymmdd,
            "capture_scope": "full_limit_roster", "write_mode": "replace",
            "n_codes": len(codes), "n_rows": total, "n_rows_fetched": len(rows),
            "n_ok": counts[dataset]["ok"], "n_empty": counts[dataset]["empty"],
            "n_error": counts[dataset]["error"], "errors": "",
        })
    return len(codes)


def _approved_plan(plan_date: str) -> dict | None:
    run_dir = RUNS / plan_date
    status = run_dir / "run_status.json"
    plan = run_dir / "stage_c_result.json"
    if not status.exists() or not plan.exists():
        return None
    if json.loads(status.read_text(encoding="utf-8")).get("status") != "APPROVED":
        return None
    return json.loads(plan.read_text(encoding="utf-8"))


def _capture_plan_candidates(c, plan_date: str, tplus1: str, datasets) -> int:
    plan = _approved_plan(plan_date)
    if not plan:
        return 0
    codes = sorted({item.get("thscode") for item in plan.get("candidates", []) if item.get("thscode")})
    yyyymmdd = tplus1.replace("-", "")
    acc = {dataset: [] for dataset in datasets}
    counts = {dataset: {"ok": 0, "empty": 0, "error": 0} for dataset in datasets}
    for code in codes:
        data, statuses = intraday.capture_code(c, to_eltdx_code(code), tplus1, datasets)
        for dataset in datasets:
            state = statuses.get(dataset, "error:Missing")
            if state == "ok":
                acc[dataset].extend(data.get(dataset, []))
                counts[dataset]["ok"] += 1
            elif state == "empty":
                counts[dataset]["empty"] += 1
            else:
                counts[dataset]["error"] += 1
    for dataset in datasets:
        total = storage.write_dataset(dataset, yyyymmdd, acc[dataset], mode="merge")
        storage.append_manifest({
            "dataset": dataset, "trade_date": yyyymmdd,
            "capture_scope": "targeted_plan_candidates", "write_mode": "merge",
            "plan_date": plan_date, "n_codes": len(codes), "n_rows": total,
            "n_rows_fetched": len(acc[dataset]), "n_ok": counts[dataset]["ok"],
            "n_empty": counts[dataset]["empty"], "n_error": counts[dataset]["error"],
            "errors": "",
        })
    return len(codes)


def _write_outcome(plan_date: str, tplus1: str, plan: dict) -> Path:
    evaluation_dir = RUNS / plan_date / "evaluation"
    evaluation_dir.mkdir(parents=True, exist_ok=True)
    # At T+1 close only the one-day outcome is available. Longer horizons must
    # be computed by a later evaluation run with a correspondingly later as_of.
    evaluation_cohort = [
        {**candidate, "selection_status": "SELECTED"}
        for candidate in plan.get("candidates", [])
    ] + [
        {**candidate, "selection_status": "EXCLUDED", "role": None,
         "output_tier": "同期排除"}
        for candidate in plan.get("excluded_candidates", [])
    ]
    outcome = evaluate_candidates(evaluation_cohort, plan_date, horizons=(1,))
    outcome.update({
        "tplus1": tplus1,
        "evaluation_as_of": f"{tplus1} CLOSE",
        "information_class": "POST_PLAN_OUTCOME_EVALUATION_ONLY",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "discipline": "不得输入 Stage B/C/D，不得用于改写冻结计划",
    })
    path = evaluation_dir / f"outcome_{tplus1}.json"
    path.write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8")
    append_followup(plan_date, tplus1, outcome_file=str(path), status="EVALUATED_AT_CLOSE")
    return path


def _follow_previous_day(plan_date: str, tplus1: str, backend: str,
                         validation_dry_run: bool) -> dict:
    plan = _approved_plan(plan_date)
    if not plan:
        return {"status": "SKIPPED_NO_APPROVED_PLAN", "plan_date": plan_date}
    results = []
    for snapshot in ("AUCTION_0925", "OPEN_0935"):
        result = run_validation(
            plan_date, tplus1, backend=backend,
            dry_run=validation_dry_run, snapshot=snapshot,
        )
        results.append(result)
        if not validation_dry_run:
            append_followup(
                plan_date, tplus1, snapshot=snapshot,
                result_file=result.get("result_file"), status="VALIDATED",
            )
    outcome = None if validation_dry_run else str(_write_outcome(plan_date, tplus1, plan))
    return {"status": "FOLLOWUP_COMPLETE", "validations": results, "outcome": outcome}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--backend", default="codex", choices=["codex", "cursor"])
    parser.add_argument("--datasets", default="auction_point,opening_match,minute_bar,trade_tick")
    parser.add_argument("--capture-only", action="store_true")
    parser.add_argument("--no-capture", action="store_true", help="data already captured")
    parser.add_argument("--skip-followup", action="store_true")
    parser.add_argument("--validation-dry-run", action="store_true")
    args = parser.parse_args()
    datasets = [value.strip() for value in args.datasets.split(",") if value.strip()]

    with client() as connection:
        days = [day for day in trading_days(connection, year=int(args.start[:4]))
                if args.start <= day <= args.end]
        print(f"walk-forward {len(days)} days")
        for index, day in enumerate(days):
            if not args.no_capture:
                count = _capture_day(connection, day, datasets)
                print(f"{day}: captured current roster {count} codes")
                if not count:
                    continue
                if index > 0 and not args.skip_followup:
                    previous = days[index - 1].replace("-", "")
                    count = _capture_plan_candidates(connection, previous, day, datasets)
                    print(f"{day}: merged {count} previous-plan candidates")
            if args.capture_only:
                continue

            if index > 0 and not args.skip_followup:
                previous = days[index - 1].replace("-", "")
                followup = _follow_previous_day(
                    previous, day, args.backend, args.validation_dry_run)
                print(f"{day}: previous-plan followup {followup.get('status')}")

            output = run_pipeline(day.replace("-", ""), backend=args.backend, with_daily=True)
            print(f"{day}: EOD {output.get('status') or output}")


if __name__ == "__main__":
    main()
