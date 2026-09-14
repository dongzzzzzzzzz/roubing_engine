"""CI-equivalent checks that do not require model credentials or live APIs."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                   cwd=ROOT, check=True)
    subprocess.run([sys.executable, "-m", "compileall", "-q", "roubing_engine"],
                   cwd=ROOT, check=True)
    units = json.loads((ROOT / "roubing_engine/rules/corpus_units.json").read_text())
    cards = json.loads((ROOT / "roubing_engine/rules/corpus_case_cards.json").read_text())
    if len(units) != 282 or len(cards) != 282:
        raise SystemExit("corpus count check failed")
    print("local checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
