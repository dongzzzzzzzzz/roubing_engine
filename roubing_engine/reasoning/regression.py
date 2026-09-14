"""Single-day end-to-end regression entry point.

The function is intentionally serial: a failed EOD plan prevents any Stage-D
validation, and a failed earlier snapshot prevents later snapshots.
"""
from __future__ import annotations

from .eod_pipeline import run_pipeline
from .validate_pipeline import run_validation


def run_single_day(plan_date: str, tplus1: str, backend: str = "codex",
                   snapshots: tuple[str, ...] = ("AUCTION_0925", "OPEN_0935")) -> dict:
    eod = run_pipeline(plan_date, backend=backend)
    if not eod.get("ok"):
        return {"ok": False, "stage": "EOD", "eod": eod, "validations": []}
    validations = []
    for snapshot in snapshots:
        result = run_validation(plan_date, tplus1, backend=backend, snapshot=snapshot)
        validations.append(result)
        if not result.get("ok"):
            return {"ok": False, "stage": snapshot, "eod": eod,
                    "validations": validations}
    return {"ok": True, "eod": eod, "validations": validations}


def main():
    import argparse
    import json
    p = argparse.ArgumentParser()
    p.add_argument("--plan-date", required=True)
    p.add_argument("--tplus1", required=True)
    p.add_argument("--backend", default="codex", choices=["codex", "cursor"])
    args = p.parse_args()
    print(json.dumps(run_single_day(args.plan_date, args.tplus1, args.backend),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
