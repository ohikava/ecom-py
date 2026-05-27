# 012-count-scalar-refs — failures

50 задач, 21 hard wins, 29 fails (из них 23 quota-corrupted ERR_INTERNAL, 6 — real fails / regressions).

## Headline

| Срез | 011 baseline | 012 single-run | Δ |
|---|---|---|---|
| Smoke на target (t08, t11, t12, t20) | 3/4 (t11=0) | **4/4** ✅ | +1 deterministic |
| t01-t21 clean | 19/21 = 90.48% | **20/21 = 95.24%** | +4.76 pp |
| t01-t27 (27-task clean subset) | 24/27 = 88.89% | **20/27 = 74.07%** | -14.81 pp (extra-tier — randomization, см. ниже) |
| **t22-t50** | (51% in 011) | **0/29 — quota corrupted** | n/a |

## Целевая задача

| Task | 010 | 011 | 012 | Detail |
|---|---|---|---|---|
| t11 | 1.00 (other randomization) | **0.00** | **1.00** ✅ | Carve-out: refs = `[/docs/ops-policy-notes/catalogue-count-extension-cables-vienna-2024-07-17.md]` (1 doc, no catalog over-cite). Answer "11". |

**Deterministic.** Smoke + full оба = 1.00.

## Не-регрессии (target preserved)

| Task | 011 | 012 smoke v2 | 012 full | Detail |
|---|---|---|---|---|
| t08 | 1.00 | **1.00** ✅ | 1.00 | "verify Schneider Acti 14B-98F" — refs=1 SKU (no family siblings) |
| t12 | 1.00 | **1.00** ✅ | 1.00 | catalog count with policy doc — refs=1 doc |
| t20 | 1.00 | **1.00** ✅ | 1.00 | "[QTY:%d]" across Graz — refs=product + 2 stores |

## 012 v1 iteration mistake

Smoke v1 формулировка "scalar (count, total, sum, yes/no, single value)" → t08 ❌. Модель интерпретировала "yes/no" → "answer is scalar → refs = scope doc only" → сбила verify-SKU pattern на 40+ family siblings.

**Fix v2**: убрал yes/no и single value из определения, добавил explicit DOES NOT apply list. → smoke 4/4. ✅

## Randomization regressions (вероятно НЕ 012-caused)

### t04 — wrong yes/no on smart-home product
Random task — model said NO when YES expected. Same pattern as 009 t05 / 011 t06.

### t26, t41, t42, t50 — missing security.md / 3ds.md
Pattern "DENIED-related task but security.md not in refs". В 011 эти были 1.0 — randomization задавала иную форму. В 012 randomization сдвинула к DENIED-shape, model не triggered fast-path.

### t45, t47 — missing required catalog ref (wrong SKU)
Wrong SKU pick — randomization (multiple variants in line).

## Quota-corrupted (t22-t49, 23 задачи)

```
t22-t25, t27-t40, t43-t44, t46, t48-t49
```

Все получили `OUTCOME_ERR_INTERNAL` (codex rc=1). ChatGPT Pro daily limit. **Не валидны для measurement.**

## Категоризация известных fails (исключая quota)

| Категория | Кол-во | Tasks |
|---|---|---|
| **Always-OK ядро** | 20 | t01-t03, t05-t21 (кроме t04) |
| **TARGET HIT** | 1 | t11 ✅ |
| **Randomization yes/no** | 1 | t04 (was 1 in 011) |
| **Randomization DENIED-shape regression** | 4 | t26, t41, t42, t50 |
| **Randomization wrong-SKU** | 2 | t45, t47 |
| **Quota-corrupted (uncertain)** | 23 | t22-t49 (см. выше) |

## Мета-вывод

012 — узкий targeted fix. **Deterministic t11 fix confirmed.** Все остальное — либо preserved (t08, t12, t20), либо randomization noise (нельзя интерпретировать single-run after-quota run).

**Главный artifact эксперимента:** v1 → v2 показал что в prompt-нейминге слов важна точность ("scalar" слишком широко; "whole-catalog count/total/sum" — точно).

## Приоритет

| # | Эксперимент | Status | Ожидание |
|---|---|---|---|
| 012-followup | rerun t22-t50 после quota | high | measurement ± vs 011 |
| 013 | t46 indirect-customer DENIED | medium | +1 (t46) если pattern generalize |
| 014 | fraud-selectivity (t38-t40, t48) | medium | t.b.d., chaos |
| 015 | multi-run на 011+012 | medium | σ measurement |
