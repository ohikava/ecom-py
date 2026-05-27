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
| 010 | policy-docs-refs    | Bootstrap `tree /docs -L 4` + prompt-rule "cite matching dated policy doc"; целит t09-t12, t41-t42 (cat refs-doc) | **+11.05 pp на 40t-overlap** ✅ → 78.55%; 3/3 hits на t09-t11 (t12 over-citation), 1/1 на t41 smoke; t41-t44 quota-corrupted на full | 232k in / 1.77k out / 49.2s (cost-neutral, **−10% elapsed**) | завершён (40/44 clean) |
| 011 | generalize-silent   | Universal "evidence ≡ answer objects" + 5 anti-patterns (verify-SKU, count-product, report-category, count-with-criterion, find-matching); pre-call check для `ecom_read` | **+4.73 pp на 40t-overlap** → 83.28% (35/40); 3/3 на target (t08, t12, t20); t41-t42 confirmed на full; 1 induced regression t11 (count-aggregate scalar); 50t bench = 76.63% | 257k in / 2.18k out / 77.8s (+11% input, +58% elapsed) | завершён |

Базовая модель: `openai/gpt-4.1` через OpenRouter (если не указано иное).
Бенчмарк: `bitgn/ecom1-dev` — **рос с 31 → 40 → 42 → 44 → 50 tasks** между сериями экспериментов.

## Следующие в очереди

- **012 — count-aggregate refs carve-out** (high; новый из 011 failure analysis). Узкое правило: для scalar count answers (no enumeration) refs = только scope/policy doc; per-record probes — silent или SQL. Target: t11 deterministic +1. Возможно +1 на t43 если он count-related.
- **013 — t46 DENIED-без-security расследование** (medium). Новый attack-pattern не triggered fast-path A-E. Целит +1.
- **014 — fraud-selectivity** (medium). t38-t40 + t48 — 4 chronic, recall/precision tradeoff. Требует semantic boost `/docs/payments/3ds.md` или специфический SQL discipline.
- **015 — multi-run sanity на 011** (medium). 2-3 повтора для σ на новом 50-task bench.
- **016 — outcome-mismatch class** (low; t25, t28). Randomization-driven, низкий приоритет.

## Замечания по среде

- Инструкции для одного и того же `task_id` **рандомизируются** между прогонами бенчмарка (наблюдается на t23, t29 и др.). Smoke по 1 task не даёт стабильного сигнала — нужен либо полный прогон, либо несколько повторов.
- `cached_tokens = 0` во всех прогонах — OpenRouter не отдаёт prompt cache; это влияет на стоимость, но не на accuracy.
- **Длина system prompt влияет на accuracy на нейтральных задачах**. 20k (001) → 24k (002) → 32k (003): каждое расширение приносит +1-2 победы по целевым задачам, но теряет 1-2 ранее решённые. Чистое расширение перестало быть рабочей стратегией — нужно компактифицировать.
