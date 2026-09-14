"""Reasoning-output provenance (plan §30.2): stamp every agent result with the
inputs and config needed to reproduce/audit it. No secrets are stored.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path

from roubing_engine.config import PROJECT_ROOT

RULES_VERSION = "units_v1_37+historical_versions_v1+corpus282_full+theme_registry_v2+regulatory_registry_v2"


def _hash_file(p: Path) -> str | None:
    return hashlib.sha1(p.read_bytes()).hexdigest()[:12] if p.exists() else None


def _hash_code_tree() -> str:
    digest = hashlib.sha1()
    files = sorted((PROJECT_ROOT / "roubing_engine").rglob("*.py"))
    files += sorted((PROJECT_ROOT / "roubing_engine" / "rules").glob("*.json"))
    for path in files:
        if path.name == "corpus_units.json":
            # The original-post corpus has its own per-document hashes and is
            # already captured through the task-package input hash.
            continue
        digest.update(str(path.relative_to(PROJECT_ROOT)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def stamp(result: dict, backend: str, task_dir: Path, input_names: list[str]) -> dict:
    try:
        process = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=task_dir,
            capture_output=True, text=True, check=True,
        )
        code_version = process.stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain", "--", str(PROJECT_ROOT)], cwd=task_dir,
            capture_output=True, text=True, check=True,
        ).stdout.strip())
    except Exception:  # noqa: BLE001
        code_version = "UNCOMMITTED"
        dirty = True
    return {
        **result,
        "_provenance": {
            "backend": backend,
            "rules_version": RULES_VERSION,
            "code_version": code_version,
            "code_tree_hash": _hash_code_tree(),
            "working_tree_dirty": dirty,
            "instructions_hash": _hash_file(task_dir / "instructions.md"),
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "input_hashes": {n: _hash_file(task_dir / n) for n in input_names},
        },
    }


def write(result: dict, path: Path) -> None:
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def model_view(value):
    """Remove wall-clock/runtime metadata before feeding an output downstream.

    Historical replay outputs keep ``_provenance`` in their canonical files so
    humans can audit when and how they were produced.  A later reasoning stage
    must not see that wall-clock timestamp: it is neither market data nor part
    of the frozen as-of state and can be mistaken for the replay date.
    """
    if isinstance(value, dict):
        return {
            key: model_view(child) for key, child in value.items()
            if key != "_provenance"
        }
    if isinstance(value, list):
        return [model_view(child) for child in value]
    return value
