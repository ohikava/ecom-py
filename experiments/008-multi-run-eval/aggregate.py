"""Aggregate multiple bench runs to estimate noise (σ) on the BitGN ECOM suite.

Reads every results/run*.jsonl, extracts per-trial scores + outcomes, prints
a markdown summary, and writes it to results/summary.md.

Statistics produced:
  - Per-run aggregate score (% of mean(score) over all trials).
  - Cross-run mean, stdev, 95% CI of aggregate score.
  - Per-task: mean, stdev, min, max, pass_count, outcome distribution.
  - Categorisation: always_pass (k=N), always_fail (k=0), flaky (0<k<N).

The runs themselves are produced by `python -m main` in
experiments/007-codex-discount-refs/agent/, normally with WORKERS=3 and the
output JSONL renamed into results/runN.jsonl.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

_RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _parse_run(path: Path) -> dict[str, dict]:
    """Return {task_id: {score, outcome, score_detail}} for one run JSONL."""
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            tid = ev.get("task_id") or ""
            if not tid:
                continue
            e = ev.get("event", "")
            if e == "trial_finished":
                out.setdefault(tid, {})["score"] = ev.get("score")
                out[tid]["score_detail"] = ev.get("score_detail") or []
            elif e == "agent_completed":
                out.setdefault(tid, {})["outcome"] = ev.get("outcome")
    return out


def _ci95(values: list[float]) -> float:
    """Half-width of a 95% confidence interval for the mean. For n<2 returns 0."""
    n = len(values)
    if n < 2:
        return 0.0
    return 1.96 * statistics.stdev(values) / math.sqrt(n)


def _fmt(x: float) -> str:
    return f"{x:.4f}"


def main() -> None:
    run_files = sorted(_RESULTS_DIR.glob("run*.jsonl"))
    if not run_files:
        print(f"No runs found in {_RESULTS_DIR}")
        return

    runs = [_parse_run(p) for p in run_files]
    n_runs = len(runs)
    print(f"Loaded {n_runs} runs from {_RESULTS_DIR}")

    # ── Per-task aggregation ────────────────────────────────────────────
    all_tids = sorted({t for r in runs for t in r})
    per_task: dict[str, dict] = {}
    for tid in all_tids:
        scores = [r[tid]["score"] for r in runs if tid in r and r[tid].get("score") is not None]
        outcomes = [r[tid].get("outcome") for r in runs if tid in r and r[tid].get("outcome")]
        if not scores:
            continue
        per_task[tid] = {
            "n": len(scores),
            "mean": statistics.mean(scores),
            "std": statistics.stdev(scores) if len(scores) > 1 else 0.0,
            "min": min(scores),
            "max": max(scores),
            "pass_count": sum(1 for s in scores if s == 1.0),
            "fail_count": sum(1 for s in scores if s == 0.0),
            "outcomes": Counter(outcomes),
            "scores": scores,
        }

    # ── Per-run aggregate (% mean over all task scores in that run) ─────
    run_means: list[float] = []
    for r in runs:
        run_scores = [v["score"] for v in r.values() if v.get("score") is not None]
        run_means.append(statistics.mean(run_scores) if run_scores else 0.0)

    mean = statistics.mean(run_means)
    std = statistics.stdev(run_means) if len(run_means) > 1 else 0.0
    ci = _ci95(run_means)

    # ── Categorise tasks ────────────────────────────────────────────────
    always_pass: list[str] = []
    always_fail: list[str] = []
    flaky: list[tuple[str, int, int]] = []
    for tid, st in per_task.items():
        if st["pass_count"] == st["n"]:
            always_pass.append(tid)
        elif st["pass_count"] == 0 and st["max"] < 1.0:
            always_fail.append(tid)
        else:
            flaky.append((tid, st["pass_count"], st["n"]))

    # ── Build summary markdown ──────────────────────────────────────────
    lines: list[str] = []
    lines.append("# 008-multi-run-eval — summary\n")
    lines.append(
        f"Runs: **{n_runs}** "
        f"(files: {', '.join(p.name for p in run_files)})\n"
    )
    lines.append("## Aggregate score across runs\n")
    lines.append("| Run | Score | Hard wins / Total |")
    lines.append("|---|---|---|")
    for path, r, m in zip(run_files, runs, run_means):
        hard = sum(1 for v in r.values() if v.get("score") == 1.0)
        tot = sum(1 for v in r.values() if v.get("score") is not None)
        lines.append(f"| `{path.name}` | {m*100:.2f}% | {hard} / {tot} |")
    lines.append("")
    lines.append(f"**Mean:** {mean*100:.2f}%")
    lines.append(f"**StDev:** {std*100:.2f} pp")
    lines.append(f"**95% CI half-width:** ±{ci*100:.2f} pp (n={n_runs})")
    lines.append(f"**Range:** [{min(run_means)*100:.2f}%, {max(run_means)*100:.2f}%]")
    lines.append("")

    lines.append("## Task categorisation\n")
    lines.append(
        f"- **always_pass** (k=N): **{len(always_pass)}** tasks — "
        f"{', '.join(always_pass) if always_pass else '—'}"
    )
    lines.append(
        f"- **always_fail** (k=0): **{len(always_fail)}** tasks — "
        f"{', '.join(always_fail) if always_fail else '—'}"
    )
    lines.append(f"- **flaky** (0<k<N or partial credit): **{len(flaky)}** tasks")
    if flaky:
        lines.append("")
        lines.append("### Flaky tasks (per-run scores)\n")
        lines.append("| Task | Pass / N | Mean | Std | Min | Max | Outcomes |")
        lines.append("|---|---|---|---|---|---|---|")
        for tid, p, n in sorted(flaky):
            st = per_task[tid]
            outcomes = " / ".join(f"{o}:{c}" for o, c in st["outcomes"].most_common())
            lines.append(
                f"| {tid} | {p}/{n} | {st['mean']:.2f} | {st['std']:.2f} | "
                f"{st['min']:.2f} | {st['max']:.2f} | {outcomes} |"
            )
        lines.append("")

    lines.append("## Per-task full table\n")
    lines.append("| Task | Mean | Std | Pass/N | Outcomes |")
    lines.append("|---|---|---|---|---|")
    for tid in sorted(per_task):
        st = per_task[tid]
        outcomes = " / ".join(f"{o}:{c}" for o, c in st["outcomes"].most_common())
        lines.append(
            f"| {tid} | {st['mean']:.2f} | {st['std']:.2f} | "
            f"{st['pass_count']}/{st['n']} | {outcomes} |"
        )

    text = "\n".join(lines)
    print(text)
    summary_path = _RESULTS_DIR / "summary.md"
    summary_path.write_text(text, encoding="utf-8")
    print(f"\n[written to {summary_path}]")


if __name__ == "__main__":
    main()
