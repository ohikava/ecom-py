# Индекс экспериментов

| #   | Слаг                | Гипотеза (кратко)                                                        | Δ Success rate         | Стоимость / task        | Статус   |
|-----|---------------------|--------------------------------------------------------------------------|------------------------|--------------------------|----------|
| 000 | baseline            | OpenAI structured output + 10 явных tools (`baseline/`)                  | 19.35%                 | 1x (ref)                 | завершён |
| 001 | pangolin-port       | Один `execute_code` + scratchpad + `verify(sp)` (порт Operation Pangolin) | **+9.68 pp** → 29.03%  | 99k in / 2.4k out        | завершён |
| 002 | security-hardening  | Fast-path детект prompt-injection / social engineering / privacy / identity mismatch | **+6.45 pp** → 35.48%  | **37k** in / 1.85k out (-62%!) | завершён |
| 003 | sql-discipline      | Schema-first SQL + LIKE/LOWER + 0-row fallback + count/yes-no правила              | **±0 pp** → 35.48% (перетасовка) | 97k in / 2.65k out (+162% к 002) | завершён |
| 004 | gpt5-model          | Тот же scaffolding 002, но `MODEL_ID=openai/gpt-5` (без других правок)             | **−3.22 pp** → 32.26% (10/31, **хуже**) | 36k in / **9.2k out** (×5!) / 141s (×6!) | завершён |
| 005 | codex-mcp-port      | Убрать свой OpenAI-loop; Codex CLI + ECOM MCP server; `gpt-5.4` через Codex auth   | **+29.04 pp** → 64.52% (20/31)   | 149k in (**129k cached**) / 1.68k out / 47.6s | завершён |
| 006 | codex-refs-fix      | `ecom_read_silent` + post-process DENIED refs + prompt SQL-step-5                  | **+12.90 pp на overlap** → 77.42% (24/31), 74.24% на расширенном 40-task бенчмарке | 210k in (**180k cached**) / 1.72k out / 52.1s | завершён |
| 007 | codex-discount-refs | topic→policy doc map (`/docs/discounts.md`, `/docs/payments/3ds.md`) для DENIED   | **+2.77 pp** → 77.01% (30/40); 2/3 target wins (t25, t37); шум съел сигнал на overlap | 211k in (177k cached) / 1.88k out / 52.2s | завершён |
| 008 | multi-run-eval      | 3× прогон 007 baseline для оценки σ; **+ WORKERS=3 parallelization patch**         | **n=2 (run3 hit quota)**: mean **64.83%**, σ **3.22 pp**, 95% CI ±4.46 pp. Bench вырос 40→42 задач. 007 single-run 77.01% — outlier ~3.8σ выше 008 mean → likely bench-shift между датами | 1.7M tok / run, ~11 мин wall time @ WORKERS=3 | частично |
| 009 | probing-silent      | Step 5 → silent probe + tracked-read только qualifying subset; целит t13-t16 (cat A) | **4/4 hit на target** ✅; на 42-overlap −0.54 pp (27/42, в зоне σ); 44-task bench 61.36%; t08, t20 — рула не обобщилась | 227k in / 2.0k out / 54.8s (+7% к 007) | завершён |

Базовая модель: `openai/gpt-4.1` через OpenRouter (если не указано иное).
Бенчмарк: `bitgn/ecom1-dev` (31 task).

## Следующие в очереди

- **009b — generalize Step 5** (high). Переписать "if you read more records than your answer cites, the extras must be `ecom_read_silent`" — обобщить узкий "how many of these N" паттерн до универсального правила. Target: t08, t20 без регрессии target t13-t16. Risk: over-silent на legitimate evidence reads.
- **010 — policy-docs-refs** (high). t09, t10, t11, t12, t41, t42 — все always_fail с одинаковой ошибкой `missing required reference '/docs/<policy-doc>.md'`. Похоже на 007 discount-refs pattern. Ожидание: +6 wins, если evaluator-side rule consistent.
- **011 — fraud-selectivity** (medium). t38-t40: recall ~100%, precision ~5-15%. Chaos category, требует chain-of-thought про exact match criteria.
- **012 — multi-run на 009 или 009b** (medium). 2-3 повтора для measurement σ на 44-task bench. Подтвердить deterministic 4/4 на target.

## Замечания по среде

- Инструкции для одного и того же `task_id` **рандомизируются** между прогонами бенчмарка (наблюдается на t23, t29 и др.). Smoke по 1 task не даёт стабильного сигнала — нужен либо полный прогон, либо несколько повторов.
- `cached_tokens = 0` во всех прогонах — OpenRouter не отдаёт prompt cache; это влияет на стоимость, но не на accuracy.
- **Длина system prompt влияет на accuracy на нейтральных задачах**. 20k (001) → 24k (002) → 32k (003): каждое расширение приносит +1-2 победы по целевым задачам, но теряет 1-2 ранее решённые. Чистое расширение перестало быть рабочей стратегией — нужно компактифицировать.
