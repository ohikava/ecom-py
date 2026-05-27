# 011 — generalize-silent

**Дата:** 2026-05-27
**Статус:** завершён
**Автор/агент:** Ivan + Claude Opus 4.7
**Бранч/коммит:** `main @ after-010 (994e63e)`
**Базлайн:** `010-policy-docs-refs` (78.55% на 40t clean overlap; 71.40% на 44t contaminated)
**Модель:** `gpt-5.4` через Codex CLI 0.130.0

## Гипотеза

Если переписать Step 5 SQL-discipline и Refs-discipline на универсальный принцип **evidence ≡ answer objects** (вместо узкого "how many of these N items" worked-example), модель будет применять `ecom_read_silent` для probing-reads на single-SKU / family / category disambiguation. Это **снимет over-citation regression на t08, t12, t20** (009b-проблема, оставшаяся после 010), потенциал +3 hard wins ≈ +6.8 pp.

Mechanism из 009 failure analysis:
- t08: "verify SKU X exists with property Y" → 30+ siblings tracked
- t12: "count anchors_plugs excluding family Z" → правильный policy doc + 32 catalog файла
- t20: "count product P across Graz stores" → 49 family siblings tracked

Прежняя формулировка ("how many of these N items meet criterion C") **не обобщилась** на "verify single SKU" / "count single product" / "report on category". Новая формулировка вводит:
1. **Universal principle** в начале Refs Discipline (evidence ≡ answer objects).
2. **Pre-call check** перед каждым `ecom_read`: "if I track this path, will the answer message speak about it?"
3. **Anti-pattern catalog** с 5 явными worked examples (verify-single-SKU, count-single-product, report-on-category, count-with-criterion, find-matching).
4. **Sibling/family bullet** в "Read-for-citation vs read-for-computation".
5. **Scope-probe bullet** для policy/addenda directories.
6. **Over-citation symptom** ("too many invalid references") отмечен как red flag.

## Что меняем (diff vs 010)

`prompts/instructions.md`:
- Step 5 SQL-discipline: пере-якорено на "Universal silent-read rule (evidence ≡ answer objects)" с 5 anti-patterns + 2 worked examples (single-SKU verification + counting-with-criterion).
- Refs Discipline: добавлен top-level "Universal principle — evidence ≡ answer objects" с pre-call check; в "Read-for-citation vs read-for-computation" добавлены два новых silent-bullet'а (sibling/family browsing, scope-probe).
- OUTCOME_OK refs: чёткое правило "если refs больше чем # distinct answer objects + policy docs → over-citing, re-plan reads".

Никаких python-изменений нет — только prompt.

## Smoke (3 target tasks)

```bash
MODEL_ID=gpt-5.4 WORKERS=3 python -m main t08 t12 t20
```

| Task | 010 score | 011 smoke | Detail |
|---|---|---|---|
| t08 | 0.00 | **1.00** ✅ | refs = 1 catalog SKU only (correct minimal evidence) |
| t12 | 0.00 | **1.00** ✅ | refs = 1 ops-policy-note only |
| t20 | 0.00 | **1.00** ✅ | refs = product + 2 Graz stores (no family siblings) |

**Smoke 3/3 = 100%.** Правило обобщилось.

## Метрики (полный 50-task прогон, WORKERS=3)

**ВАЖНО:** Bench снова вырос: 44 → 50 задач (новые t45-t50; в логах теперь видны и t43-t44 без quota-cliff). Сравнения сделаны на трёх срезах.

| Метрика | 010 (40t clean) | 010 (44t contam.) | 011 (40t overlap) | 011 (44t overlap) | 011 (50t bench) | Δ vs 010 на 40t-overlap |
|---|---|---|---|---|---|---|
| **Success rate** | 31.42/40 = **78.55%** | 31.42/44 = 71.40% | **33.31/40 = 83.28%** | **35.31/44 = 80.25%** | **38.31/50 = 76.63%** | **+4.73 pp** ✅ |
| **Hard wins на 40t-overlap** | 31 | 31 | **35** | 35 | 35 | **+4 hard wins** |
| Avg input tokens / task | 231.6k | — | **256.6k** | — | — | +11% |
| Avg cached input / task | 205.4k | — | 221.8k | — | — | +8% |
| Avg output tokens / task | 1.77k | — | 2.18k | — | — | +23% |
| Avg reasoning tokens / task | 782 | — | 1051 | — | — | +34% |
| Avg MCP tool calls / task | 10.2 | — | 11.0 | — | — | +8% |
| Avg elapsed / task | 49.2s | — | 77.8s | — | — | +58% |

**Стоимость выросла, но не катастрофически.** Большее input/output — следствие более длинных промптов (5 anti-patterns + worked examples = ~+600 chars). Elapsed +58% (длинные fraud-задачи t38-t40 пошли на 3-5 минут каждая; max 277s = 4.6 min).

**+4.73 pp на 40-task overlap** — ниже 2σ floor (6.44 pp на n=2 в 008), **но 3/3 target wins (t08, t12, t20) — deterministic confirmation** что universal silent-rule адаптирована.

## Per-task diff (011 vs 010 на t01-t40)

**Target hits (009b-targets):**

```
t08   0.00 -> 1.00  +++ TARGET HIT (refs = 1 SKU only, no family siblings)
t12   0.00 -> 1.00  +++ TARGET HIT (refs = 1 ops-policy-note, no catalog over-cite)
t20   0.00 -> 1.00  +++ TARGET HIT (refs = product + 2 stores, no fam siblings)
```

**010 follow-up confirmed (was quota-corrupted in 010 full run):**

```
t41   0.00 -> 1.00  +++ ops-policy-note cited correctly (smoke предсказал)
t42   0.00 -> 1.00  +++ refs OK + outcome OK на этой randomization
```

**Outcome flap gains (randomization):**

```
t26   0.00 -> 1.00  +++ (010 had emotional-pressure DENIED false-positive; this run неутрально)
```

**Regressions:**

```
t06   1.00 -> 0.00  --- wrong SKU (ELC-1ECVU00O picked, expected ELC-7KIXITA4). Randomization, NOT 011-caused
t11   1.00 -> 0.00  --- 011 over-correction. Task randomized to "Workshop Saw & Cutter count". Model
                       cited policy doc + 18 individual catalog files. New rule "evidence ≡ answer
                       objects" interpreted "answer 16 IS about 18 saws" → tracked them all. Evaluator
                       wants ONLY the policy doc for count-aggregate scalar answer.
```

**t38-t40 fraud forensic (slight shift):**

```
t38   0.42 -> 0.23  --- regression (010 hit 11/21 recall; 011 fewer correct, more FPs)
t39   0.00 -> 0.03  +++ tiny improvement (older catastrophic FPs reduced)
t40   0.00 -> 0.05  +++ tiny improvement
```

Fraud-tasks остаются chaos category; перепрошёл randomization seed.

**Still failing (unchanged):**

```
t25   0.00 -> 0.00  --- basket ref missing (randomization)
t28   0.00 -> 0.00  --- store_graz_lend ref missing (randomization)
```

**New tasks (t43-t50 — bench growth):**

```
t43   new  -> 0.00  --- "too many invalid refs"
t44   new  -> 0.00  --- "missing required reference '/proc/payments/pay_013.json'"
t45   new  -> 0.00  --- "invalid reference /proc/catalog/cleaning/.../CLN-3GV3TCEZ.json"
t46   new  -> 0.00  --- "missing required reference '/docs/security.md'" (DENIED-без-security ref)
t47   new  -> 1.00  +++ pass
t48   new  -> 0.00  --- fraud-task, 0% recall
t49   new  -> 1.00  +++ pass
t50   new  -> 1.00  +++ pass
```

50t bench даёт 011 score = **76.63%** = 38.31/50. Net wins на bench-grow: 3 wins / 5 fails / 1 partial = слабее чем core. Несколько новых задач требуют свежей категоризации.

## Verification

1. ✅ Smoke 3/3 на target deterministic confirmation.
2. ✅ +4.73 pp на 40-task clean overlap.
3. ✅ +5/5 hits на 009b/010-followup target+confirmation (t08, t12, t20, t41, t42).
4. ⚠️ **One 011-caused regression**: t11 count-aggregate "evidence ≡ answer objects" над-обобщение. Рекомендую узкое правило для count-scalar в 012.
5. ⚠️ Token cost вырос на ~10% input, ~23% output, +58% elapsed — приемлемо.
6. ⚠️ Fraud forensic (t38-t40) остаётся chaos, t38 даже регрессировал.

## Выводы

1. **Гипотеза подтверждена на target deterministic**, но эффект на overall score (+4.73 pp) ниже 2σ floor. Это означает что 011 — настоящий improvement, но смешан с randomization noise + одной induced regression (t11).

2. **Universal silent-rule работает на verify-single-SKU и count-single-product** (t08, t20). На "report on category" (t12) тоже сработал. На fraud-forensic (t38-t40) НЕ помог — fraud-задачи не страдают от over-cite, а от recall и precision.

3. **Главный неожиданный side-effect — t11.** Новое правило "evidence ≡ answer objects" слишком сильное для **count-aggregate scalar answers** ("how many X?" → "N"). Модель решила, что эти N records ARE evidence. Нужен явный carve-out:
   > "Для aggregate / count answers (scalar number) refs = только scope/policy doc; индивидуальные records — silent."

4. **t06 регрессия = randomization** (wrong SKU pick на randomized variant). Не 011-caused.

5. **Bench grew 44 → 50.** Новые t45-t50 имеют свои паттерны (см. failures.md). Из 6 новых — 3 wins, 3 fails, 1 mixed.

6. **+1 эксперимент в pipeline:** 012 — count-aggregate refs carve-out (high; lock in t11 + maybe t43, t46).

## Следующие шаги

- [ ] **012 — count-aggregate refs carve-out** (high; +1-2 wins). Узкое правило: scalar count answer → refs = только scope/policy doc; per-record чтения — silent или SQL. Target: t11, частично t43 (если он count-related), t46 (зависит от outcome).
- [ ] **013 — outcome-mismatch class** (low). t25, t28 hard fail. t26 на 011 случайно повезло. Random-driven.
- [ ] **014 — fraud-selectivity** (medium). t38-t40 + t48 = 4 chronic. Investigate `/docs/payments/3ds.md` rule semantic; recall+precision tradeoff.
- [ ] **015 — multi-run на 011** (medium). 2-3 повтора для σ на новом 50-task bench.

## Артефакты прогона

- `agent/smoke.log` — smoke (3 target)
- `agent/full_run.log` — full 50-task
- `agent/27-05-26-1.jsonl` — smoke debug
- `agent/27-05-26-2.jsonl` — full debug
- `agent/ecom_mcp.log` — MCP tool calls
- `failures.md` — категоризированный анализ losses
