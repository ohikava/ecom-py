"""Benchmark runner for experiment 009-probing-silent.

Port of 005/006 main.py with one scaffolding addition: optional parallel trial
processing through ThreadPoolExecutor (env WORKERS). Defaults to WORKERS=1
(sequential, byte-identical behaviour to prior runs). With WORKERS>1 trials run
concurrently; each task has its own BitGN VM (harness_url), its own codex exec
subprocess, and its own MCP-server child — there is no shared workspace state
between concurrent trials. The only shared resources are the ECOM MCP log
file (appended-to, line-buffered) and the JSONL debug log (uses a per-call
write+flush so interleaving stays line-atomic).
"""

import os
import sys
import textwrap
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from env_loader import load_dotenv
from debug_logger import JsonlDebugLogger

# .env lives at the repo root; agent/ is 3 levels below it.
_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(str(_ENV_PATH))

from bitgn.harness_connect import HarnessServiceClientSync
from bitgn.harness_pb2 import (
    EndTrialRequest,
    EvalPolicy,
    GetBenchmarkRequest,
    StartRunRequest,
    StartTrialRequest,
    StatusRequest,
    SubmitRunRequest,
)
from connectrpc.errors import ConnectError

from codex_agent import run_agent
from http_sync_client import HttpxSyncClient


CLI_RED = "\x1B[31m"
CLI_GREEN = "\x1B[32m"
CLI_CLR = "\x1B[0m"
CLI_BLUE = "\x1B[34m"


# Lock for terminal output ordering only — does NOT serialize trial work.
_print_lock = threading.Lock()


def _tprint(tid: str, msg: str) -> None:
    """Thread-safe print with [task_id] prefix; used in parallel mode."""
    with _print_lock:
        for line in msg.splitlines() or [""]:
            print(f"[{tid}] {line}")


def _process_trial(
    client: HarnessServiceClientSync,
    trial_id: str,
    model_id: str,
    debug_logger: JsonlDebugLogger,
    task_filter: list[str],
    parallel: bool,
) -> tuple[str, float | None, list[str]]:
    """Start trial → run agent → end trial. Returns (task_id, score, detail).

    score is None when no score is available or trial was filtered out.
    detail is the harness's score_detail list (empty when score unavailable).
    """
    trial = client.start_trial(StartTrialRequest(trial_id=trial_id))

    if task_filter and trial.task_id not in task_filter:
        # Skip filtered trial without ending it — matches prior single-thread
        # behaviour where filtered trials are left dangling and `submit_run
        # force=True` finalises them.
        return (trial.task_id, None, [])

    header = (
        f"{'=' * 30} Starting task: {trial.task_id} {'=' * 30}\n"
        f"{CLI_BLUE}{trial.instruction}{CLI_CLR}\n{'-' * 80}"
    )
    if parallel:
        _tprint(trial.task_id, header)
    else:
        print(header)

    debug_logger.log(
        "trial_started",
        task_id=trial.task_id,
        trial_id=trial.trial_id,
        harness_url=trial.harness_url,
        instruction=trial.instruction,
    )

    try:
        run_agent(
            model_id,
            trial.harness_url,
            trial.instruction,
            task_id=trial.task_id,
            debug_logger=debug_logger,
        )
    except Exception as exc:
        if parallel:
            _tprint(trial.task_id, f"crashed: {exc}")
        else:
            print(exc)
        debug_logger.log(
            "trial_failed",
            task_id=trial.task_id,
            trial_id=trial.trial_id,
            error=str(exc),
        )

    result = client.end_trial(EndTrialRequest(trial_id=trial.trial_id))
    score = result.score if result.score_available else None
    detail = list(result.score_detail)

    debug_logger.log(
        "trial_finished",
        task_id=trial.task_id,
        trial_id=trial.trial_id,
        score_available=result.score_available,
        score=score,
        score_detail=detail,
    )

    if score is not None:
        style = CLI_GREEN if score == 1 else CLI_RED
        body = f"\n{style}Score: {score:0.2f}\n{textwrap.indent(chr(10).join(detail), '  ')}\n{CLI_CLR}"
    else:
        body = f"\n{CLI_BLUE}Score: not available{CLI_CLR}\n"
    if parallel:
        _tprint(trial.task_id, body)
    else:
        print(body)

    return (trial.task_id, score, detail)


def main() -> None:
    bitgn_url = (
        os.getenv("BITGN_HOST")
        or os.getenv("BENCHMARK_HOST")
        or "https://api.bitgn.com"
    )
    bitgn_api_key = os.getenv("BITGN_API_KEY") or ""
    bench_id = os.getenv("BENCH_ID") or os.getenv("BENCHMARK_ID") or "bitgn/ecom1-dev"
    model_id = os.getenv("MODEL_ID") or "gpt-5.4"
    workers = max(1, int(os.getenv("WORKERS", "1")))
    parallel = workers > 1

    task_filter = sys.argv[1:]
    scores: list[tuple[str, float]] = []
    scores_lock = threading.Lock()
    debug_logger = JsonlDebugLogger()
    debug_logger.log(
        "run_started",
        benchmark_id=bench_id,
        model_id=model_id,
        task_filter=task_filter,
        workers=workers,
    )
    print(f"Debug logs: {debug_logger.path.name}  (workers={workers})")

    try:
        client = HarnessServiceClientSync(bitgn_url, http_client=HttpxSyncClient())
        print("Connecting to BitGN", client.status(StatusRequest()))
        res = client.get_benchmark(GetBenchmarkRequest(benchmark_id=bench_id))
        print(
            f"{EvalPolicy.Name(res.policy)} benchmark: {res.benchmark_id} "
            f"with {len(res.tasks)} tasks.\n{CLI_GREEN}{res.description}{CLI_CLR}"
        )

        run = client.start_run(
            StartRunRequest(
                name="ECOM Codex MCP Port",
                benchmark_id=bench_id,
                api_key=bitgn_api_key,
            )
        )

        try:
            if parallel:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [
                        pool.submit(
                            _process_trial,
                            client,
                            tid,
                            model_id,
                            debug_logger,
                            task_filter,
                            True,
                        )
                        for tid in run.trial_ids
                    ]
                    for fut in as_completed(futures):
                        task_id, score, _ = fut.result()
                        if score is not None:
                            with scores_lock:
                                scores.append((task_id, score))
            else:
                for trial_id in run.trial_ids:
                    task_id, score, _ = _process_trial(
                        client, trial_id, model_id, debug_logger, task_filter, False
                    )
                    if score is not None:
                        scores.append((task_id, score))
        finally:
            client.submit_run(SubmitRunRequest(run_id=run.run_id, force=True))

    except ConnectError as exc:
        print(f"{exc.code}: {exc.message}")
        debug_logger.log("run_error", error_code=str(exc.code), error_message=exc.message)
    except KeyboardInterrupt:
        print(f"{CLI_RED}Interrupted{CLI_CLR}")
        debug_logger.log("run_interrupted")

    if scores:
        # Sort by task_id for stable output regardless of completion order.
        scores.sort(key=lambda x: x[0])
        for task_id, score in scores:
            style = CLI_GREEN if score == 1 else CLI_RED
            print(f"{task_id}: {style}{score:0.2f}{CLI_CLR}")

        total = sum(score for _, score in scores) / len(scores) * 100.0
        print(f"FINAL: {total:0.2f}%")
        debug_logger.log("run_finished", final_score=total, scores=scores)
    else:
        debug_logger.log("run_finished", final_score=None, scores=scores)
    debug_logger.close()


if __name__ == "__main__":
    main()
