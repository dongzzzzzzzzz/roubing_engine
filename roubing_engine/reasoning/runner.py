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
import os
import signal
import shutil
import subprocess
import datetime as dt
import tempfile
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AgentTask:
    task_dir: Path
    instructions: str
    timeout_s: int = 1800


FORBIDDEN_SKILL_MARKERS = ("capital-destination-reasoner", "serenity-skill")


class SkillContaminationError(RuntimeError):
    pass


def detect_skill_contamination(text: str) -> list[str]:
    haystack = text or ""
    return [marker for marker in FORBIDDEN_SKILL_MARKERS if marker in haystack]


_EXECUTION_CONFIG_KEYS = (
    "model",
    "model_provider",
    "model_reasoning_effort",
    "model_reasoning_summary",
    "model_verbosity",
    "model_context_window",
    "model_auto_compact_token_limit",
    "openai_base_url",
    "disable_response_storage",
)


def _source_codex_home() -> Path:
    override = os.environ.get("ROUBING_CODEX_SOURCE_HOME")
    return Path(override).expanduser() if override else Path.home() / ".codex"


def _toml_value(value) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(
            f"{json.dumps(str(key), ensure_ascii=False)} = {_toml_value(item)}"
            for key, item in value.items()
        ) + " }"
    raise TypeError(f"unsupported Codex config value type: {type(value).__name__}")


def _execution_config(source: Path) -> str:
    """Keep only model/provider settings required for an isolated model call.

    cc-switch and similar routers configure Codex through ``model_provider``
    plus a matching ``model_providers.<id>`` table.  Dropping that table sends
    the child to the built-in OpenAI endpoint; copying the whole user config
    would re-enable MCP servers, plugins, hooks and notifications.  This
    function preserves the former while deliberately excluding the latter.
    """
    config_path = source / "config.toml"
    if not config_path.exists():
        return "disable_response_storage = true\n"
    parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
    # A regression may use a model exposed by the same cc-switch provider
    # without mutating the user's global selection.  The provider, endpoint
    # and authentication still come from the active user configuration.
    model_override = os.environ.get("ROUBING_CODEX_MODEL")
    if model_override:
        parsed["model"] = model_override
    lines: list[str] = []
    for key in _EXECUTION_CONFIG_KEYS:
        if key in parsed:
            lines.append(f"{key} = {_toml_value(parsed[key])}")
    if "disable_response_storage" not in parsed:
        lines.append("disable_response_storage = true")

    provider_id = parsed.get("model_provider")
    providers = parsed.get("model_providers", {})
    provider = providers.get(provider_id) if isinstance(providers, dict) else None
    if provider_id and provider_id not in {"openai", "ollama", "lmstudio"}:
        if not isinstance(provider, dict):
            raise RuntimeError(
                f"model_provider {provider_id!r} has no matching model_providers table")
        lines.append("")
        lines.append(f"[model_providers.{json.dumps(provider_id, ensure_ascii=False)}]")
        for key, value in provider.items():
            lines.append(f"{key} = {_toml_value(value)}")
    return "\n".join(lines) + "\n"


def _isolated_codex_home() -> str:
    """Create a minimal Codex home with auth and execution provider only."""
    source = _source_codex_home()
    isolated = Path(tempfile.mkdtemp(prefix="roubing-codex-home-"))
    auth = source / "auth.json"
    if auth.exists():
        (isolated / "auth.json").symlink_to(auth)
    (isolated / "config.toml").write_text(_execution_config(source), encoding="utf-8")
    return str(isolated)


def _result_path(task_dir: Path) -> Path:
    return task_dir / "output" / "result.json"


def _read_complete_result(path: Path) -> dict | None:
    """Return a completely written JSON object, otherwise keep waiting."""
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _stop_process_group(proc: subprocess.Popen, grace_s: float = 3.0) -> None:
    """Stop a hung CLI together with any provider/helper descendants."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=grace_s)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    proc.wait(timeout=grace_s)


def _run_child(cmd: list[str], *, cwd: Path, timeout: int, env: dict,
               stdout_path: Path, stderr_path: Path, result_path: Path
               ) -> tuple[int, dict | None, bool]:
    """Run a model CLI without waiting forever after it has written JSON.

    Some routed ``codex exec`` processes finish the requested file write but
    remain alive in provider shutdown.  The task result is the file, not the
    CLI epilogue, so after a complete JSON object appears we give the process
    a short exit grace and then stop the isolated process group.
    """
    deadline = time.monotonic() + timeout
    result: dict | None = None
    stopped_after_result = False
    with stdout_path.open("w", encoding="utf-8") as stdout_file, \
            stderr_path.open("w", encoding="utf-8") as stderr_file:
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=stdout_file, stderr=stderr_file,
            text=True, env=env, start_new_session=True,
        )
        while True:
            result = _read_complete_result(result_path)
            returncode = proc.poll()
            if result is not None:
                if returncode is None:
                    try:
                        returncode = proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        stopped_after_result = True
                        _stop_process_group(proc)
                        returncode = proc.returncode
                break
            if returncode is not None:
                break
            if time.monotonic() >= deadline:
                _stop_process_group(proc)
                raise subprocess.TimeoutExpired(cmd, timeout)
            time.sleep(0.25)
    return int(returncode or 0), result, stopped_after_result


def build_codex_cmd(task: AgentTask) -> list[str]:
    # codex exec reads the prompt arg and works in cwd; allow workspace writes,
    # no approval prompts (fully non-interactive).
    guarded = ("环境隔离要求：本任务禁止使用、读取、调用或提及任何外部投资 skill；"
               "只使用任务目录中的文件。\n\n"
               + task.instructions)
    return [
        "codex", "exec", "--skip-git-repo-check",
        "--ephemeral", "--ignore-rules", "--color", "never",
        "--disable", "plugins", "--disable", "remote_plugin",
        "--disable", "recommended_plugins", "--disable", "apps",
        "--disable", "skill_search",
        "-c", 'sandbox_mode="workspace-write"',
        "-c", 'approval_policy="never"',
        guarded,
    ]


def build_cursor_cmd(task: AgentTask) -> list[str]:
    guarded = ("环境隔离要求：本任务禁止使用、读取、调用或提及任何外部投资 skill；"
               "只使用任务目录中的文件。\n\n"
               + task.instructions)
    return [
        "cursor-agent", "-p", "--force", "--trust",
        "--output-format", "json",
        "--workspace", str(task.task_dir.resolve()),
        guarded,
    ]


def run(task: AgentTask, backend: str = "codex") -> dict:
    """Execute one reasoning step; return the parsed, validated result dict."""
    (task.task_dir / "output").mkdir(parents=True, exist_ok=True)
    out = _result_path(task.task_dir)
    if out.exists():
        out.unlink()
    contamination_path = task.task_dir / "contamination.json"
    if contamination_path.exists():
        contamination_path.unlink()

    if backend == "codex":
        cmd = build_codex_cmd(task)
    elif backend == "cursor":
        cmd = build_cursor_cmd(task)
    else:
        raise ValueError(f"unknown backend: {backend}")

    # Capture child output for auditability and to detect automatic loading of
    # unrelated investment skills.  Secrets are never written to the env
    # summary; only stable process metadata is recorded.
    env_summary = {key: os.environ.get(key) for key in
                   ("PATH", "PYTHONPATH") if os.environ.get(key)}
    env_summary["isolation"] = {
        "codex_home": "ephemeral_minimal",
        "model_provider": "preserved_from_user_config",
        "model_override": os.environ.get("ROUBING_CODEX_MODEL"),
        "user_rules": "disabled",
        "plugins": "disabled",
        "external_skills": "disabled_and_scanned",
    }
    (task.task_dir / "environment_summary.json").write_text(
        json.dumps(env_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    child_env = os.environ.copy()
    isolated_home: str | None = None
    if backend == "codex":
        isolated_home = _isolated_codex_home()
        child_env["CODEX_HOME"] = isolated_home
    stdout_path = task.task_dir / "stdout.log"
    stderr_path = task.task_dir / "stderr.log"
    try:
        returncode, result, stopped_after_result = _run_child(
            cmd, cwd=task.task_dir, timeout=task.timeout_s, env=child_env,
            stdout_path=stdout_path, stderr_path=stderr_path, result_path=out,
        )
    finally:
        if isolated_home:
            shutil.rmtree(isolated_home, ignore_errors=True)
    stdout = stdout_path.read_text(encoding="utf-8") if stdout_path.exists() else ""
    stderr = stderr_path.read_text(encoding="utf-8") if stderr_path.exists() else ""
    contamination = detect_skill_contamination(stdout + "\n" + stderr)
    if contamination:
        contamination_path.write_text(
            json.dumps({"status": "CONTAMINATED", "markers": contamination},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        raise SkillContaminationError(
            f"forbidden external skill detected: {', '.join(contamination)}")
    if returncode != 0 and not stopped_after_result:
        raise subprocess.CalledProcessError(returncode, cmd,
                                            output=stdout, stderr=stderr)

    if result is None:
        raise RuntimeError(f"{backend} did not produce {out}")
    return result


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
