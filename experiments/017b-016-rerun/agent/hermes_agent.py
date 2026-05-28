"""BitGN ECOM agent built around Hermes CLI + the same custom MCP server.

Port of experiment 011 (codex_agent.py) — only the subprocess backend changes:

  011: `codex exec --json` (Codex CLI, gpt-5.4 via ChatGPT auth)
  015: `hermes -z PROMPT` (Hermes CLI, deepseek/deepseek-v4-pro via OpenRouter)

Everything else is preserved verbatim: the bootstrap sequence, the prompts
(`CODEX_PREAMBLE` + `INSTRUCTIONS`), the per-task refs file consumed from
the MCP server, and the DENIED/exclusion refs sanitisers.

Isolation:
  - HERMES_HOME points at experiments/015-hermes-deepseek/agent/hermes_home,
    a self-contained home directory holding config.yaml.  The config enables
    only the bitgn-ecom MCP server and disables every built-in toolset
    (terminal, file, web, browser, code_execution, skills, memory, todo, ...).
  - `--ignore-rules` skips AGENTS.md / SOUL.md auto-injection so our prompt
    is the sole source of behaviour.
  - The MCP server inherits `VAULT_HARNESS_URL`, `VAULT_MCP_REFS`, and
    `VAULT_MCP_LOG` from the hermes parent process — these vary per task.
"""

from __future__ import annotations

import json
import os
import re
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
    message: str = Field(..., description="Answer or summary for the task")
    outcome: str = Field(
        "OUTCOME_OK",
        description=(
            "One of OUTCOME_OK, OUTCOME_DENIED_SECURITY, OUTCOME_NONE_CLARIFICATION, "
            "OUTCOME_NONE_UNSUPPORTED, OUTCOME_ERR_INTERNAL."
        ),
    )
    grounding_refs: list[str] = Field(default_factory=list)
    completed_steps: list[str] = Field(default_factory=list)


@dataclass
class AgentMetrics:
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

HERMES_TIMEOUT_SEC = int(os.environ.get("HERMES_TIMEOUT_SEC", "900"))
GROUNDING_REFS = os.environ.get("GROUNDING_REFS", "1") == "1"
AUTO_DISCOVERY = os.environ.get("AUTO_DISCOVERY", "1") == "1"
MCP_SERVER_NAME = os.environ.get("MCP_SERVER_NAME", "bitgn-ecom")
def _resolve_hermes_bin() -> str:
    explicit = os.environ.get("HERMES_BIN", "").strip()
    if explicit:
        return explicit
    # Prefer the hermes shipped next to the running Python (venv bin), not the
    # one next to the resolved interpreter (which on macOS jumps to the system
    # framework and won't have hermes installed).
    venv_hermes = Path(sys.executable).with_name("hermes")
    if venv_hermes.exists():
        return str(venv_hermes)
    import shutil
    found = shutil.which("hermes")
    return found or "hermes"


HERMES_BIN = _resolve_hermes_bin()
HERMES_PROVIDER = os.environ.get("HERMES_PROVIDER", "openrouter")
HERMES_MAX_TURNS = os.environ.get("HERMES_MAX_TURNS", "90")
# Optional safety net (carried over from 011): parse "except X" phrases in the
# task and strip matching paths from OK refs. Off by default.
CODEX_STRIP_EXCLUSIONS = os.environ.get("CODEX_STRIP_EXCLUSIONS", "0") == "1"

# Resolve the local HERMES_HOME bundled with this experiment.  We always pass
# this explicitly so that hermes never falls back to ~/.hermes (which would
# inherit unrelated MCP servers, skills, AGENTS.md, etc.).
_HERE = Path(__file__).resolve().parent
HERMES_HOME = os.environ.get("HERMES_HOME", str(_HERE / "hermes_home"))


# ── Bootstrap (unchanged from 011) ───────────────────────────────────────


def _bootstrap(
    vm: EcomRuntimeClientSync,
    debug_logger: JsonlDebugLogger | None,
    task_id: str | None,
    agent_run_id: str,
) -> str:
    parts: list[str] = []

    steps = [
        ("tree", lambda: vm.tree(TreeRequest(root="/", level=2)), {"root": "/", "level": 2}),
        ("tree_docs", lambda: vm.tree(TreeRequest(root="/docs", level=4)), {"root": "/docs", "level": 4}),
        ("read", lambda: vm.read(ReadRequest(path="/AGENTS.MD")), {"path": "/AGENTS.MD"}),
        ("exec_date", lambda: vm.exec(ExecRequest(path="/bin/date")), {"path": "/bin/date"}),
        ("exec_id", lambda: vm.exec(ExecRequest(path="/bin/id")), {"path": "/bin/id"}),
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
        elif name == "tree_docs":
            formatted = format_tree(result, root="/docs", level=4)
        elif name == "read":
            formatted = format_read(result, path="/AGENTS.MD")
        elif name == "exec_date":
            formatted = format_exec(result, path="/bin/date")
        elif name == "exec_id":
            formatted = format_exec(result, path="/bin/id")
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


_HERMES_JSON_TAIL = (
    "## OUTPUT FORMAT\n\n"
    "After completing all required MCP tool calls, return your final answer as a "
    "single JSON object — and nothing else — matching this schema:\n\n"
    "```\n"
    "{\n"
    '  "message": "<answer or summary for the task>",\n'
    '  "outcome": "<one of: OUTCOME_OK, OUTCOME_DENIED_SECURITY, '
    'OUTCOME_NONE_CLARIFICATION, OUTCOME_NONE_UNSUPPORTED, OUTCOME_ERR_INTERNAL>",\n'
    '  "grounding_refs": ["<absolute workspace path>", ...],\n'
    '  "completed_steps": ["<short step>", ...]\n'
    "}\n"
    "```\n\n"
    "Output ONLY the JSON object as your final reply. No prose, no code fences, "
    "no trailing comments. If you wrap it in ```json fences they will be stripped."
)


def _build_full_prompt(*, bootstrap_output: str, task_text: str, hint: str) -> str:
    sections: list[str] = [CODEX_PREAMBLE.rstrip(), INSTRUCTIONS.rstrip()]

    if hint.strip():
        sections.append("## Hint (from env)\n\n" + hint.strip())

    if bootstrap_output.strip():
        sections.append(
            "<bootstrap-output>\n" + bootstrap_output.rstrip() + "\n</bootstrap-output>"
        )

    sections.append("<task-system-prompt>\n" + task_text.rstrip() + "\n</task-system-prompt>")
    sections.append("## TASK\n" + task_text.rstrip())
    sections.append(_HERMES_JSON_TAIL)
    return "\n\n".join(sections)


# ── Output extraction (last balanced {...}) ──────────────────────────────


def _strip_code_fence(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = s[3:]
        if s.startswith(("json", "JSON")):
            s = s[4:]
        s = s.lstrip("\n")
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def _extract_task_result_json(text: str) -> str | None:
    """Return the last top-level balanced ``{...}`` block, or None.

    Hermes -z prints the model's final reply verbatim — if the model wraps the
    JSON in prose or fences, this scans backwards for the last balanced object.
    """
    cleaned = _strip_code_fence(text)
    # Fast-path: the response is already a JSON object.
    if cleaned.startswith("{") and cleaned.endswith("}"):
        return cleaned

    # Scan for the last balanced {...} ignoring braces inside strings.
    last_close = cleaned.rfind("}")
    while last_close != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(last_close, -1, -1):
            ch = cleaned[i]
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"' and not esc:
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "}":
                depth += 1
            elif ch == "{":
                depth -= 1
                if depth == 0:
                    return cleaned[i : last_close + 1]
        last_close = cleaned.rfind("}", 0, last_close)
    return None


# ── MCP log telemetry ────────────────────────────────────────────────────


def _count_mcp_calls(log_path: str, byte_offset: int) -> int:
    """Count tool-call lines appended to the MCP log since ``byte_offset``."""
    try:
        with open(log_path, "rb") as f:
            f.seek(byte_offset)
            buf = f.read()
    except OSError:
        return 0
    # Each ecom_mcp_server tool invocation emits one call line of the form
    # ``[ecom-mcp HH:MM:SS] ecom_<name>(...)`` and one result line
    # ``[ecom-mcp HH:MM:SS]   -> ...``.  Count the call lines only.
    return sum(1 for line in buf.splitlines() if b"] ecom_" in line)


# ── Server-side refs (unchanged from 011) ────────────────────────────────


def _read_server_refs(refs_path: str) -> list[str]:
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


# ── Hermes argv ──────────────────────────────────────────────────────────


def _build_hermes_cmd(*, model: str, full_prompt: str) -> list[str]:
    """Assemble argv for ``hermes -z``.

    `-z PROMPT` is one-shot mode: hermes prints only the final assistant
    reply to stdout (no banner, no spinner, no tool previews).  We pass
    `--ignore-rules` so AGENTS.md / SOUL.md / .cursorrules / memory are NOT
    auto-injected — the prompt we build is the sole source of behaviour.

    `--yolo` auto-approves any tool calls (oneshot mode would hang on
    approvals otherwise).  The isolated config.yaml under HERMES_HOME only
    exposes the bitgn-ecom MCP server, so "yolo" here just means "don't
    block on approvals for the safe MCP we vetted".
    """
    return [
        HERMES_BIN,
        "-z",
        full_prompt,
        "--model",
        model,
        "--provider",
        HERMES_PROVIDER,
        # Explicit -t so hermes wires the MCP server tools into the LLM
        # toolbox.  Without it, the -z oneshot path falls through to config
        # defaults and the model gets zero tools — observed in the first
        # smoke (0 MCP calls, empty stub JSON).
        "-t",
        MCP_SERVER_NAME,
        "--ignore-rules",
        "--yolo",
    ]


# ── Refs sanitisation (unchanged from 011) ───────────────────────────────


_ATTACK_TARGET_PREFIXES = (
    "/proc/baskets/",
    "/proc/payments/",
    "/proc/returns/",
)
_ATTACK_TARGET_REGEX = re.compile(r"^/proc/customers/cust_")
_POLICY_DOCS = ("/docs/security.md",)

_TOPIC_POLICY_DOCS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b(?:discount|refund|price\s+adjustment|service[\s_-]+recovery|goodwill|markdown)\b",
            re.IGNORECASE,
        ),
        "/docs/discounts.md",
    ),
    (
        re.compile(
            r"\b(?:3ds|3-?d[\s-]*secure|payment\s+recovery|3ds\s+challenge|card\s+security)\b",
            re.IGNORECASE,
        ),
        "/docs/payments/3ds.md",
    ),
)


def _sanitize_refs_for_denied(refs: list[str], task_text: str = "") -> list[str]:
    keep = [
        r
        for r in refs
        if not r.startswith(_ATTACK_TARGET_PREFIXES)
        and not _ATTACK_TARGET_REGEX.match(r)
    ]
    for doc in _POLICY_DOCS:
        if doc not in keep:
            keep.append(doc)
    for pattern, doc in _TOPIC_POLICY_DOCS:
        if pattern.search(task_text or "") and doc not in keep:
            keep.append(doc)
    return sorted(set(keep))


_EXCLUSION_RE = re.compile(
    r"\b(?:except|excluding|without|but not)\s+(?:the\s+)?"
    r"([\w][\w' /-]{1,80}?)(?=[)\].,;:!?]|\s+(?:and|or|but)\b|$)",
    re.IGNORECASE,
)


def _extract_exclusion_phrases(task_text: str) -> list[str]:
    out: list[str] = []
    for m in _EXCLUSION_RE.finditer(task_text or ""):
        phrase = m.group(1).strip().lower()
        if 2 <= len(phrase) <= 60:
            out.append(phrase)
    return out


def _ref_matches_exclusion(ref: str, phrases: list[str]) -> bool:
    low = ref.lower().replace("/", " ").replace("_", " ")
    if low.endswith(".json"):
        low = low[:-5]
    return any(p.replace("_", " ") in low for p in phrases)


def _sanitize_refs_for_exclusions(refs: list[str], task_text: str) -> tuple[list[str], list[str]]:
    phrases = _extract_exclusion_phrases(task_text)
    if not phrases:
        return list(refs), []
    kept: list[str] = []
    dropped: list[str] = []
    for r in refs:
        if _ref_matches_exclusion(r, phrases):
            dropped.append(r)
        else:
            kept.append(r)
    return kept, dropped


# ── Answer submission ────────────────────────────────────────────────────


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


def run_hermes_agent(
    model: str,
    harness_url: str,
    task_text: str,
    task_id: str | None = None,
    debug_logger: JsonlDebugLogger | None = None,
) -> AgentMetrics:
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
            provider=HERMES_PROVIDER,
            hermes_home=HERMES_HOME,
            hint_present=bool(hint),
        )

    # 1. Bootstrap (unchanged: tree, /docs tree, AGENTS.MD, /bin/date, /bin/id)
    bootstrap_output = _bootstrap(vm, debug_logger, task_id, agent_run_id) if AUTO_DISCOVERY else ""

    # 2. Prompt
    full_prompt = _build_full_prompt(
        bootstrap_output=bootstrap_output, task_text=task_text, hint=hint
    )

    # 3. Per-task temp files
    log_path = str(_HERE / "ecom_mcp.log")
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump([], f)
        refs_path = f.name

    # Track MCP-log byte offset BEFORE the run so we can count tool calls
    # for this task only (the log is appended-to across tasks).
    try:
        mcp_log_start_offset = os.path.getsize(log_path) if os.path.exists(log_path) else 0
    except OSError:
        mcp_log_start_offset = 0

    cmd = _build_hermes_cmd(model=model, full_prompt=full_prompt)

    # Build the subprocess env: copy ours, add per-task MCP env vars, and
    # pin HERMES_HOME to the isolated config we ship.
    sub_env = os.environ.copy()
    sub_env["HERMES_HOME"] = HERMES_HOME
    sub_env["HERMES_INFERENCE_MODEL"] = model
    sub_env["HERMES_INFERENCE_PROVIDER"] = HERMES_PROVIDER
    sub_env["HERMES_MAX_TURNS"] = HERMES_MAX_TURNS
    sub_env["HERMES_YOLO_MODE"] = "1"
    sub_env["HERMES_ACCEPT_HOOKS"] = "1"
    sub_env["VAULT_HARNESS_URL"] = harness_url
    sub_env["VAULT_MCP_REFS"] = refs_path
    sub_env["VAULT_MCP_LOG"] = log_path

    if debug_logger:
        debug_logger.log(
            "hermes_prompt",
            task_id=task_id,
            agent_run_id=agent_run_id,
            prompt_chars=len(full_prompt),
            prompt=full_prompt,
            cmd=cmd[:2] + ["<full_prompt>"] + cmd[3:],
        )

    print(f"\n{CLI_CYAN}Running hermes -z ({model} via {HERMES_PROVIDER})…{CLI_CLR}")

    # 4. Run Hermes
    response_text = ""
    parse_error: str | None = None

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=HERMES_TIMEOUT_SEC,
            stdin=subprocess.DEVNULL,
            env=sub_env,
        )
    except subprocess.TimeoutExpired:
        msg = f"hermes -z timed out after {HERMES_TIMEOUT_SEC}s"
        print(f"{CLI_RED}{msg}{CLI_CLR}")
        if debug_logger:
            debug_logger.log("hermes_timeout", task_id=task_id, agent_run_id=agent_run_id)
        _submit_error(vm, msg)
        metrics.finalize()
        if debug_logger:
            debug_logger.log("agent_metrics", task_id=task_id, agent_run_id=agent_run_id, **metrics.to_dict())
        return metrics
    except FileNotFoundError:
        msg = f"{HERMES_BIN} CLI not found on PATH — pip-install hermes-agent first"
        print(f"{CLI_RED}{msg}{CLI_CLR}")
        if debug_logger:
            debug_logger.log("hermes_not_found", task_id=task_id, agent_run_id=agent_run_id)
        _submit_error(vm, msg)
        metrics.finalize()
        if debug_logger:
            debug_logger.log("agent_metrics", task_id=task_id, agent_run_id=agent_run_id, **metrics.to_dict())
        return metrics

    response_text = (result.stdout or "").strip()

    if debug_logger:
        debug_logger.log(
            "hermes_finished",
            task_id=task_id,
            agent_run_id=agent_run_id,
            returncode=result.returncode,
            stdout_chars=len(result.stdout or ""),
            stderr_chars=len(result.stderr or ""),
            stdout=(result.stdout or "")[:6000],
            stderr=(result.stderr or "")[:2000],
        )

    if result.returncode != 0 and not response_text:
        msg = f"hermes -z failed (rc={result.returncode}): {(result.stderr or '')[:500]}"
        print(f"{CLI_RED}{msg}{CLI_CLR}")
        _submit_error(vm, msg)
        metrics.finalize()
        if debug_logger:
            debug_logger.log("agent_metrics", task_id=task_id, agent_run_id=agent_run_id, **metrics.to_dict())
        return metrics

    # 5. Tool-call telemetry from the MCP log (hermes -z swallows everything else).
    metrics.tool_calls = _count_mcp_calls(log_path, mcp_log_start_offset)

    # 6. Extract JSON from response_text
    if not response_text:
        parse_error = "empty response from hermes -z"

    task_result: TaskResult | None = None
    if not parse_error:
        json_text = _extract_task_result_json(response_text)
        if json_text is None:
            parse_error = "no JSON object found in hermes -z output"
        else:
            try:
                task_result = TaskResult.model_validate_json(json_text)
            except ValidationError as exc:
                parse_error = f"TaskResult schema mismatch: {exc.errors()[:3]}"
                if debug_logger:
                    debug_logger.log(
                        "hermes_schema_error",
                        task_id=task_id,
                        agent_run_id=agent_run_id,
                        error=str(exc),
                        response_text=response_text[:6000],
                        extracted_json=json_text[:4000],
                    )

    # 6b. JSON-fallback retry: hermes -z occasionally narrates instead of
    # responding with the schema. Re-ask once with the prior reply included
    # plus a stern "JSON only" instruction. Closes the CLI parsing hole that
    # cost us t32 in 015 (OUTCOME_ERR_INTERNAL).
    if task_result is None and response_text:
        retry_prompt = (
            "Your previous reply did not contain the required JSON object.\n\n"
            "Previous reply (verbatim):\n"
            "<<<\n" + response_text[:8000] + "\n>>>\n\n"
            "RESPOND NOW with ONLY a single JSON object matching this schema, "
            "nothing else. No prose. No code fences. Use your previous "
            "conclusions to fill the fields:\n\n"
            "{\"message\": <str>, "
            "\"outcome\": "
            "\"OUTCOME_OK|OUTCOME_DENIED_SECURITY|OUTCOME_NONE_CLARIFICATION|"
            "OUTCOME_NONE_UNSUPPORTED|OUTCOME_ERR_INTERNAL\", "
            "\"grounding_refs\": [<str>, ...], "
            "\"completed_steps\": [<str>, ...]}"
        )
        retry_cmd = [
            HERMES_BIN, "-z", retry_prompt,
            "--model", model, "--provider", HERMES_PROVIDER,
            "--ignore-rules", "--yolo",
        ]
        if debug_logger:
            debug_logger.log(
                "hermes_json_retry_started",
                task_id=task_id,
                agent_run_id=agent_run_id,
                first_response_chars=len(response_text),
            )
        try:
            retry_result = subprocess.run(
                retry_cmd,
                capture_output=True,
                text=True,
                timeout=min(HERMES_TIMEOUT_SEC, 180),
                stdin=subprocess.DEVNULL,
                env=sub_env,
            )
            retry_text = (retry_result.stdout or "").strip()
            if debug_logger:
                debug_logger.log(
                    "hermes_json_retry_finished",
                    task_id=task_id,
                    agent_run_id=agent_run_id,
                    returncode=retry_result.returncode,
                    stdout_chars=len(retry_text),
                    stdout=retry_text[:6000],
                )
            if retry_text:
                json_text = _extract_task_result_json(retry_text)
                if json_text:
                    try:
                        task_result = TaskResult.model_validate_json(json_text)
                        parse_error = None
                    except ValidationError as exc:
                        parse_error = f"retry: TaskResult schema mismatch: {exc.errors()[:3]}"
        except subprocess.TimeoutExpired:
            if debug_logger:
                debug_logger.log(
                    "hermes_json_retry_timeout",
                    task_id=task_id,
                    agent_run_id=agent_run_id,
                )
        except Exception as exc:
            if debug_logger:
                debug_logger.log(
                    "hermes_json_retry_error",
                    task_id=task_id,
                    agent_run_id=agent_run_id,
                    error=str(exc),
                )

    if parse_error or task_result is None:
        msg = parse_error or "empty response from hermes -z"
        print(f"{CLI_RED}{msg}{CLI_CLR}")
        _submit_error(vm, msg)
        metrics.finalize()
        if debug_logger:
            debug_logger.log("agent_metrics", task_id=task_id, agent_run_id=agent_run_id, **metrics.to_dict())
        return metrics

    if task_result.outcome not in _VALID_OUTCOMES:
        print(f"{CLI_YELLOW}unknown outcome {task_result.outcome!r}, coercing to ERR_INTERNAL{CLI_CLR}")
        task_result.outcome = "OUTCOME_ERR_INTERNAL"

    # 7. Override grounding_refs with MCP-server-tracked set if enabled
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

    # 8. Sanitise refs per outcome (DENIED: strip attack targets + add policy
    # docs; OK: optional "except X" stripper).
    if task_result.outcome == "OUTCOME_DENIED_SECURITY":
        pre = list(task_result.grounding_refs)
        task_result.grounding_refs = _sanitize_refs_for_denied(
            task_result.grounding_refs, task_text=task_text
        )
        if debug_logger and pre != task_result.grounding_refs:
            dropped = [r for r in pre if r not in task_result.grounding_refs]
            added = [r for r in task_result.grounding_refs if r not in pre]
            debug_logger.log(
                "refs_sanitized_denied",
                task_id=task_id,
                agent_run_id=agent_run_id,
                dropped=dropped,
                added=added,
            )
    elif task_result.outcome == "OUTCOME_OK" and CODEX_STRIP_EXCLUSIONS:
        kept, dropped = _sanitize_refs_for_exclusions(
            list(task_result.grounding_refs), task_text
        )
        if dropped:
            task_result.grounding_refs = kept
            if debug_logger:
                debug_logger.log(
                    "refs_sanitized_exclusions",
                    task_id=task_id,
                    agent_run_id=agent_run_id,
                    dropped=dropped,
                    exclusion_phrases=_extract_exclusion_phrases(task_text),
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


def run_agent(
    model: str,
    harness_url: str,
    task_text: str,
    task_id: str | None = None,
    debug_logger: JsonlDebugLogger | None = None,
) -> None:
    try:
        run_hermes_agent(
            model=model,
            harness_url=harness_url,
            task_text=task_text,
            task_id=task_id,
            debug_logger=debug_logger,
        )
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # pragma: no cover
        print(f"{CLI_RED}hermes agent crashed: {exc}{CLI_CLR}", file=sys.stderr)
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


_ = (datetime, timezone)
