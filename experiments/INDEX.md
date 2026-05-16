# Индекс экспериментов

| #   | Слаг               | Гипотеза (кратко)                                                        | Δ Success rate | Δ Стоимость     | Статус   |
|-----|--------------------|--------------------------------------------------------------------------|----------------|------------------|----------|
| 000 | baseline           | OpenAI structured output + 10 явных tools (`baseline/`)                  | 19.35%         | 1x (ref)         | завершён |
| 001 | pangolin-port      | Один `execute_code` + scratchpad + `verify(sp)` (порт Operation Pangolin) | **+9.68 pp** → 29.03% | ~99k in / 2.4k out / task | завершён |

Базовая модель: `openai/gpt-4.1` через OpenRouter (если не указано иное).
Бенчмарк: `bitgn/ecom1-dev` (31 task).

## Следующие в очереди

- `002-refs-from-sql` — автотрекинг путей из stdout `/bin/sql` (ожидаемый прирост +3–5 pp).
- `003-answer-format-conventions` — документировать `<COUNT:N>` и прочие теги.
- `004-strict-disambiguation` — hard-stop при множественных кандидатах.
- `005-anti-premature-clarification` — запрет ранней CLARIFICATION.
- `006-fast-security-check` — безусловный prompt-injection pre-check.
- `007-prompt-cache` — попытаться добиться cached_tokens > 0.
- `008-model-sweep` — тот же scaffolding на claude/gpt-5.
