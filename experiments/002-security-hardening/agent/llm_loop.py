"""LLM-цикл: OpenAI function calling + execute_code.

Порт `agents/src/agent/index.ts` (runAgent) под OpenAI/OpenRouter:
  - tool_calls вместо Anthropic tool_use, role="tool" для результата
  - параллельные tool_calls обрабатываются ВСЕ перед следующим API-вызовом
  - scratchpad пересобирается в system message каждую итерацию
  - nudge-механизм: до 3 попыток × 3 итерации, если ws.answer() не вызван
  - метрики (токены, elapsed) собираются в TaskMetrics

Финал — `Workspace.answer()` поднимает `AnswerSubmitted`, мы ловим и возвращаем.
"""

from __future__ import annotations

import json
import time
from typing import Any

from cost import TaskMetrics
from system_prompt import build_system_prompt
from tool_defs import TOOLS
from workspace import AnswerSubmitted


NUDGE_SUBMIT = (
    "You have not submitted your answer yet. Populate scratchpad[\"answer\"], "
    "scratchpad[\"outcome\"], scratchpad[\"refs\"], then define a verify(sp) "
    "function that checks your gates, and call ws.answer(scratchpad, verify). "
    "If you cannot determine the answer, use OUTCOME_NONE_CLARIFICATION."
)

MAX_NUDGES = 3
NUDGE_ITERATIONS = 3


def _build_system_message(
    *,
    task_text: str,
    workspace_tree: str,
    bootstrap_output: str,
    hint: str,
    scratchpad: dict,
    iterations_used: int,
    max_iterations: int,
) -> dict:
    content = build_system_prompt(
        task_text=task_text,
        workspace_tree=workspace_tree,
        bootstrap_output=bootstrap_output,
        hint=hint,
        scratchpad=scratchpad,
        iterations_used=iterations_used,
        max_iterations=max_iterations,
    )
    return {"role": "system", "content": content}


def _assistant_msg_from_response(msg) -> dict:
    """Преобразовать OpenAI response message в формат, пригодный для messages-истории."""
    out: dict[str, Any] = {"role": "assistant"}
    if getattr(msg, "content", None):
        out["content"] = msg.content
    else:
        out["content"] = None
    tool_calls = getattr(msg, "tool_calls", None) or []
    if tool_calls:
        serialized = []
        for tc in tool_calls:
            serialized.append(
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
            )
        out["tool_calls"] = serialized
    return out


def run_llm_loop(
    *,
    client,
    model: str,
    ws,
    scratchpad: dict,
    executor,
    task_text: str,
    workspace_tree: str,
    bootstrap_output: str,
    hint: str = "",
    max_iterations: int = 20,
    max_tokens: int = 16384,
    debug_logger=None,
    task_id: str | None = None,
    agent_run_id: str | None = None,
) -> tuple[dict | None, TaskMetrics]:
    """Главный цикл. Возвращает (answer_dict_or_None, metrics)."""
    metrics = TaskMetrics()
    iterations = 0

    messages: list[dict] = [
        {
            "role": "user",
            "content": (
                "Begin. Follow the call-1 discipline from the system prompt: load everything "
                "needed in one execute_code call (reads + searches), then in call 2 make the "
                "decision, perform writes/deletes if authorized, populate scratchpad with gates, "
                "define verify(sp), and call ws.answer(scratchpad, verify)."
            ),
        }
    ]

    nudge_attempts = 0
    pending_iter_budget = max_iterations

    try:
        while pending_iter_budget > 0:
            for _ in range(pending_iter_budget):
                system_msg = _build_system_message(
                    task_text=task_text,
                    workspace_tree=workspace_tree,
                    bootstrap_output=bootstrap_output,
                    hint=hint,
                    scratchpad=scratchpad,
                    iterations_used=iterations,
                    max_iterations=max_iterations,
                )

                step = f"step_{iterations + 1}"
                api_started = time.time()
                try:
                    resp = client.chat.completions.create(
                        model=model,
                        messages=[system_msg, *messages],
                        tools=TOOLS,
                        tool_choice="auto",
                        max_completion_tokens=max_tokens,
                    )
                except Exception as exc:
                    if debug_logger:
                        debug_logger.log(
                            "llm_error",
                            task_id=task_id,
                            agent_run_id=agent_run_id,
                            step=step,
                            error=str(exc),
                            error_type=exc.__class__.__name__,
                        )
                    raise

                elapsed_ms = int((time.time() - api_started) * 1000)
                metrics.add_response(resp)
                iterations += 1

                choice = resp.choices[0]
                msg = choice.message
                tool_calls = getattr(msg, "tool_calls", None) or []
                finish_reason = getattr(choice, "finish_reason", None)

                if debug_logger:
                    try:
                        raw = resp.model_dump(mode="json")
                    except Exception:
                        raw = {"_unavailable": True}
                    debug_logger.log(
                        "llm_response",
                        task_id=task_id,
                        agent_run_id=agent_run_id,
                        step=step,
                        elapsed_ms=elapsed_ms,
                        finish_reason=finish_reason,
                        tool_calls_count=len(tool_calls),
                        text=getattr(msg, "content", None),
                        raw_response=raw,
                    )

                messages.append(_assistant_msg_from_response(msg))

                if not tool_calls:
                    if debug_logger:
                        debug_logger.log(
                            "text",
                            task_id=task_id,
                            agent_run_id=agent_run_id,
                            step=step,
                            text=getattr(msg, "content", None),
                        )
                    break  # выход в nudge

                for tc in tool_calls:
                    fn_name = tc.function.name
                    arguments_raw = tc.function.arguments or "{}"
                    try:
                        args = json.loads(arguments_raw)
                    except json.JSONDecodeError as exc:
                        err_text = (
                            f"[error] could not parse tool arguments as JSON: {exc}\n"
                            f"raw: {arguments_raw[:1000]}"
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": err_text,
                            }
                        )
                        if debug_logger:
                            debug_logger.log(
                                "tool_error",
                                task_id=task_id,
                                agent_run_id=agent_run_id,
                                step=step,
                                tool=fn_name,
                                error=str(exc),
                                arguments_raw=arguments_raw[:2000],
                            )
                        continue

                    if fn_name != "execute_code":
                        err_text = f"[error] unknown tool: {fn_name}"
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": err_text,
                            }
                        )
                        if debug_logger:
                            debug_logger.log(
                                "tool_error",
                                task_id=task_id,
                                agent_run_id=agent_run_id,
                                step=step,
                                tool=fn_name,
                                error="unknown tool",
                            )
                        continue

                    code = args.get("code", "")
                    exec_started = time.time()
                    try:
                        output_text, is_error = executor.execute(code)
                    except AnswerSubmitted as submitted:
                        exec_ms = int((time.time() - exec_started) * 1000)
                        confirmation = (
                            f"[answer submitted: outcome={submitted.outcome}, "
                            f"refs={len(submitted.refs)}]"
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": confirmation,
                            }
                        )
                        if debug_logger:
                            debug_logger.log(
                                "tool_result",
                                task_id=task_id,
                                agent_run_id=agent_run_id,
                                phase="step",
                                step=step,
                                tool="execute_code",
                                elapsed_ms=exec_ms,
                                code=code,
                                output=confirmation,
                                is_error=False,
                                answer_submitted=True,
                            )
                            debug_logger.log(
                                "scratchpad_snapshot",
                                task_id=task_id,
                                agent_run_id=agent_run_id,
                                step=step,
                                scratchpad=scratchpad,
                            )
                        metrics.finalize()
                        return (
                            {
                                "message": submitted.message,
                                "outcome": submitted.outcome,
                                "refs": submitted.refs,
                            },
                            metrics,
                        )

                    exec_ms = int((time.time() - exec_started) * 1000)

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": output_text or "ok",
                        }
                    )

                    if debug_logger:
                        debug_logger.log(
                            "tool_result",
                            task_id=task_id,
                            agent_run_id=agent_run_id,
                            phase="step",
                            step=step,
                            tool="execute_code",
                            elapsed_ms=exec_ms,
                            code=code,
                            output=output_text,
                            is_error=is_error,
                            answer_submitted=False,
                        )
                        debug_logger.log(
                            "scratchpad_snapshot",
                            task_id=task_id,
                            agent_run_id=agent_run_id,
                            step=step,
                            scratchpad=scratchpad,
                        )

                if iterations >= max_iterations + nudge_attempts * NUDGE_ITERATIONS:
                    break

            # цикл итераций закончился без сабмита — пробуем nudge
            if nudge_attempts >= MAX_NUDGES:
                break
            nudge_attempts += 1
            messages.append({"role": "user", "content": NUDGE_SUBMIT})
            if debug_logger:
                debug_logger.log(
                    "nudge",
                    task_id=task_id,
                    agent_run_id=agent_run_id,
                    attempt=nudge_attempts,
                    iterations_used=iterations,
                )
            pending_iter_budget = NUDGE_ITERATIONS
    finally:
        metrics.finalize()

    return None, metrics
