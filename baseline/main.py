import os
import textwrap

from env_loader import load_dotenv
from debug_logger import JsonlDebugLogger

load_dotenv()

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

from agent import run_agent
from http_sync_client import HttpxSyncClient


CLI_RED = "\x1B[31m"
CLI_GREEN = "\x1B[32m"
CLI_CLR = "\x1B[0m"
CLI_BLUE = "\x1B[34m"


def main() -> None:
    bitgn_url = (
        os.getenv("BITGN_HOST")
        or os.getenv("BENCHMARK_HOST")
        or "https://api.bitgn.com"
    )
    bitgn_api_key = os.getenv("BITGN_API_KEY") or ""
    bench_id = os.getenv("BENCH_ID") or os.getenv("BENCHMARK_ID") or "bitgn/ecom1-dev"
    model_id = os.getenv("MODEL_ID") or "openai/gpt-4.1"

    task_filter = os.sys.argv[1:]
    scores = []
    debug_logger = JsonlDebugLogger()
    debug_logger.log(
        "run_started",
        benchmark_id=bench_id,
        model_id=model_id,
        task_filter=task_filter,
    )
    print(f"Debug logs: {debug_logger.path.name}")

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
                name="ECOM Python Sample",
                benchmark_id=bench_id,
                api_key=bitgn_api_key,
            )
        )

        try:
            for trial_id in run.trial_ids:
                trial = client.start_trial(
                    StartTrialRequest(trial_id=trial_id),
                )
                if task_filter and trial.task_id not in task_filter:
                    continue

                print(f"{'=' * 30} Starting task: {trial.task_id} {'=' * 30}")
                print(f"{CLI_BLUE}{trial.instruction}{CLI_CLR}\n{'-' * 80}")
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
                    print(exc)
                    debug_logger.log(
                        "trial_failed",
                        task_id=trial.task_id,
                        trial_id=trial.trial_id,
                        error=str(exc),
                    )

                result = client.end_trial(EndTrialRequest(trial_id=trial.trial_id))
                debug_logger.log(
                    "trial_finished",
                    task_id=trial.task_id,
                    trial_id=trial.trial_id,
                    score_available=result.score_available,
                    score=result.score if result.score_available else None,
                    score_detail=list(result.score_detail),
                )
                if result.score_available:
                    scores.append((trial.task_id, result.score))
                    style = CLI_GREEN if result.score == 1 else CLI_RED
                    explain = textwrap.indent("\n".join(result.score_detail), "  ")
                    print(
                        f"\n{style}Score: {result.score:0.2f}\n{explain}\n{CLI_CLR}"
                    )
                else:
                    print(f"\n{CLI_BLUE}Score: not available{CLI_CLR}\n")
        finally:
            client.submit_run(SubmitRunRequest(run_id=run.run_id, force=True))

    except ConnectError as exc:
        print(f"{exc.code}: {exc.message}")
        debug_logger.log("run_error", error_code=str(exc.code), error_message=exc.message)
    except KeyboardInterrupt:
        print(f"{CLI_RED}Interrupted{CLI_CLR}")
        debug_logger.log("run_interrupted")

    if scores:
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
