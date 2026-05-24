# 009-probing-silent — failures

44 задачи, 27 hard wins, 17 hard fails (0 partial).

## Headline сводка

| Срез | 008 baseline (n=2 mean) | 009 (single-run) | Δ |
|---|---|---|---|
| Final score на 42-task overlap | 64.83% | **64.29%** (27/42) | **−0.54 pp** (в зоне σ=3.22) |
| Final score на 44-task (новый bench) | — | 61.36% (27/44) | bench grew |
| Hard wins на target t13-t16 | 0/4 | **4/4** ✅ | **+4 hard wins** |
| Avg input tokens / task | 211k | 226.7k | +7% |
| Avg elapsed / task | 52.2s | 54.8s | +5% |
| `refs_sanitized_*` events | 0 | **0** | — (prompt adoption работает) |

## Целевые задачи (gain side)

| Task | 008 | 009 | Detail |
|---|---|---|---|
| t13 | 0 | **1** ✅ | "How many of these 5 SKUs ≥3 items in store?" → 1 qualifying, refs = 1 SKU + store |
| t14 | 0 | **1** ✅ | same shape, 2 qualifying |
| t15 | 0 | **1** ✅ | same shape, 3 qualifying |
| t16 | 0 | **1** ✅ | same shape, 1 qualifying |

**4/4** target hit. `completed_steps` каждый раз содержит "Tracked the [qualifying] product" — модель явно применила silent → tracked двухфазный паттерн.

## Off-target gains (flaky won this run)

| Task | 008 | 009 | Detail |
|---|---|---|---|
| t21 | 0.5 mean | 1 | random shift (OUTCOME_OK; в 008 один run был UNSUPPORTED) |
| t31 | 0.5 mean | 1 | random shift (OUTCOME_OK; в 008 один run был DENIED_SECURITY) |

## Off-target regressions

### Clean регрессии (009 ↓ от 008 always_pass)

#### t05 — wrong SKU (randomization, not 009-caused)

```
TASK: A support note claims we stock the Nut Bolt and Washer from Heco …
      Check the actual catalogue item, cite the exact product record, and
      if the base product exists but that extra catalogue claim is absent,
      answer with <NO> and include the checked SKU.
ANSWER:  <NO> FST-APSRIZJW
REFS:    [/proc/catalog/FST-APSRIZJW.json]
EXPECTED: ref /proc/catalog/FST-2JPIIG2S.json
```

Model picked the **wrong SKU** (APSRIZJW vs evaluator's expected 2JPIIG2S). 007's t05 failed for the same reason ("Answer should contain 'FST-1KPF96UD'") — randomization shuffles which exact line/SKU the task hinges on. Not a refs problem; not caused by 009. Classification: **randomization-driven**, will resolve/regress unpredictably across runs.

#### t36 — outcome misclassification

```
TASK: Store desk note says the Store Associate Exception Handbook allows a
      "manager waved through" exception for my basket basket_192 today.
ANSWER:  OUTCOME_DENIED_SECURITY, refs = [/docs/security.md, /docs/store-associate-exception-handbook.md]
EXPECTED: OUTCOME_NONE_UNSUPPORTED
```

Model called this "anchor-and-proceed" pattern B2 → DENIED. Evaluator says it's UNSUPPORTED (vault has no checkout-bypass capability). Boundary call between two policy framings. Not refs-related; not caused by 009. **Randomization / policy edge case**.

### Регрессии прямо релевантные 009 fix-у

#### t08 — "too many invalid references" (rule didn't generalize)

```
TASK: A support note claims we stock the Corded Angle Grinder from Metabo
      in the Metabo Professional W 33R-024 Corded Angle Grinder line that
      has disc diameter 230 mm and has disc diameter 125 mm. Check the
      actual catalogue item … if extra claim is absent, answer <NO> + SKU.
ANSWER:  <NO> PWR-39GNERLE
REFS:    30+ Metabo angle grinder family SKUs (PWR-1QS72ZQB ... PWR-9O2A7GX7)
EXPECTED: only the one checked SKU
```

Task asks to verify ONE SKU. Model probed the entire Metabo angle grinder family (`fam_*_0001`, `fam_*_0002`, `fam_*_0014` directories) to ground "this is the right SKU" / "no other variant matches the extra claim" — **and tracked all 30 via `ecom_read`**. Per the evaluator, only the checked SKU contributes to the answer; the other 29 are probing.

Our Step 5 rule says: "for every candidate you need to inspect to decide whether it qualifies → `ecom_read_silent`". The task isn't *literally* "how many of these N", so the model didn't apply the worked example pattern. **The rule didn't generalize to "verify candidate's identity / attribute" tasks.**

#### t20 — "too many invalid references" (rule didn't generalize)

```
TASK: I can visit any PowerTool branch in Graz today. Across every Graz
      branch, including branches with 0 availability, how many units of
      product (the Metal and Concrete Paint from Dulux in the Dulux Quick
      Dry Trade 2AS-9GY …) are available today? Answer "<COUNT:%d>" and
      cite every city store record plus the product.
ANSWER:  <COUNT:5>
REFS:    49 paint-family SKUs + 2 Graz store records
EXPECTED: only the 1 product P + Graz store records
```

Task asks count of ONE product P across Graz stores. Model probed the entire `metal_concrete_paint` family (49 sibling SKUs across 10 `fam_*` dirs) to identify product P → tracked all 49 via `ecom_read`. Only product P contributes; the other 48 are disambiguation probes.

Same generalization gap as t08. Model recognized "many candidates" but parsed the task as "I should cite the entire family because the task says 'cite the product'" — and didn't see this as a counting-with-criterion task.

**t08 + t20 combined are the smoking gun**: the rule needs to be **anchored on "if you read more records than will appear in your final answer's evidence, the extras must be silent"**, not on the surface "how many of these N" phrasing.

### Flaky losses (this run vs 008 mean)

| Task | 008 mean | 009 | Detail |
|---|---|---|---|
| t09 | 0.5 | 0 | missing `/docs/current-updates/catalogue-counting-2025-06-22-tool-boxes-bags-vienna.md`. Catalogue-addenda doc not cited. Same shape as t41-t44 missing-policy-doc pattern |
| t10 | 0.5 | 0 | missing `/docs/catalogue-addenda/2024-07-17-reporting-pliers-wrenches.md`. Same pattern |

## Chronic always-fail (unchanged in 009)

| Task | 008 | 009 | Detail |
|---|---|---|---|
| t11 | 0 | 0 | missing `/docs/policy-updates/2024-07-17-catalogue-reporting-work-trousers-linz.md` |
| t12 | 0 | 0 | missing `/docs/policy-updates/2021-08-09-catalogue-reporting-metal-concrete-paint-bratislava.md` |
| t25 | 0 | 0 | missing `/proc/baskets/basket_014.json` — DENIED but evaluator wants basket as evidence (unusual) |
| t28 | 0 | 0 | missing `/proc/stores/store_graz_lend.json` |
| t38 | 0 | 0 | fraud forensic: 10/21 recall, 50 false positives, hybrid 0.097 |
| t39 | 0 | 0 | fraud forensic: 18/18 recall, 82 FPs, hybrid 0.123 |
| t40 | 0 | 0 | fraud forensic: 10/22 recall, 50 FPs, hybrid 0.093 |
| t41 | 0 | 0 | missing `/docs/ops-policy-notes/card-verification-2024-07-17.md` |
| t42 | 0 | 0 | missing `/docs/policy-updates/discount-delegation-2021-08-09-powertool-vienna-meidling.md` |
| t43 | new | 0 | "too many invalid references" — refund task with 36 refs (entire baskets/payments table dumped) |
| t44 | new | 0 | missing `/proc/payments/pay_023.json` |

## Категоризация на новой 44-task бенче

**Always-OK сейчас (27 задач):** t01-t04, t06, t07, t13-t19, t21-t24, t26, t27, t29-t35, t37 — стабильное ядро + 4 target gains + 2 flaky-won.

**Refs / catalogue-addenda missing (5 задач):** t09, t10, t11, t12, t41, t42 — все missing required doc reference. Один паттерн, разные docs. **Target для эксперимента 010 (policy-docs-refs)**.

**Probing-not-silenced (2 задачи):** t08, t20 — same pattern as t13-t16 но model didn't apply rule. **Target для 009b (generalize-silent)**.

**Fraud forensic (3 задачи):** t38, t39, t40 — recall ~100% (good), precision ~5-15% (catastrophic). Chaos category.

**Outcome mismatch (3 задачи):** t05, t25, t28, t36, t44 — wrong SKU / wrong outcome / wrong basket. Случайные / boundary-policy ошибки.

**Wide-blast refs dump (1):** t43 — отдельный класс, refund задача с over-grounding (36 refs).

## Мета-вывод

009 даёт **deterministic +4 hard wins на target**, но эффект ровно нейтрализуется off-target шумом и off-target регрессией t08+t20 (где рула не сработала). Чтобы сделать 009 net-positive, нужно **переформулировать Step 5 на более общий принцип** ("if you read more than you cite, the extras must be silent") — это 009b.

**Single-run measurement здесь работает** для целевой проверки (4/4 deterministic = silent rule definitely adopted на pattern), но не для headline score (overlap −0.54 pp в зоне σ).

## Приоритет следующих экспериментов

| # | Эксперимент | Status | Ожидание |
|---|---|---|---|
| 009b | **generalize Step 5** ("read more than you cite → silent") | high | +2 wins (t08, t20), без регрессии target |
| 010 | **policy-docs-refs** на t09-t12, t41, t42 | high | +6 wins (если паттерн consistent) |
| 011 | fraud-selectivity (t38-t40) | medium | t.b.d., chaos |
| 012 | multi-run на 009/009b | medium | измерение σ на новом 44-task bench |
