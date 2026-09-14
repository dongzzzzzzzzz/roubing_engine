"""Write a self-contained task package folder for a sub-agent to consume."""
from __future__ import annotations

import json
from pathlib import Path


def write_package(task_dir: Path, instructions: str, files: dict[str, object]) -> Path:
    """Create task_dir with instructions.md, output/, and the given files.

    files: name -> object. dict/list are dumped as JSON; str written as text.
    """
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "output").mkdir(exist_ok=True)
    stale_result = task_dir / "output" / "result.json"
    if stale_result.exists():
        stale_result.unlink()
    # Reusing a run directory must not leak inputs from an older package.  In
    # particular, production Stage B/C/D no longer receive raw posts.
    for stale in ("original_posts.md", "evidence_coverage.json", "evidence_coverage.md",
                  "plan.json", "executable_plan.json", "task_candidates.json"):
        path = task_dir / stale
        if stale not in files and path.exists():
            path.unlink()
    (task_dir / "instructions.md").write_text(instructions, encoding="utf-8")
    for name, obj in files.items():
        path = task_dir / name
        if isinstance(obj, str):
            path.write_text(obj, encoding="utf-8")
        else:
            path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return task_dir
