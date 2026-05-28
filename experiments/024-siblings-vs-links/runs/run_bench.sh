#!/usr/bin/env bash
# Runs 5 sequential iterations of the 4 fraud tasks (t38, t39, t40, t48).
# Each iteration:
#   - truncates agent/ecom_mcp.log so we can rotate it cleanly per-run
#   - runs `python -m main t38 t39 t40 t48` with WORKERS=4 (4 fraud tasks
#     parallel inside one iteration)
#   - tees stdout to runs/run_<N>.log
#   - copies the freshly-rotated MCP log and the just-created JSONL into
#     runs/run_<N>_mcp.log and runs/run_<N>_debug.jsonl
#
# Pre-conditions:
#   - venv/ activated (PYTHONPATH etc.) — call as `bash runs/run_bench.sh`
#     from project root after `source venv/bin/activate`
#   - .env at repo root carries BITGN_API_KEY + OPENROUTER_API_KEY
#
# Override the number of iterations via:
#   RUNS=3 bash runs/run_bench.sh
# Override task subset via:
#   TASKS="${TASKS:-t07 t22 t26 t27 t32 t41 t44 t46 t50}"

set -euo pipefail

EXPDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTDIR="${EXPDIR}/agent"
RUNSDIR="${EXPDIR}/runs"

RUNS="${RUNS:-1}"
TASKS="${TASKS:-t07 t22 t26 t27 t32 t41 t44 t46 t50}"
export WORKERS="${WORKERS:-4}"

echo "Experiment dir : ${EXPDIR}"
echo "Agent dir      : ${AGENTDIR}"
echo "Iterations     : ${RUNS}"
echo "Tasks          : ${TASKS}"
echo "Workers        : ${WORKERS}"
echo

cd "${AGENTDIR}"

for i in $(seq 1 "${RUNS}"); do
  echo "================================================================"
  echo "== RUN ${i}/${RUNS} :: tasks=${TASKS}                                "
  echo "================================================================"

  # Rotate MCP log: capture pre-existing tail (if any), then truncate.
  : > "${AGENTDIR}/ecom_mcp.log"

  # Snapshot existing JSONLs so we can identify the new one created by this run.
  before_jsonl=$(ls -1 "${AGENTDIR}"/*.jsonl 2>/dev/null | sort || true)

  STDOUT_LOG="${RUNSDIR}/run_${i}.log"
  set +e
  # shellcheck disable=SC2086
  python -m main ${TASKS} 2>&1 | tee "${STDOUT_LOG}"
  rc=${PIPESTATUS[0]}
  set -e

  # Identify the new JSONL (one that wasn't present before).
  after_jsonl=$(ls -1 "${AGENTDIR}"/*.jsonl 2>/dev/null | sort || true)
  new_jsonl=$(comm -13 <(echo "${before_jsonl}") <(echo "${after_jsonl}") | head -1)
  if [[ -n "${new_jsonl}" && -f "${new_jsonl}" ]]; then
    cp "${new_jsonl}" "${RUNSDIR}/run_${i}_debug.jsonl"
    echo "Captured debug jsonl: ${new_jsonl}"
  else
    echo "WARN: no new JSONL detected for run ${i}"
  fi

  # Snapshot the MCP log for this run.
  cp "${AGENTDIR}/ecom_mcp.log" "${RUNSDIR}/run_${i}_mcp.log"

  echo "Run ${i} finished (rc=${rc}); artifacts:"
  echo "  ${STDOUT_LOG}"
  echo "  ${RUNSDIR}/run_${i}_mcp.log"
  echo "  ${RUNSDIR}/run_${i}_debug.jsonl"
  echo
done

echo "All ${RUNS} iterations complete."
echo "Per-run final scores:"
for i in $(seq 1 "${RUNS}"); do
  printf "\n--- run %d ---\n" "${i}"
  grep -E "^t[0-9]+: |FINAL:" "${RUNSDIR}/run_${i}.log" || echo "(no scores found in run_${i}.log)"
done
