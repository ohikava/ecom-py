"""BitGN ECOM agent built around Codex CLI + a custom MCP server.

For each task we:
  1. Open an EcomRuntime gRPC client for bootstrap + final answer submission.
  2. Pre-read tree / AGENTS.MD / /bin/date / /bin/id / context to seed the prompt.
  3. Spawn `codex exec --json --full-auto` with our ECOM MCP server attached
     (`~/.codex/config.toml` must register `bitgn-ecom` pointing at
     `ecom_mcp_server.py`). All workspace I/O during reasoning happens through
     that MCP server.
  4. Parse Codex JSONL events: extract the final agent_message JSON, token usage,
     and tool_call telemetry.
  5. Validate the response against the `TaskResult` schema and submit via
     `vm.answer`. Server-tracked grounding refs (per-task JSON file) override the
     model's self-declared refs.

The Codex loop replaces the OpenAI/OpenRouter chat loop used in experiments
001-004 — no scratchpad, no `verify(sp)`, no nudge mechanism on this side. We
own bootstrap, MCP-server lifecycle (indirectly via env), schema validation,
and answer submission.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bitgn.vm.ecom.ecom_connect import EcomRuntimeClientSync
from bitgn.vm.ecom.ecom_pb2 import (
    AnswerRequest,
    ContextRequest,
    ExecRequest,
    Outcome,
    ReadRequest,
    TreeRequest,
)
from connectrpc.errors import ConnectError
from pydantic import BaseModel, Field, ValidationError

from debug_logger import JsonlDebugLogger
from formatters import format_exec, format_read, format_tree
from http_sync_client import HttpxSyncClient
from prompts import CODEX_PREAMBLE, INSTRUCTIONS


# ── ANSI ─────────────────────────────────────────────────────────────────

CLI_RED = "\x1B[31m"
CLI_GREEN = "\x1B[32m"
CLI_YELLOW = "\x1B[33m"
CLI_BLUE = "\x1B[34m"
CLI_CYAN = "\x1B[36m"
CLI_CLR = "\x1B[0m"


# ── TaskResult schema ────────────────────────────────────────────────────


_VALID_OUTCOMES = (
    "OUTCOME_OK",
    "OUTCOME_DENIED_SECURITY",
    "OUTCOME_NONE_CLARIFICATION",
    "OUTCOME_NONE_UNSUPPORTED",
    "OUTCOME_ERR_INTERNAL",
)

_OUTCOME_BY_NAME: dict[str, Outcome] = {
    "OUTCOME_OK": Outcome.OUTCOME_OK,
    "OUTCOME_DENIED_SECURITY": Outcome.OUTCOME_DENIED_SECURITY,
    "OUTCOME_NONE_CLARIFICATION": Outcome.OUTCOME_NONE_CLARIFICATION,
    "OUTCOME_NONE_UNSUPPORTED": Outcome.OUTCOME_NONE_UNSUPPORTED,
    "OUTCOME_ERR_INTERNAL": Outcome.OUTCOME_ERR_INTERNAL,
}


class TaskResult(BaseModel):
    """Structured output schema Codex must return (validated via --output-schema)."""

    message: str = Field(..., description="Answer or summary for the task")
    outcome: str = Field(
        "OUTCOME_OK",
        description=(
            "One of OUTCOME_OK, OUTCOME_DENIED_SECURITY, OUTCOME_NONE_CLARIFICATION, "
            "OUTCOME_NONE_UNSUPPORTED, OUTCOME_ERR_INTERNAL."
        ),
    )
    grounding_refs: list[str] = Field(
        default_factory=list,
        description="Absolute workspace paths supporting the answer.",
    )
    completed_steps: list[str] = Field(
        default_factory=list,
        description="Laconic list of what was done.",
    )


@dataclass
class AgentMetrics:
    """Per-task telemetry (tokens + wall time + tool-call count)."""

    elapsed_ms: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    tool_calls: int = 0
    started_at: float = field(default_factory=time.time)

    def finalize(self) -> None:
        self.elapsed_ms = int((time.time() - self.started_at) * 1000)

    def to_dict(self) -> dict[str, int]:
        return {
            "elapsed_ms": self.elapsed_ms,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "tool_calls": self.tool_calls,
        }


# ── Config knobs (env-driven) ────────────────────────────────────────────


CODEX_TIMEOUT_SEC = int(os.environ.get("CODEX_TIMEOUT_SEC", "600"))
CODEX_REASONING_EFFORT = os.environ.get("CODEX_REASONING_EFFORT", "medium")
GROUNDING_REFS = os.environ.get("GROUNDING_REFS", "1") == "1"
COMPACT_PROMPT = os.environ.get("COMPACT_PROMPT", "1") == "1"
AUTO_DISCOVERY = os.environ.get("AUTO_DISCOVERY", "1") == "1"
MCP_SERVER_NAME = os.environ.get("MCP_SERVER_NAME", "bitgn-ecom")


# ── Bootstrap ────────────────────────────────────────────────────────────


def _bootstrap(
    vm: EcomRuntimeClientSync,
    debug_logger: JsonlDebugLogger | None,
    task_id: str | None,
    agent_run_id: str,
) -> str:
    """Pre-fetch tree, AGENTS.MD, date, id, context — return them as one text block."""
    parts: list[str] = []

    steps = [
        ("tree", lambda: vm.tree(TreeRequest(root="/", level=2)), {"root": "/", "level": 2}),
        ("read", lambda: vm.read(ReadRequest(path="/AGENTS.MD")), {"path": "/AGENTS.MD"}),
        ("exec_date", lambda: vm.exec(ExecRequest(path="/bin/date")), {"path": "/bin/date"}),
        ("exec_id", lambda: vm.exec(ExecRequest(path="/bin/id")), {"path": "/bin/id"}),
        ("context", lambda: vm.context(ContextRequest()), {}),
    ]

    for name, fn, args in steps:
        try:
            result = fn()
        except ConnectError as exc:
            err_text = f"[bootstrap {name} failed: {exc.code}: {exc.message}]"
            print(f"{CLI_YELLOW}BOOTSTRAP {name}: {exc.message}{CLI_CLR}")
            parts.append(err_text)
            if debug_logger:
                debug_logger.log(
                    "bootstrap_step",
                    task_id=task_id,
                    agent_run_id=agent_run_id,
                    step=name,
                    args=args,
                    error=str(exc.message),
                    error_code=str(exc.code),
                )
            continue

        if name == "tree":
            formatted = format_tree(result, root="/", level=2)
        elif name == "read":
            formatted = format_read(result, path="/AGENTS.MD")
        elif name == "exec_date":
            formatted = format_exec(result, path="/bin/date")
        elif name == "exec_id":
            formatted = format_exec(result, path="/bin/id")
        elif name == "context":
            unix_time = int(getattr(result, "unix_time", 0))
            time_str = getattr(result, "time", "")
            formatted = f"context\n{{\"unix_time\": {unix_time}, \"time\": \"{time_str}\"}}"
        else:  # pragma: no cover
            formatted = ""

        parts.append(formatted)
        print(f"{CLI_GREEN}BOOTSTRAP {name}{CLI_CLR}:\n{formatted}\n")
        if debug_logger:
            debug_logger.log(
                "bootstrap_step",
                task_id=task_id,
                agent_run_id=agent_run_id,
                step=name,
                args=args,
                formatted_result=formatted,
            )

    return "\n\n".join(parts)


# ── Prompt assembly ──────────────────────────────────────────────────────


def _build_full_prompt(*, bootstrap_output: str, task_text: str, hint: str) -> str:
    """Assemble preamble + instructions + bootstrap + task into one string."""
    sections: list[str] = [CODEX_PREAMBLE.rstrip(), INSTRUCTIONS.rstrip()]

    if hint.strip():
        sections.append("## Hint (from env)\n\n" + hint.strip())

    if bootstrap_output.strip():
        sections.append(
            "<bootstrap-output>\n" + bootstrap_output.rstrip() + "\n</bootstrap-output>"
        )

    sections.append("<task-system-prompt>\n" + task_text.rstrip() + "\n</task-system-prompt>")
    sections.append(
        "## TASK\n"
        + task_text.rstrip()
        + "\n\nReturn a TaskResult JSON object per the schema."
    )
    return "\n\n".join(sections)


# ── Codex schema normalisation ───────────────────────────────────────────


def _ensure_no_additional_props(schema: dict[str, Any]) -> dict[str, Any]:
    """Codex / OpenAI structured output requires additionalProperties=false on every
    object and disallows other keys alongside `$ref`. Walk the schema in place."""
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        return {"$ref": schema["$ref"]}
    if schema.get("type") == "object":
        schema["additionalProperties"] = False
    for key in ("properties", "items", "$defs", "definitions"):
        val = schema.get(key)
        if isinstance(val, dict):
            for k, v in val.items():
                if isinstance(v, dict):
                    val[k] = _ensure_no_additional_props(v)
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            schema[key] = [_ensure_no_additional_props(s) for s in schema[key]]
    return schema


def _write_temp_schema(schema: dict[str, Any]) -> str:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(schema, f)
        return f.name


# ── Codex JSONL parsing ──────────────────────────────────────────────────


def _strip_code_fence(text: str) -> str:
    """Strip ```json ... ``` fences if the model wrapped the JSON."""
    s = text.strip()
    if s.startswith("```"):
        s = s[3:]
        if s.startswith(("json", "JSON")):
            s = s[4:]
        s = s.lstrip("\n")
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def _parse_jsonl(
    output: str,
    metrics: AgentMetrics,
    debug_logger: JsonlDebugLogger | None,
    task_id: str | None,
    agent_run_id: str,
) -> tuple[str, dict[str, Any]]:
    """Walk Codex JSONL events; return (final_agent_message_text, usage)."""
    response_text = ""
    usage: dict[str, Any] = {}

    for line in output.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = event.get("type", "")

        if etype == "item.completed":
            item = event.get("item", {})
            itype = item.get("type", "")
            if itype == "agent_message":
                response_text = item.get("text", response_text)
                if debug_logger:
                    debug_logger.log(
                        "codex_agent_message",
                        task_id=task_id,
                        agent_run_id=agent_run_id,
                        text=item.get("text", ""),
                    )
            elif itype in ("tool_call", "mcp_tool_call"):
                # Codex 0.130 emits `mcp_tool_call` for MCP-server invocations and
                # `tool_call` for native tools (browser, file). Both count.
                metrics.tool_calls += 1
                if debug_logger:
                    err = item.get("error") or {}
                    debug_logger.log(
                        "codex_tool_call",
                        task_id=task_id,
                        agent_run_id=agent_run_id,
                        tool_name=item.get("tool", "") or item.get("name", ""),
                        server=item.get("server", ""),
                        arguments=str(item.get("arguments", ""))[:4000],
                        output=str(item.get("output", ""))[:4000],
                        status=item.get("status", ""),
                        error=err.get("message", "") if isinstance(err, dict) else "",
                    )
            elif itype == "user_message":
                if debug_logger:
                    debug_logger.log(
                        "codex_user_message",
                        task_id=task_id,
                        agent_run_id=agent_run_id,
                        text=item.get("text", "")[:4000],
                    )

        elif etype == "turn.completed":
            usage = event.get("usage", {}) or {}

        elif etype == "turn.failed":
            err = event.get("error", {}) or {}
            raise RuntimeError(f"Codex turn failed: {err.get('message', 'unknown error')}")

    return response_text, usage


def _apply_usage(metrics: AgentMetrics, usage: dict[str, Any]) -> None:
    if not usage:
        return
    metrics.input_tokens += int(usage.get("input_tokens", 0) or 0)
    metrics.cached_input_tokens += int(usage.get("cached_input_tokens", 0) or 0)
    metrics.output_tokens += int(usage.get("output_tokens", 0) or 0)
    # Codex 0.130 emits the flat key `reasoning_output_tokens` at the usage top
    # level; older versions used `output_tokens_details.reasoning_tokens`. Read
    # both so we don't silently lose the metric across version bumps.
    reasoning = int(usage.get("reasoning_output_tokens", 0) or 0)
    if not reasoning:
        details = usage.get("output_tokens_details") or {}
        reasoning = int(details.get("reasoning_tokens", 0) or 0)
    metrics.reasoning_tokens += reasoning


# ── Server-side refs ─────────────────────────────────────────────────────


def _read_server_refs(refs_path: str) -> list[str]:
    """Read and consume the MCP-server-tracked grounding refs JSON file."""
    try:
        if not os.path.exists(refs_path):
            return []
        with open(refs_path, encoding="utf-8") as f:
            data = json.load(f)
        os.unlink(refs_path)
        if isinstance(data, list):
            return [str(p) for p in data]
        return []
    except (OSError, json.JSONDecodeError) as exc:
        print(f"{CLI_YELLOW}failed to read server refs ({refs_path}): {exc}{CLI_CLR}")
        return []


# ── Codex argv ───────────────────────────────────────────────────────────


def _build_codex_cmd(
    *,
    model: str,
    harness_url: str,
    refs_path: str,
    log_path: str,
    schema_path: str,
    compact_prompt_path: str | None,
    full_prompt: str,
) -> list[str]:
    """Assemble the argv for `codex exec`.

    Note: we override the MCP server's per-task env via `-c mcp_servers.<name>.env.X=...`.
    `~/.codex/config.toml` must already register the `bitgn-ecom` MCP server pointing at
    `ecom_mcp_server.py`; this argv only rewrites the per-task env. See README.
    """
    # Codex 0.130 removed `--full-auto`. In `exec` (non-interactive) mode every
    # MCP tool call triggers `request_user_input`, which is unsupported in exec
    # and silently auto-cancels (visible in the JSONL as
    # `error: user cancelled MCP tool call`). The only way to make MCP tools
    # actually run is `--dangerously-bypass-approvals-and-sandbox`. We rely on
    # the runtime sandbox being external (BitGN VM is virtual, no real FS),
    # so this is acceptable for this experiment but not safe in general.
    cmd = [
        "codex",
        "exec",
        "--json",
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
        "-m",
        model,
        "-c",
        f"model_reasoning_effort={CODEX_REASONING_EFFORT}",
        "-c",
        f'mcp_servers.{MCP_SERVER_NAME}.env.VAULT_HARNESS_URL="{harness_url}"',
        "-c",
        f'mcp_servers.{MCP_SERVER_NAME}.env.VAULT_MCP_REFS="{refs_path}"',
        "-c",
        f'mcp_servers.{MCP_SERVER_NAME}.env.VAULT_MCP_LOG="{log_path}"',
    ]
    if compact_prompt_path:
        cmd += ["-c", f"experimental_compact_prompt_file={compact_prompt_path}"]
    cmd += ["--output-schema", schema_path, full_prompt]
    return cmd


# ── Answer submission helpers ────────────────────────────────────────────


def _submit_answer(
    vm: EcomRuntimeClientSync,
    outcome_name: str,
    message: str,
    refs: list[str],
) -> None:
    outcome_value = _OUTCOME_BY_NAME.get(outcome_name, Outcome.OUTCOME_ERR_INTERNAL)
    vm.answer(AnswerRequest(message=message, outcome=outcome_value, refs=list(refs)))


def _submit_error(vm: EcomRuntimeClientSync, message: str) -> None:
    try:
        _submit_answer(vm, "OUTCOME_ERR_INTERNAL", message, [])
    except Exception as exc:  # pragma: no cover
        print(f"{CLI_RED}fallback answer failed: {exc}{CLI_CLR}")


# ── Entry point ──────────────────────────────────────────────────────────


def run_codex_agent(
    model: str,
    harness_url: str,
    task_text: str,
    task_id: str | None = None,
    debug_logger: JsonlDebugLogger | None = None,
) -> AgentMetrics:
    """Run a single ECOM task through `codex exec`.

    Contract from main.py: one trial → one call. The function always submits
    *some* answer to the harness (either the parsed TaskResult or an
    OUTCOME_ERR_INTERNAL fallback) before returning.
    """
    metrics = AgentMetrics()
    agent_run_id = f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-{int(time.time() * 1000)}"
    hint = os.environ.get("HINT", "")

    vm = EcomRuntimeClientSync(harness_url, http_client=HttpxSyncClient())

    if debug_logger:
        debug_logger.log(
            "agent_started",
            task_id=task_id,
            agent_run_id=agent_run_id,
            model=model,
            harness_url=harness_url,
            task_text=task_text,
            reasoning_effort=CODEX_REASONING_EFFORT,
            hint_present=bool(hint),
        )

    # 1. Bootstrap
    bootstrap_output = _bootstrap(vm, debug_logger, task_id, agent_run_id) if AUTO_DISCOVERY else ""

    # 2. Prompt
    full_prompt = _build_full_prompt(
        bootstrap_output=bootstrap_output, task_text=task_text, hint=hint
    )

    # 3. Schema (Codex requires additionalProperties=false and all properties in required)
    schema = _ensure_no_additional_props(TaskResult.model_json_schema())
    if "properties" in schema:
        schema["required"] = list(schema["properties"].keys())
    schema_path = _write_temp_schema(schema)

    # 4. Per-task temp files
    here = Path(__file__).resolve().parent
    compact_prompt_path = str(here / "compact_prompt.md") if COMPACT_PROMPT else None
    log_path = str(here / "ecom_mcp.log")
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump([], f)
        refs_path = f.name

    cmd = _build_codex_cmd(
        model=model,
        harness_url=harness_url,
        refs_path=refs_path,
        log_path=log_path,
        schema_path=schema_path,
        compact_prompt_path=compact_prompt_path,
        full_prompt=full_prompt,
    )

    if debug_logger:
        debug_logger.log(
            "codex_prompt",
            task_id=task_id,
            agent_run_id=agent_run_id,
            prompt_chars=len(full_prompt),
            prompt=full_prompt,
            cmd=cmd[:-1] + ["<full_prompt>"],
        )

    print(f"\n{CLI_CYAN}Running codex exec ({model}, effort={CODEX_REASONING_EFFORT})…{CLI_CLR}")

    # 5. Run Codex
    response_text = ""
    usage: dict[str, Any] = {}
    parse_error: str | None = None

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=CODEX_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        msg = f"codex exec timed out after {CODEX_TIMEOUT_SEC}s"
        print(f"{CLI_RED}{msg}{CLI_CLR}")
        if debug_logger:
            debug_logger.log("codex_timeout", task_id=task_id, agent_run_id=agent_run_id)
        _submit_error(vm, msg)
        metrics.finalize()
        if debug_logger:
            debug_logger.log("agent_metrics", task_id=task_id, agent_run_id=agent_run_id, **metrics.to_dict())
        return metrics
    except FileNotFoundError:
        msg = "codex CLI not found on PATH — install Codex CLI and `codex login` first"
        print(f"{CLI_RED}{msg}{CLI_CLR}")
        if debug_logger:
            debug_logger.log("codex_not_found", task_id=task_id, agent_run_id=agent_run_id)
        _submit_error(vm, msg)
        metrics.finalize()
        if debug_logger:
            debug_logger.log("agent_metrics", task_id=task_id, agent_run_id=agent_run_id, **metrics.to_dict())
        return metrics

    output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")

    if debug_logger:
        debug_logger.log(
            "codex_finished",
            task_id=task_id,
            agent_run_id=agent_run_id,
            returncode=result.returncode,
            stdout_chars=len(result.stdout or ""),
            stderr_chars=len(result.stderr or ""),
        )

    if result.returncode != 0 and not (result.stdout or "").strip():
        msg = f"codex exec failed (rc={result.returncode}): {(result.stderr or '')[:500]}"
        print(f"{CLI_RED}{msg}{CLI_CLR}")
        _submit_error(vm, msg)
        metrics.finalize()
        if debug_logger:
            debug_logger.log("agent_metrics", task_id=task_id, agent_run_id=agent_run_id, **metrics.to_dict())
        return metrics

    # 6. Parse JSONL
    try:
        response_text, usage = _parse_jsonl(
            output, metrics, debug_logger, task_id, agent_run_id
        )
    except RuntimeError as exc:
        parse_error = str(exc)
        print(f"{CLI_RED}{parse_error}{CLI_CLR}")

    _apply_usage(metrics, usage)

    if debug_logger:
        debug_logger.log(
            "codex_usage",
            task_id=task_id,
            agent_run_id=agent_run_id,
            **{k: v for k, v in metrics.to_dict().items() if k != "elapsed_ms"},
        )

    # 7. Validate response → TaskResult
    if parse_error or not response_text.strip():
        msg = parse_error or "empty response from codex exec"
        _submit_error(vm, msg)
        metrics.finalize()
        if debug_logger:
            debug_logger.log("agent_metrics", task_id=task_id, agent_run_id=agent_run_id, **metrics.to_dict())
        return metrics

    cleaned = _strip_code_fence(response_text)
    try:
        task_result = TaskResult.model_validate_json(cleaned)
    except ValidationError as exc:
        msg = f"TaskResult schema mismatch: {exc.errors()[:3]}"
        print(f"{CLI_RED}{msg}{CLI_CLR}")
        if debug_logger:
            debug_logger.log(
                "codex_schema_error",
                task_id=task_id,
                agent_run_id=agent_run_id,
                error=str(exc),
                response_text=cleaned[:4000],
            )
        _submit_error(vm, msg)
        metrics.finalize()
        if debug_logger:
            debug_logger.log("agent_metrics", task_id=task_id, agent_run_id=agent_run_id, **metrics.to_dict())
        return metrics

    if task_result.outcome not in _VALID_OUTCOMES:
        print(f"{CLI_YELLOW}unknown outcome {task_result.outcome!r}, coercing to ERR_INTERNAL{CLI_CLR}")
        task_result.outcome = "OUTCOME_ERR_INTERNAL"

    # 8. Override grounding_refs with MCP-server-tracked set if enabled
    server_refs = _read_server_refs(refs_path)
    if GROUNDING_REFS and server_refs:
        model_refs = list(task_result.grounding_refs)
        task_result.grounding_refs = sorted(set(server_refs))
        if debug_logger:
            debug_logger.log(
                "refs_override",
                task_id=task_id,
                agent_run_id=agent_run_id,
                server_refs=server_refs,
                model_refs=model_refs,
            )

    # 9. Submit final answer
    try:
        _submit_answer(
            vm,
            task_result.outcome,
            task_result.message,
            list(task_result.grounding_refs),
        )
    except Exception as exc:
        print(f"{CLI_RED}submit error: {exc}{CLI_CLR}")
        if debug_logger:
            debug_logger.log(
                "submit_error",
                task_id=task_id,
                agent_run_id=agent_run_id,
                error=str(exc),
            )

    # 10. Final logging
    status_color = CLI_GREEN if task_result.outcome == "OUTCOME_OK" else CLI_YELLOW
    print(f"\n{status_color}=== Agent {task_result.outcome} ==={CLI_CLR}")
    for step in task_result.completed_steps:
        print(f"  - {step}")
    print(f"{CLI_BLUE}ANSWER: {task_result.message}{CLI_CLR}")
    for ref in task_result.grounding_refs:
        print(f"  ref: {CLI_BLUE}{ref}{CLI_CLR}")

    metrics.finalize()

    if debug_logger:
        debug_logger.log(
            "agent_completed",
            task_id=task_id,
            agent_run_id=agent_run_id,
            outcome=task_result.outcome,
            message=task_result.message,
            grounding_refs=list(task_result.grounding_refs),
            completed_steps=list(task_result.completed_steps),
        )
        debug_logger.log(
            "agent_metrics",
            task_id=task_id,
            agent_run_id=agent_run_id,
            **metrics.to_dict(),
        )

    return metrics


# ── Compatibility shim ───────────────────────────────────────────────────


def run_agent(
    model: str,
    harness_url: str,
    task_text: str,
    task_id: str | None = None,
    debug_logger: JsonlDebugLogger | None = None,
) -> None:
    """Match the signature main.py expects from 001–004."""
    try:
        run_codex_agent(
            model=model,
            harness_url=harness_url,
            task_text=task_text,
            task_id=task_id,
            debug_logger=debug_logger,
        )
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # pragma: no cover
        print(f"{CLI_RED}codex agent crashed: {exc}{CLI_CLR}", file=sys.stderr)
        if debug_logger:
            debug_logger.log(
                "agent_crashed",
                task_id=task_id,
                error=str(exc),
                error_type=exc.__class__.__name__,
            )
        try:
            vm = EcomRuntimeClientSync(harness_url, http_client=HttpxSyncClient())
            _submit_error(vm, f"agent crashed: {exc.__class__.__name__}: {exc}")
        except Exception:
            pass


# Force-import datetime/timezone used implicitly by logging (kept explicit so the
# import isn't pruned by IDE auto-organisers).
_ = (datetime, timezone)
