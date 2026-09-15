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

PIPELINE_VERSION = "roubing-full-chain-v20260915"
SCHEMA_VERSION = "roubing-stage-schema-v20260915"
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


def _normalize_method_trace(value):
    if isinstance(value, dict):
        output = {key: _normalize_method_trace(child) for key, child in value.items()}
        if {"step_id", "status", "fact_ids", "counter_fact_ids"}.issubset(output):
            output.setdefault("reason_code", str(output.get("judgment") or output["step_id"]))
        return output
    if isinstance(value, list):
        return [_normalize_method_trace(child) for child in value]
    return value


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
    input_hashes = {n: _hash_file(task_dir / n) for n in input_names}
    normalized = _normalize_method_trace(result)
    return {
        "schema_version": normalized.get("schema_version") or SCHEMA_VERSION,
        "pipeline_version": normalized.get("pipeline_version") or PIPELINE_VERSION,
        "run_id": normalized.get("run_id") or task_dir.parent.name,
        "stage_id": normalized.get("stage_id") or task_dir.name,
        "fact_manifest_hash": normalized.get("fact_manifest_hash") or hashlib.sha1(
            json.dumps(input_hashes, sort_keys=True).encode("utf-8")).hexdigest()[:12],
        **normalized,
        "_provenance": {
            "backend": backend,
            "pipeline_version": PIPELINE_VERSION,
            "schema_version": SCHEMA_VERSION,
            "rules_version": RULES_VERSION,
            "code_version": code_version,
            "code_tree_hash": _hash_code_tree(),
            "working_tree_dirty": dirty,
            "instructions_hash": _hash_file(task_dir / "instructions.md"),
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "input_hashes": input_hashes,
        },
    }


def write(result: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


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
