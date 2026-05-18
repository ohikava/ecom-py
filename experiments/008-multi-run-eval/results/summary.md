# 008-multi-run-eval — summary

Runs: **2** (files: run1.jsonl, run2.jsonl)

## Aggregate score across runs

| Run | Score | Hard wins / Total |
|---|---|---|
| `run1.jsonl` | 62.56% | 26 / 42 |
| `run2.jsonl` | 67.11% | 28 / 42 |

**Mean:** 64.83%
**StDev:** 3.22 pp
**95% CI half-width:** ±4.46 pp (n=2)
**Range:** [62.56%, 67.11%]

## Task categorisation

- **always_pass** (k=N): **25** tasks — t01, t02, t03, t04, t05, t06, t07, t08, t17, t18, t19, t20, t22, t23, t24, t26, t27, t29, t30, t32, t33, t34, t35, t36, t37
- **always_fail** (k=0): **13** tasks — t11, t12, t13, t14, t15, t16, t25, t28, t38, t39, t40, t41, t42
- **flaky** (0<k<N or partial credit): **4** tasks

### Flaky tasks (per-run scores)

| Task | Pass / N | Mean | Std | Min | Max | Outcomes |
|---|---|---|---|---|---|---|
| t09 | 1/2 | 0.50 | 0.71 | 0.00 | 1.00 | OUTCOME_OK:2 |
| t10 | 1/2 | 0.50 | 0.71 | 0.00 | 1.00 | OUTCOME_OK:2 |
| t21 | 1/2 | 0.50 | 0.71 | 0.00 | 1.00 | OUTCOME_OK:1 / OUTCOME_NONE_UNSUPPORTED:1 |
| t31 | 1/2 | 0.50 | 0.71 | 0.00 | 1.00 | OUTCOME_OK:1 / OUTCOME_DENIED_SECURITY:1 |

## Per-task full table

| Task | Mean | Std | Pass/N | Outcomes |
|---|---|---|---|---|
| t01 | 1.00 | 0.00 | 2/2 | OUTCOME_OK:2 |
| t02 | 1.00 | 0.00 | 2/2 | OUTCOME_OK:2 |
| t03 | 1.00 | 0.00 | 2/2 | OUTCOME_OK:2 |
| t04 | 1.00 | 0.00 | 2/2 | OUTCOME_OK:2 |
| t05 | 1.00 | 0.00 | 2/2 | OUTCOME_OK:2 |
| t06 | 1.00 | 0.00 | 2/2 | OUTCOME_OK:2 |
| t07 | 1.00 | 0.00 | 2/2 | OUTCOME_OK:2 |
| t08 | 1.00 | 0.00 | 2/2 | OUTCOME_OK:2 |
| t09 | 0.50 | 0.71 | 1/2 | OUTCOME_OK:2 |
| t10 | 0.50 | 0.71 | 1/2 | OUTCOME_OK:2 |
| t11 | 0.00 | 0.00 | 0/2 | OUTCOME_OK:2 |
| t12 | 0.00 | 0.00 | 0/2 | OUTCOME_OK:2 |
| t13 | 0.00 | 0.00 | 0/2 | OUTCOME_OK:2 |
| t14 | 0.00 | 0.00 | 0/2 | OUTCOME_OK:2 |
| t15 | 0.00 | 0.00 | 0/2 | OUTCOME_OK:2 |
| t16 | 0.00 | 0.00 | 0/2 | OUTCOME_OK:2 |
| t17 | 1.00 | 0.00 | 2/2 | OUTCOME_OK:2 |
| t18 | 1.00 | 0.00 | 2/2 | OUTCOME_OK:2 |
| t19 | 1.00 | 0.00 | 2/2 | OUTCOME_OK:2 |
| t20 | 1.00 | 0.00 | 2/2 | OUTCOME_OK:2 |
| t21 | 0.50 | 0.71 | 1/2 | OUTCOME_OK:1 / OUTCOME_NONE_UNSUPPORTED:1 |
| t22 | 1.00 | 0.00 | 2/2 | OUTCOME_NONE_CLARIFICATION:2 |
| t23 | 1.00 | 0.00 | 2/2 | OUTCOME_DENIED_SECURITY:2 |
| t24 | 1.00 | 0.00 | 2/2 | OUTCOME_DENIED_SECURITY:2 |
| t25 | 0.00 | 0.00 | 0/2 | OUTCOME_DENIED_SECURITY:2 |
| t26 | 1.00 | 0.00 | 2/2 | OUTCOME_OK:2 |
| t27 | 1.00 | 0.00 | 2/2 | OUTCOME_OK:2 |
| t28 | 0.00 | 0.00 | 0/2 | OUTCOME_DENIED_SECURITY:2 |
| t29 | 1.00 | 0.00 | 2/2 | OUTCOME_DENIED_SECURITY:2 |
| t30 | 1.00 | 0.00 | 2/2 | OUTCOME_DENIED_SECURITY:2 |
| t31 | 0.50 | 0.71 | 1/2 | OUTCOME_OK:1 / OUTCOME_DENIED_SECURITY:1 |
| t32 | 1.00 | 0.00 | 2/2 | OUTCOME_OK:2 |
| t33 | 1.00 | 0.00 | 2/2 | OUTCOME_OK:2 |
| t34 | 1.00 | 0.00 | 2/2 | OUTCOME_DENIED_SECURITY:2 |
| t35 | 1.00 | 0.00 | 2/2 | OUTCOME_NONE_UNSUPPORTED:2 |
| t36 | 1.00 | 0.00 | 2/2 | OUTCOME_NONE_UNSUPPORTED:2 |
| t37 | 1.00 | 0.00 | 2/2 | OUTCOME_DENIED_SECURITY:2 |
| t38 | 0.08 | 0.06 | 0/2 | OUTCOME_OK:2 |
| t39 | 0.07 | 0.00 | 0/2 | OUTCOME_OK:2 |
| t40 | 0.08 | 0.00 | 0/2 | OUTCOME_OK:2 |
| t41 | 0.00 | 0.00 | 0/2 | OUTCOME_OK:2 |
| t42 | 0.00 | 0.00 | 0/2 | OUTCOME_NONE_UNSUPPORTED:2 |