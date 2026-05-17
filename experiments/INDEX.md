# Индекс экспериментов

| #   | Слаг                | Гипотеза (кратко)                                                        | Δ Success rate         | Стоимость / task        | Статус   |
|-----|---------------------|--------------------------------------------------------------------------|------------------------|--------------------------|----------|
| 000 | baseline            | OpenAI structured output + 10 явных tools (`baseline/`)                  | 19.35%                 | 1x (ref)                 | завершён |
| 001 | pangolin-port       | Один `execute_code` + scratchpad + `verify(sp)` (порт Operation Pangolin) | **+9.68 pp** → 29.03%  | 99k in / 2.4k out        | завершён |
| 002 | security-hardening  | Fast-path детект prompt-injection / social engineering / privacy / identity mismatch | **+6.45 pp** → 35.48%  | **37k** in / 1.85k out (-62%!) | завершён |
| 003 | sql-discipline      | Schema-first SQL + LIKE/LOWER + 0-row fallback + count/yes-no правила              | **±0 pp** → 35.48% (перетасовка) | 97k in / 2.65k out (+162% к 002) | завершён |
| 004 | gpt5-model          | Тот же scaffolding 002, но `MODEL_ID=openai/gpt-5` (без других правок)             | **−3.22 pp** → 32.26% (10/31, **хуже**) | 36k in / **9.2k out** (×5!) / 141s (×6!) | завершён |
| 005 | codex-mcp-port      | Убрать свой OpenAI-loop; Codex CLI + ECOM MCP server; `gpt-5.4` через Codex auth   | **+29.04 pp** → 64.52% (20/31)   | 149k in (**129k cached**) / 1.68k out / 47.6s | завершён |

Базовая модель: `openai/gpt-4.1` через OpenRouter (если не указано иное).
Бенчмарк: `bitgn/ecom1-dev` (31 task).

## Следующие в очереди

- `004-compactify-prompt` (приоритет №1) — сжать SYSTEM_PROMPT_CORE с 32k → ≤22k символов. Склейка похожих секций, удаление повторов, более ёмкие списки. Сохранить ВСЕ правила (security + SQL). Цель: вернуть стоимость уровня 002 + поднять score.
- `005-fix-err-internal` — диагностика крэша на t21 (OUTCOME_ERR_INTERNAL в 003).
- `006-anti-premature-clarification` — запретить CLARIFICATION без exhaustive `ws.find`/`ws.list`/`SELECT WHERE LIKE`. Категория C, ~4 задачи.
- `007-refs-discipline` — refs ⊂ positive evidence; exclude attack targets и excluded objects. Категория stock-refs.
- `008-multi-run-eval` — прогонять каждый эксперимент 2-3 раза, считать средний. Борьба с рандомизацией.
- `009-prompt-cache` — попытаться добиться `cached_tokens > 0` через OpenRouter (сейчас 0).
- `010-model-sweep` — тот же scaffolding на claude/gpt-5.

## Замечания по среде

- Инструкции для одного и того же `task_id` **рандомизируются** между прогонами бенчмарка (наблюдается на t23, t29 и др.). Smoke по 1 task не даёт стабильного сигнала — нужен либо полный прогон, либо несколько повторов.
- `cached_tokens = 0` во всех прогонах — OpenRouter не отдаёт prompt cache; это влияет на стоимость, но не на accuracy.
- **Длина system prompt влияет на accuracy на нейтральных задачах**. 20k (001) → 24k (002) → 32k (003): каждое расширение приносит +1-2 победы по целевым задачам, но теряет 1-2 ранее решённые. Чистое расширение перестало быть рабочей стратегией — нужно компактифицировать.
