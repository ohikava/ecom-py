"""run_agent — точка входа, дёргаемая из main.py для каждого trial.

Создаёт OpenAI-клиент, ECOM runtime client, выполняет bootstrap (tree /, read
/AGENTS.MD, exec /bin/date, exec /bin/id), кладёт результаты в system prompt
как <bootstrap-output>, инициализирует scratchpad, передаёт управление в
run_llm_loop. На любую необработанную ошибку — fallback OUTCOME_ERR_INTERNAL.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

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
from openai import OpenAI

from code_executor import CodeExecutor
from debug_logger import JsonlDebugLogger
from env_loader import load_dotenv
from formatters import format_exec, format_read, format_tree
from http_sync_client import HttpxSyncClient
from llm_loop import run_llm_loop
from workspace import Workspace


# .env лежит в корне репозитория; main.py выполняется из experiments/001-pangolin-port/agent/
_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(str(_ENV_PATH))


CLI_RED = "\x1B[31m"
CLI_GREEN = "\x1B[32m"
CLI_YELLOW = "\x1B[33m"
CLI_BLUE = "\x1B[34m"
CLI_CLR = "\x1B[0m"


def _bootstrap(vm: EcomRuntimeClientSync, debug_logger, task_id, agent_run_id) -> tuple[str, str]:
    """Сделать 4 bootstrap-вызова, вернуть (workspace_tree_text, bootstrap_output_text)."""
    workspace_tree_text = ""
    bootstrap_parts: list[str] = []

    bootstrap_steps = [
        ("tree", lambda: vm.tree(TreeRequest(root="/", level=2)), {"root": "/", "level": 2}),
        ("read", lambda: vm.read(ReadRequest(path="/AGENTS.MD")), {"path": "/AGENTS.MD"}),
        ("exec_date", lambda: vm.exec(ExecRequest(path="/bin/date")), {"path": "/bin/date"}),
        ("exec_id", lambda: vm.exec(ExecRequest(path="/bin/id")), {"path": "/bin/id"}),
    ]

    for step_name, fn, args in bootstrap_steps:
        try:
            result = fn()
        except ConnectError as exc:
            err_text = f"[bootstrap {step_name} failed: {exc.code}: {exc.message}]"
            print(f"{CLI_YELLOW}BOOTSTRAP {step_name}: {exc.message}{CLI_CLR}")
            bootstrap_parts.append(err_text)
            if debug_logger:
                debug_logger.log(
                    "tool_result",
                    task_id=task_id,
                    agent_run_id=agent_run_id,
                    phase="bootstrap",
                    step=step_name,
                    args=args,
                    is_error=True,
                    error=str(exc.message),
                    error_code=str(exc.code),
                )
            continue

        if step_name == "tree":
            formatted = format_tree(result, root="/", level=2)
            workspace_tree_text = formatted
        elif step_name == "read":
            formatted = format_read(result, path="/AGENTS.MD")
            bootstrap_parts.append(formatted)
        elif step_name == "exec_date":
            formatted = format_exec(result, path="/bin/date")
            bootstrap_parts.append(formatted)
        elif step_name == "exec_id":
            formatted = format_exec(result, path="/bin/id")
            bootstrap_parts.append(formatted)
        else:
            formatted = ""

        print(f"{CLI_GREEN}BOOTSTRAP {step_name}{CLI_CLR}:\n{formatted}\n")
        if debug_logger:
            debug_logger.log(
                "tool_result",
                task_id=task_id,
                agent_run_id=agent_run_id,
                phase="bootstrap",
                step=step_name,
                args=args,
                is_error=False,
                formatted_result=formatted,
            )

    return workspace_tree_text, "\n\n".join(bootstrap_parts)


def _seed_scratchpad(vm: EcomRuntimeClientSync) -> dict:
    """Инициализировать scratchpad с серверным временем (или локальным как fallback)."""
    try:
        ctx = vm.context(ContextRequest())
        context_dict = {"unix_time": int(ctx.unix_time), "time": ctx.time}
    except Exception:
        now = datetime.now(timezone.utc)
        context_dict = {
            "unix_time": int(now.timestamp()),
            "time": now.isoformat().replace("+00:00", "Z"),
        }
    return {"refs": [], "context": context_dict}


def _fallback_answer(vm: EcomRuntimeClientSync, outcome: Outcome, message: str) -> None:
    try:
        vm.answer(AnswerRequest(message=message, outcome=outcome, refs=[]))
    except Exception as exc:
        print(f"{CLI_RED}fallback answer failed: {exc}{CLI_CLR}")


def run_agent(
    model: str,
    harness_url: str,
    task_text: str,
    task_id: str | None = None,
    debug_logger: JsonlDebugLogger | None = None,
) -> None:
    """Контракт от main.py: один trial → один вызов."""
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    if not openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY is not set")

    hint = os.environ.get("HINT", "")
    agent_run_id = f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-{int(time.time() * 1000)}"

    client = OpenAI(api_key=openrouter_api_key, base_url="https://openrouter.ai/api/v1")
    vm = EcomRuntimeClientSync(harness_url, http_client=HttpxSyncClient())

    if debug_logger:
        debug_logger.log(
            "agent_started",
            task_id=task_id,
            agent_run_id=agent_run_id,
            model=model,
            harness_url=harness_url,
            task_text=task_text,
            hint_present=bool(hint),
        )

    workspace_tree_text, bootstrap_output = _bootstrap(
        vm, debug_logger, task_id, agent_run_id
    )

    scratchpad = _seed_scratchpad(vm)
    tracker = {"read_paths": [], "write_paths": [], "delete_paths": []}
    ws = Workspace(vm, scratchpad, tracker=tracker)
    executor = CodeExecutor(ws, scratchpad)

    try:
        answer, metrics = run_llm_loop(
            client=client,
            model=model,
            ws=ws,
            scratchpad=scratchpad,
            executor=executor,
            task_text=task_text,
            workspace_tree=workspace_tree_text,
            bootstrap_output=bootstrap_output,
            hint=hint,
            max_iterations=20,
            max_tokens=16384,
            debug_logger=debug_logger,
            task_id=task_id,
            agent_run_id=agent_run_id,
        )
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        print(f"{CLI_RED}agent crashed: {exc}{CLI_CLR}")
        if debug_logger:
            debug_logger.log(
                "agent_crashed",
                task_id=task_id,
                agent_run_id=agent_run_id,
                error=str(exc),
                error_type=exc.__class__.__name__,
            )
        _fallback_answer(
            vm,
            Outcome.OUTCOME_ERR_INTERNAL,
            f"agent crashed: {exc.__class__.__name__}: {exc}",
        )
        return

    if answer is None:
        print(f"{CLI_YELLOW}agent did not submit answer; sending fallback{CLI_CLR}")
        _fallback_answer(
            vm,
            Outcome.OUTCOME_ERR_INTERNAL,
            "agent did not submit an answer within the iteration budget",
        )
        if debug_logger:
            debug_logger.log(
                "agent_completed",
                task_id=task_id,
                agent_run_id=agent_run_id,
                outcome="OUTCOME_ERR_INTERNAL",
                message="agent did not submit (fallback)",
                refs=[],
                fallback=True,
            )
            debug_logger.log(
                "agent_metrics",
                task_id=task_id,
                agent_run_id=agent_run_id,
                **metrics.to_dict(),
            )
        return

    status_color = CLI_GREEN if answer["outcome"] == "OUTCOME_OK" else CLI_YELLOW
    print(f"{status_color}agent {answer['outcome']}{CLI_CLR}")
    print(f"{CLI_BLUE}AGENT SUMMARY: {answer['message']}{CLI_CLR}")
    for ref in answer.get("refs", []):
        print(f"- {CLI_BLUE}{ref}{CLI_CLR}")

    if debug_logger:
        debug_logger.log(
            "agent_completed",
            task_id=task_id,
            agent_run_id=agent_run_id,
            outcome=answer["outcome"],
            message=answer["message"],
            refs=answer.get("refs", []),
            fallback=False,
        )
        debug_logger.log(
            "agent_metrics",
            task_id=task_id,
            agent_run_id=agent_run_id,
            **metrics.to_dict(),
        )
