"""Agent runner: drive the EOD reasoning layer via Codex / Cursor sub-agents.

No LLM API key is used. Each reasoning step is executed by launching a
sub-agent (codex exec / cursor-agent -p) against a self-contained *task
package* folder, and reading back a schema-validated result.json.

Task package layout (written by the pipeline, one folder per step):
  <task_dir>/
    instructions.md      # the step's prompt + hard contract (see plan §28)
    facts.json           # deterministic facts available at as_of
    rules.md             # retrieved roubing evidence units (plan §23)
    yesterday_state.json # prior-day ledger (for state migration)
    schema.json          # JSON schema the agent MUST satisfy
    output/result.json   # <- the sub-agent writes this; we read+validate it

The sub-agent is instructed to ONLY write output/result.json and nothing else.
This is more robust than parsing stdout.

Backends (both use the models included in your subscription):
  codex  : codex exec  "<instructions>"          (cwd = task_dir)
  cursor : cursor-agent -p --force --output-format json --workspace <task_dir>

NOTE: exact sandbox/approval flags are validated when P1 is built; the two
build_*_cmd helpers below centralize them.
"""
from __future__ import annotations

import json
import subprocess
import datetime as dt
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AgentTask:
    task_dir: Path
    instructions: str
    timeout_s: int = 1800


def _result_path(task_dir: Path) -> Path:
    return task_dir / "output" / "result.json"


def build_codex_cmd(task: AgentTask) -> list[str]:
    # codex exec reads the prompt arg and works in cwd; allow workspace writes,
    # no approval prompts (fully non-interactive).
    return [
        "codex", "exec", "--skip-git-repo-check",
        "-c", 'sandbox_mode="workspace-write"',
        "-c", 'approval_policy="never"',
        task.instructions,
    ]


def build_cursor_cmd(task: AgentTask) -> list[str]:
    return [
        "cursor-agent", "-p", "--force", "--trust",
        "--output-format", "json",
        "--workspace", str(task.task_dir.resolve()),
        task.instructions,
    ]


def run(task: AgentTask, backend: str = "codex") -> dict:
    """Execute one reasoning step; return the parsed, validated result dict."""
    (task.task_dir / "output").mkdir(parents=True, exist_ok=True)
    out = _result_path(task.task_dir)
    if out.exists():
        out.unlink()

    if backend == "codex":
        cmd = build_codex_cmd(task)
    elif backend == "cursor":
        cmd = build_cursor_cmd(task)
    else:
        raise ValueError(f"unknown backend: {backend}")

    subprocess.run(cmd, cwd=task.task_dir, timeout=task.timeout_s, check=True)

    if not out.exists():
        raise RuntimeError(f"{backend} did not produce {out}")
    return json.loads(out.read_text(encoding="utf-8"))


def validate(result: dict, schema: dict) -> list[str]:
    """Validate a result against the project's strict JSON-schema subset."""
    problems: list[str] = []

    def check(value, spec, path: str) -> None:
        expected = spec.get("type")
        allowed = expected if isinstance(expected, list) else [expected] if expected else []
        type_ok = {
            "object": lambda x: isinstance(x, dict),
            "array": lambda x: isinstance(x, list),
            "string": lambda x: isinstance(x, str),
            "boolean": lambda x: isinstance(x, bool),
            "number": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
            "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
            "null": lambda x: x is None,
        }
        if allowed and not any(type_ok[t](value) for t in allowed):
            problems.append(f"{path}: expected {'|'.join(allowed)}, got {type(value).__name__}")
            return
        if "enum" in spec and value not in spec["enum"]:
            problems.append(f"{path}: value {value!r} not in enum")
        if isinstance(value, str) and len(value) < spec.get("minLength", 0):
            problems.append(f"{path}: empty string is not allowed")
        if isinstance(value, str) and spec.get("format") == "date":
            try:
                dt.date.fromisoformat(value)
            except ValueError:
                problems.append(f"{path}: expected YYYY-MM-DD date")
        if isinstance(value, list):
            if len(value) < spec.get("minItems", 0):
                problems.append(f"{path}: expected at least {spec['minItems']} items")
            item_spec = spec.get("items")
            if item_spec:
                for index, item in enumerate(value):
                    check(item, item_spec, f"{path}[{index}]")
        if isinstance(value, dict):
            for key in spec.get("required", []):
                if key not in value:
                    problems.append(f"{path}: missing required field {key!r}")
            for key, child_spec in spec.get("properties", {}).items():
                if key in value:
                    check(value[key], child_spec, f"{path}.{key}")

    check(result, schema, "$")
    return problems
