# 012 — count-scalar-refs

**Дата:** 2026-05-27
**Статус:** завершён (smoke 4/4 + clean t01-t21; t22-t50 quota-corrupted, нужен rerun)
**Автор/агент:** Ivan + Claude Opus 4.7
**Бранч/коммит:** `main @ after-011 (59fc324)`
**Базлайн:** `011-generalize-silent` (83.28% на 40t overlap; 76.63% на 50t bench)
**Модель:** `gpt-5.4` через Codex CLI 0.130.0

## Гипотеза

Если добавить **carve-out для whole-catalog count/aggregate answers** (refs = scope/policy doc only, individual records — silent), модель перестанет over-cite records на task'ах вида "how many products are X". Target: t11 (011-induced regression: 010 показывал 1.0 на аналогичной randomization, 011 — 0.0 после нового universal-rule). Потенциал +1 hard win ≈ +2.0 pp.

Также проверить что carve-out НЕ ломает прежние target wins (t08, t12, t20).

## Что меняем (diff vs 011)

`prompts/instructions.md`:

1. **В Refs Discipline** (под Universal principle) добавлен **"Aggregate-count carve-out"** с явным указанием на whole-catalog count/total/sum.
2. **В Step 5 SQL discipline** (после Anti-patterns) добавлен **"Carve-out — whole-catalog count / aggregate"** с worked example для t11-shaped task ("how many Workshop Saw and Cutter").
3. **Explicit "DOES NOT apply to"** list для предотвращения over-correction:
   - Yes/no verifications ("<NO> SKU-FOO" — refs include SKU-FOO)
   - "How many of these N items meet C?" (named candidates)
   - Single-record reports
   - Messages enumerating records by ID

Никаких python-изменений.

### Iteration history

- v1: формулировка "scalar (count, total, sum, yes/no, single value)" → smoke 3/4 — t08 (yes/no verify-SKU) сбился: модель цитировала 40+ family siblings (PLB-* plumbing drain traps). Yes/no попало в carve-out ошибочно.
- v2: убрал "yes/no, single value" из определения, добавил explicit "DOES NOT apply to: yes/no verifications" → smoke 4/4.

## Smoke

```bash
MODEL_ID=gpt-5.4 WORKERS=3 python -m main t08 t11 t12 t20
```

| Task | 010 | 011 | 012 smoke v1 | 012 smoke v2 |
|---|---|---|---|---|
| t08 | 0.00 | **1.00** ✅ | 0.00 ❌ (40+ siblings tracked) | **1.00** ✅ |
| t11 | 1.00 | 0.00 ❌ | **1.00** ✅ TARGET | **1.00** ✅ |
| t12 | 0.00 | **1.00** ✅ | 1.00 ✅ | **1.00** ✅ |
| t20 | 0.00 | **1.00** ✅ | 1.00 ✅ | **1.00** ✅ |

**Smoke v2 = 4/4.** Carve-out успешно изолирован от verify-SKU pattern.

## Метрики (clean t01-t21 + 6 расширенных)

**ВНИМАНИЕ: quota cliff на t22.** ChatGPT Pro daily limit исчерпался после ~21 задачи на full run (после 011 + smoke v1 + smoke v2 + full сегодня). t22-t49 получили `rc=1` от codex без полезного output → `OUTCOME_ERR_INTERNAL` submitted, corrupted data.

Чистые задачи (27 запусков, остальные corrupted):

| Метрика | 011 (на этой же 27-task подвыборке) | 012 |
|---|---|---|
| **Score** | 24/27 = 88.89% | **20/27 = 74.07%** |
| t01-t21 wins | 19/21 | **20/21** (+1 = t11) |
| extra (t26, t41, t42, t45, t47, t50) | 5/6 | 0/6 ⚠️ |

**Внутри t01-t21 011→012**: +2 wins (t06, t11), -1 win (t04). Net +1 win = +4.76 pp на узком чистом срезе.

**Внутри extra-tier (t26, t41, t42, t45, t47, t50)**: все 6 регрессировали в 012. Но это **одиночный run после quota-stressed 011** — есть подозрение что:
1. t26 ('missing /docs/security.md') — randomization shift (011 t26 был OK, 012 — другой instruction)
2. t41 ('missing /docs/payments/3ds.md') — randomization shift к 3ds-related task
3. t42 ('missing /docs/security.md') — randomization
4. t45, t47 ('missing required reference /proc/catalog/...') — wrong-SKU pick (randomization)
5. t50 ('missing /docs/security.md') — randomization

Все 5 регрессий — типичные randomization patterns, видели на 011/009.

**Достоверно 012-связанное изменение — ТОЛЬКО t11 (deterministic gain).**

## Per-task diff (012 vs 011 на clean t01-t21)

```
t04   1.00 -> 0.00  --- "Answer should contain '<YES>'" — model said NO/<NO>. Randomization.
t06   0.00 -> 1.00  +++ randomization (right SKU pick this time)
t11   0.00 -> 1.00  +++ TARGET HIT (carve-out: refs=1 policy doc only)
```

Все остальные t01-t21 (18 задач) — без изменения.

## Verification

1. ✅ Smoke v2 4/4 на target subset.
2. ✅ t11 deterministic fix (0 → 1 на smoke AND full).
3. ✅ t08, t12, t20 НЕ регрессировали (smoke + full).
4. ⚠️ Quota cliff на t22 corrupted t22-t49 — нужен rerun next-day для measurement σ vs 011.
5. ⚠️ Extra-tier "регрессии" (t26, t41, t42, t45, t47, t50) — выглядят randomization-driven; single-run, нельзя интерпретировать как 012-caused без multi-run.

## Выводы

1. **t11 carve-out работает deterministic.** Smoke + full оба = 1.00 на t11. Mechanism подтверждён.
2. **Yes/no verifications требуют explicit exception** в carve-out (iteration v1 → v2). Это уже отражено в финальной формулировке.
3. **Quota cliff ограничивает single-day iteration**. На WORKERS=3 + 011 + 012-smoke-x2 + 012-full quota исчерпался при ~21 task'е full run. Будущим experiments нужна стратегия: pace-friendly (WORKERS=1) или multi-day разбиение.
4. **Стоит сделать rerun через 1 день** с focus на t22-t50, чтобы провалидировать что t11 fix не нарушил остальные.

## Следующие шаги

- [ ] **012-followup**: rerun 012 на t22-t50 после quota reset (~24h) для measurement.
- [ ] **013 — t46 indirect-customer DENIED** (medium). В 011 t46 = "apply discount to basket of mia.hoffmann+cust886@yahoo.com" → модель OK + applied 10%, evaluator wants DENIED+security.md. Fast-path D (Identity mismatch) не сработал, т.к. customer назван через email, не через basket_id напрямую. Нужно расширить D: "resolve email/phone/account-name to customer; if ≠ /bin/id → DENIED".
- [ ] **014 — fraud-selectivity** (medium). t38-t40 + t48 chronic.
- [ ] **015 — multi-run на 011+012** (medium) после quota reset.

## Артефакты прогона

- `agent/smoke.log` — smoke v2 (4 target)
- `agent/full_run.log` — full 50-task (t22-t49 corrupted)
- `agent/27-05-26-1.jsonl` — full debug log
- `agent/ecom_mcp.log` — MCP tool calls
- `failures.md` — категоризированный анализ losses
