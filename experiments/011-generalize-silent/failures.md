# 011-generalize-silent — failures

50 задач, 35 hard wins, 12 hard fails, 3 partial (t38/t39/t40).

## Headline

| Срез | 010 baseline | 011 single-run | Δ |
|---|---|---|---|
| 40-task overlap (clean) | 78.55% (31.42/40) | **83.28%** (33.31/40) | **+4.73 pp** ✅ |
| 44-task overlap | 71.40% (31.42/44) contaminated | **80.25%** (35.31/44) | +8.85 pp |
| 50-task new bench | — | **76.63%** (38.31/50) | new |

## Целевые задачи (target)

| Task | 010 | 011 | Detail |
|---|---|---|---|
| t08 | 0 | **1** ✅ | "verify Schneider socket has 6A" — refs = 1 SKU only, no family siblings |
| t12 | 0 | **1** ✅ | "count anchors_plugs ex held family" — refs = 1 ops-policy-note only |
| t20 | 0 | **1** ✅ | "[QTY:%d] Hager product across Graz" — refs = product + 2 stores |

3/3 deterministic. Universal silent-rule adopted.

## 010 follow-up confirmed (был quota-corrupted)

| Task | 010 raw | 011 | Detail |
|---|---|---|---|
| t41 | quota-corrupted | **1** ✅ | ops-policy-note cited (smoke предсказал) |
| t42 | quota-corrupted | **1** ✅ | refs + outcome OK на этой randomization |

## 011-caused regression

### t11 — count-aggregate "evidence ≡ answer objects" over-correction

```
TASK: For the catalogue count report, how many products are Workshop Saw and Cutter?
      Answer in exactly format "[QTY:%d]" (no quotes).
ANSWER: [QTY:16]
REFS (19): policy doc /docs/policy-updates/2024-07-17-catalogue-reporting-saws-cutters-vienna.md
        + 18 catalog files /proc/catalog/workshop_machines/saws_cutters/MAC-*.json
SCORE: 0.0 ("too many invalid references")
EXPECTED: refs = policy doc only (010 для аналогичного t11 = "valves and connectors" дал refs=[1] и score=1.0)
```

**Mechanism:** Новый universal-principle "evidence ≡ answer objects" + "track only the qualifying subset {q_i}" привёл модель к выводу: "answer is 16, the 18 records I counted ARE the qualifying subset → cite them". Старая формулировка ("how many of these N items") не задействовалась, потому что задача не назвала N кандидатов поimенно.

**Fix (целевой для 012):** carve-out для scalar count answers:
> Для aggregate / count answers, где `message` = scalar number (no enumeration), `grounding_refs` = scope/policy doc only. Per-record probes должны быть SQL `COUNT(*)` или `ecom_read_silent`. Worked example: "how many X are in catalog?" → `SELECT COUNT(*) FROM products WHERE kind=X` + read scope policy doc tracked → answer "16", refs=[policy_doc]. NEVER tracked-read individual records.

## Randomization regressions (NOT 011-caused)

### t06 — wrong SKU pick

```
TASK: Schneider Electric Heavy Duty Merten 214-ZHY Extension Cable, color gray + length 3m.
      Check the actual catalogue item, cite the exact product record.
ANSWER: <NO> ELC-1ECVU00O (но evaluator ждал /proc/catalog/Schneider Electric/ELC-7KIXITA4.json)
```

Same pattern as 009's t05. Multiple variants in line; randomization picks which is the canonical reference. Not refs problem.

## Outcome flap / persistent

| Task | 010 | 011 | Detail |
|---|---|---|---|
| t25 | 0 | 0 | "missing /proc/baskets/basket_014.json" (DENIED-pattern, evaluator wants basket as evidence — unusual) |
| t28 | 0 | 0 | "missing /proc/stores/store_graz_lend.json" (randomization) |

## t38-t40 fraud forensic — chaos

| Task | 010 | 011 | Detail |
|---|---|---|---|
| t38 | 0.42 | 0.23 | Recall ~32% EUR, "more than 10 FPs". Worse precision than 010 |
| t39 | 0.00 | 0.03 | Recall ~28%, ">50 FPs". Catastrophic FP, slightly better than 010's 18/18+182FP |
| t40 | 0.00 | 0.05 | Recall ~24%, ">25 FPs". Slightly improved on 0% recall |

**Pattern**: модель находит cluster cust_*/date burst, но не знает критерия "fraud" по бенчмарку. Над-включает baseline payments (pay_001..080) в refs. 011's silent-rule **не помог** — модель верит что эти baseline records ARE evidence about fraud pattern. Нужен либо `/docs/payments/3ds.md` deep dive в подсказку, либо явная семантика fraud классификации.

## Новые задачи (bench grew 44 → 50)

### Wins (3): t47, t49, t50 — clean pass.

### Fails (5):

#### t43 — "too many invalid references"
[fraud-similar over-cite, ref count неизвестен]

#### t44 — "missing required reference '/proc/payments/pay_013.json'"
Payment ref пропущен.

#### t45 — "invalid reference /proc/catalog/cleaning/.../CLN-3GV3TCEZ.json"
Цитирована чужая категория cleaning при ответе про другой scope. Похоже на disambiguation/over-cite.

#### t46 — "missing required reference '/docs/security.md'"
DENIED outcome без security.md. Похоже на новый attack-pattern, который не triggered fast-path A-E.

#### t48 — fraud-task, 0% recall

## Категоризация на 50-task

| Категория | Кол-во | Tasks |
|---|---|---|
| **Always-OK ядро** | 33 | t01-t05, t07, t09, t10, t13-t24, t26, t27, t29-t37, t41, t42, t47, t49, t50 + t08, t12, t20 (NEW IN 011) |
| **011-induced regression** (count-aggregate scalar) | 1 | t11 → target для 012 |
| **Randomization SKU-pick** | 1 | t06 (random which variant is canonical) |
| **Outcome flap / randomization** | 2 | t25, t28 |
| **Fraud forensic chaos** | 4 | t38-t40, t48 |
| **New bench fails (mixed)** | 4 | t43, t44, t45, t46 |

## Мета-вывод

011 хорошо adapted на single-record verify и count-with-criterion (3 deterministic target wins), но over-correction на count-aggregate scalar (t11). Net на 40t = +4.73 pp.

**Главные паттерны накопленных failures (для 012+):**
1. **Count-aggregate scalar over-cite** (t11) → 012 carve-out.
2. **DENIED-without-security.md** (t46) → проверить fast-path coverage.
3. **Fraud-forensic recall+precision** (t38-t40, t48) → отдельная категория, нужен либо domain knowledge boost, либо SQL discipline специфическая для платежей.
4. **Randomization SKU-pick** (t06) → не lecitable через prompt, нужно understand evaluator's canonical-SKU heuristic.

## Приоритет следующих экспериментов

| # | Эксперимент | Status | Ожидание |
|---|---|---|---|
| 012 | **count-aggregate refs carve-out** | high | +1 (t11), возможно +1 (t43 если count-related) |
| 013 | t46 DENIED-без-security расследование | medium | +1 (t46) если pattern fast-path |
| 014 | fraud-selectivity (t38-t40, t48) | medium | t.b.d., chaos |
| 015 | multi-run sanity на 011 | medium | σ на новом 50-task bench |
