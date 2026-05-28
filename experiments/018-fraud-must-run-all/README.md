# 018 — fraud-must-run-all

**Дата:** 2026-05-28
**Статус:** в работе
**Автор/агент:** Ivan + Claude Opus 4.7 (1M context)
**Бранч/коммит:** `main @ 8030768`
**Базлайн:** `017c-fraud-skill-tight` (4 fraud-задачи: t38=0.38, t39=0.37, t40=0.34, t48=0.00)

## Гипотеза

Текущий SKILL.md явно велит «stop at the first cluster that produces a coherent fraud story»
и «pick the tightest cluster ... resist the urge to also flag weaker secondary clusters». В
логах 017c видно, что агент именно так и делает: на t38/t39/t40 находит ОДИН кластер
(по Pattern 1 или 2) и закрывает задачу. Грейдер при этом ждёт больше payment-ов —
recall 24–55% EUR.

**Если** переписать SKILL.md под «прогнать ВСЕ 5 паттернов независимо + взять union
кластеров перед ответом» (с anti-pattern явно про early-stop и worked-example на ДВУХ
disjoint кластерах), **recall на t38/t39/t40 должен подняться на 20–40 pp**.

Риск: precision просядет (больше false positives) → возможны новые потери на
overflagging. Это будет видно по детализации грейдера.

Точка измерения — только 4 fraud-задачи. Цель эксперимента — изолированно проверить
гипотезу, не трогая non-fraud distribution.

## Что меняем (diff vs 017c)

Только `agent/hermes_home/skills/ecom-fraud-forensic/SKILL.md`:

1. Добавлен второй **Core principle**: «fraud is MULTI-CLUSTER, not single-cluster»,
   с явным «MANDATORY: run ALL FIVE patterns to completion».
2. Заголовок секции паттернов: было «Behavioural fraud patterns — these are the
   signals» (+ инструкция «stop at the first cluster»), стало «Behavioural fraud
   patterns — independent detectors» (+ «Run every one of these. Each is a standalone
   classifier ... Collect them all; dedupe at the end»).
3. **Procedure**: бывший пункт 4 «Pick the tightest cluster ... resist the urge to
   also flag weaker secondary clusters» заменён на пункт 3 «Union & dedupe: union
   of all payment_ids flagged by ANY pattern».
4. **Worked example** — теперь два disjoint кластера (P1+P2 на cust_042 + P3
   device-ring), explicit Wrong answer = «early-stop on cluster A only».
5. **Anti-patterns** — добавлены 3 новых:
   - «Stopping after the first pattern produces a hit»
   - «Pattern 2 covered P1, so I'll skip P3-P5»
   - «"one hit" framing as structural cap»

Тело паттернов P1–P5 — без изменений.

Frontmatter `description` — без изменений (т.е. сохраняем tight activation rules из 017c).

Всё остальное (agent code, prompts, MCP server, config.yaml) — побайтово скопировано
из 017c.

## Метод прогона

- Запуск через `runs/run_bench.sh` — wrapper, делающий 5 последовательных вызовов
  `python -m main t38 t39 t40 t48` с `WORKERS=4` (4 задачи параллельно внутри
  одного прогона, прогоны между собой — sequential).
- Каждый прогон сохраняет:
  - `runs/run_N.log` — полный stdout (`tee`-ed)
  - `runs/run_N_mcp.log` — ротация `agent/ecom_mcp.log` (truncate перед каждым прогоном)
  - `runs/run_N_debug.jsonl` — копия `agent/<date>-N.jsonl` (Hermes JSONL логгер
    сам инкрементит суффикс)
- Между прогонами агент НЕ перезапускается; sessions/state.db естественно копится
  как в реальном бенчмарке.

## Результат

(заполнить после прогона)

| Метрика | 017c | 018 run1 | run2 | run3 | run4 | run5 | mean | σ |
|---|---|---|---|---|---|---|---|---|
| t38 | 0.38 | | | | | | | |
| t39 | 0.37 | | | | | | | |
| t40 | 0.34 | | | | | | | |
| t48 | 0.00 | | | | | | | |
| mean | 0.272 | | | | | | | |

## Выводы

(заполнить после анализа per-run логов)
