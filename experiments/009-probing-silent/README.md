# 009 — codex-probing-silent

**Дата:** 2026-05-24
**Статус:** завершён (mixed signal)
**Автор/агент:** Ivan + Claude Opus 4.7
**Бранч/коммит:** `main @ after-008 (8349d77)`
**Базлайн:** `007-codex-discount-refs` scaffolding, измеренный в `008-multi-run-eval` (mean **64.83%**, σ **3.22 pp** на 42-task бенче, n=2)
**Модель:** `gpt-5.4` через Codex CLI 0.130.0

## Гипотеза

Если в `prompts/instructions.md` переписать **Step 5 (SQL discipline → refs)** так, чтобы для "how many of these N items meet criterion C" сценариев модель сначала probed всех N через `ecom_read_silent`, а потом `ecom_read` (tracked) только qualifying subset — success rate вырастет на **+4 wins ≈ +9.5 pp**, потому что в 008 ровно 4 задачи (t13, t14, t15, t16) always-fail с одинаковой ошибкой `answer contains invalid reference '/proc/catalog/<sku>.json'`.

Это **выше 2σ-порога** из 008 (σ=3.22 pp → 2σ=6.44 pp), поэтому сигнал должен быть различим даже на single-run.

## Корень проблемы (из run1.jsonl анализа)

Все 4 always-fail задачи в категории "count of these N products with criterion C" (например t13: "How many of these 5 products have at least 3 items available in store X today?"). Tool call sequence модели на t13 (run1):

```
1) ecom_read /proc/README.md
2) ecom_exec /bin/sql (schema)
3) ecom_exec /bin/sql (find store_id)
4) ecom_exec /bin/sql (find SKUs by brand/model)
5) ecom_find / ecom_search (locate store doc)
6) ecom_read /proc/stores/store_graz_lend.json   ← tracked, correct
7) ecom_exec /bin/sql (inventory check)
8) ecom_read /proc/catalog/CLN-NOLQX7ED.json     ← tracked, BUT didn't qualify
9) ecom_read /proc/catalog/CLN-GEF2EYP9.json     ← tracked, BUT didn't qualify
10) ecom_read /proc/catalog/FST-23VT61XO.json    ← tracked, qualified
11) ecom_read /proc/catalog/FST-2JPIIG2S.json    ← tracked, qualified
12) ecom_read /proc/catalog/STO-2R84BSHQ.json    ← tracked, qualified
```

Evaluator response: `answer contains invalid reference '/proc/catalog/CLN-NOLQX7ED.json'`.

Step 5 in 007's prompt **actively instructs** the model to `ecom_read` каждого candidate: "If the task names a list of products to evaluate, call `ecom_read` on each of those product JSONs explicitly — otherwise their paths will be missing from `grounding_refs`". Это правило справедливо для "list the attributes" задач, но ломает "count meeting criterion" задачи — disqualified candidates попадают в refs, evaluator их rejects.

Раздел `## Refs discipline` (lines 143-156) уже описывает `ecom_read_silent` для "probing alternate paths during disambiguation that turn out NOT to support the final answer", но **общее правило конфликтует с конкретной директивой Step 5**, и модель следует конкретике.

## Что меняем (diff vs 007)

### 1. `prompts/instructions.md` — Step 5 (SQL discipline)

Заменяем «`ecom_read` каждого candidate» на двухфазную инструкцию:

- **`ecom_read(path)` (tracked)** — ONLY rows что contribute to final answer.
- **`ecom_read_silent(path)` (NOT tracked)** — для probing/eligibility checks.
- Worked example: "how many of these N have criterion C" → N× silent → tracked только qualifying subset.

### 2. `prompts/instructions.md` — Refs by outcome (OUTCOME_OK)

Добавлена явная строка: "NEVER include candidates you evaluated but that did NOT qualify under the task's criterion".

### 3. `codex_agent.py` — чистка OpenRouter dead code

Удалён `CODEX_PROVIDER`/`model_provider=openrouter` блок (не пошёл в production; см. session 2026-05-24).

### 4. Mechanical post-process

**Не добавляется** в 009. Mechanical "strip disqualified" requires knowing which catalog refs contributed — only the model has that info. Полагаемся на prompt adoption, который стабильно работал в 005→006→007.

## Целевые задачи и ожидание

| Task | 008 (n=2) | 009 ожидание | Механизм |
|---|---|---|---|
| t13 | 0.00 (always_fail) | **OK** | silent probe → tracked только qualifying SKUs |
| t14 | 0.00 (always_fail) | **OK** | то же |
| t15 | 0.00 (always_fail) | **OK** | то же |
| t16 | 0.00 (always_fail) | **OK** | то же |

Ожидаемый эффект: **+4 hard wins → +9.5 pp** на 42-task. Mean: 64.83% → ~74%, выше 2σ-порога.

Риск регрессии: модель может over-strip refs на других OK-задачах ("эта задача похожа на probing, не буду tracked-читать") → empty или incomplete refs → шумовая регрессия на 1-2 задачах. Степень риска средняя; снижается тем, что worked example даёт чёткий шаблон («count meeting criterion»), а другие OK-задачи имеют другую форму (lookup-by-name, transaction by ID и т.п.).

## Setup

MCP server `bitgn-ecom` перенаправлен на 009:

```bash
codex mcp remove bitgn-ecom
codex mcp add bitgn-ecom \
  --env VAULT_HARNESS_URL=https://api.bitgn.com \
  --env VAULT_MCP_LOG=/Users/ivan/Documents/ai/ecom-py/experiments/009-probing-silent/agent/ecom_mcp.log \
  -- /Users/ivan/Documents/ai/ecom-py/venv/bin/python /Users/ivan/Documents/ai/ecom-py/experiments/009-probing-silent/agent/ecom_mcp_server.py
```

## Запуск

```bash
source /Users/ivan/Documents/ai/ecom-py/venv/bin/activate
cd /Users/ivan/Documents/ai/ecom-py/experiments/009-probing-silent/agent

# Smoke на target tasks (t13-t16)
MODEL_ID=gpt-5.4 python -m main t13 t14 t15 t16

# Full run (42-task)
MODEL_ID=gpt-5.4 python -m main
# Если quota позволяет: WORKERS=3 для скорости (но cost не меняется)
```

## Smoke (t13-t16)

```bash
MODEL_ID=gpt-5.4 python -m main t13 t14 t15 t16
```

| Task | 008 (n=2) | 009 smoke | Answer | Refs (catalog) |
|---|---|---|---|---|
| t13 | 0.00 | **1.00** ✅ | `<COUNT:1>` | 1 SKU (FST-3SJKL8BF) |
| t14 | 0.00 | **1.00** ✅ | count : 2 | 2 SKUs |
| t15 | 0.00 | **1.00** ✅ | count : 3 | 3 SKUs |
| t16 | 0.00 | **1.00** ✅ | `<COUNT:1>` | 1 SKU |

Smoke **4/4 = 100% на target**. Prompt-only adoption работает на той же модели: для "how many of these N meet criterion C" задач gpt-5.4 теперь probes silent и tracks только qualifying subset. `completed_steps` явно говорит "Tracked the single qualifying product …" — рула усвоена.

## Метрики (полный 44-task прогон, WORKERS=3)

Бенч вырос ещё раз: 42 → 44 (добавились t43, t44 — оба always_fail).

| Метрика | 008 baseline (mean n=2, 42t) | 009 (single-run, 44t) | Δ |
|---|---|---|---|
| **Success rate** | 64.83% (42t) | **61.36%** (44t) | −3.47 pp (bench grew) |
| **Hard wins на 42-task overlap** | mean 27.23 / 42 | **27 / 42** = 64.29% | **−0.54 pp (в зоне шума σ=3.22)** |
| **Hits на t13-t16 (target)** | 0/4 | **4/4** ✅ | **+4 hard wins** |
| Avg input tokens / task | 211k | 226.7k | +7% |
| Avg cached input tokens / task | 177k | 193.8k | +9% |
| Avg output tokens / task | 1.88k | 2.0k | +6% |
| Avg reasoning tokens / task | 660 | 880 | +33% |
| Avg MCP tool calls / task | 11.0 | 9.8 | −11% |
| Avg elapsed / task | 52.2s | 54.8s | +5% |

`refs_sanitized_*` events: 0 (prompt adoption без срабатывания mechanical post-process — паттерн 005→006→007 продолжается).

## Per-task diff (009 vs 008 mean)

**Target hits (gains):**

```
t13   0.00 -> 1.00  +++ TARGET HIT (always_fail → pass)
t14   0.00 -> 1.00  +++ TARGET HIT
t15   0.00 -> 1.00  +++ TARGET HIT
t16   0.00 -> 1.00  +++ TARGET HIT
```

**Off-target gains (flaky win this run):**

```
t21   0.50 -> 1.00  +++ flaky won (OUTCOME_OK; vs UNSUPPORTED in run2-008)
t31   0.50 -> 1.00  +++ flaky won (OUTCOME_OK; vs DENIED_SECURITY in run1-008)
```

**Off-target regressions:**

```
t05   1.00 -> 0.00  --- model picked WRONG SKU (FST-APSRIZJW vs expected FST-2JPIIG2S). Randomization, not 009-caused
t08   1.00 -> 0.00  --- "too many invalid references" — model included 30+ Metabo grinder family SKUs as refs (probing they should have been silent). **009-rule did NOT generalize** to "verify SKU does/doesn't have attribute X"
t20   1.00 -> 0.00  --- "too many invalid references" — model dumped 49 paint family SKUs into refs for "across all Graz stores, count of product P" task. Same mechanism: probing wasn't silenced
t36   1.00 -> 0.00  --- outcome mismatch (DENIED instead of UNSUPPORTED). Unrelated to refs
t09   0.50 -> 0.00  --- flaky lost (missing required catalogue-counting doc ref)
t10   0.50 -> 0.00  --- flaky lost (missing required doc ref)
```

**Net on 42-task overlap: +4 (targets) +2 (flaky won) −4 (clean regressions) −2 (flaky lost) = 0 wins delta.** All visible 009 effect lies inside the 2σ noise floor.

## Выводы

1. **Target hypothesis подтверждена на 4/4**, но эффект ровно компенсирован off-target регрессиями и flaky колебаниями. На single-run эффект **+0 wins на overlap** (27 → 27), то есть signal/noise = 1:1. На full 44 = 61.36% (за счёт 2 новых always_fail задач t43/t44 в bench).

2. **Корневой регрессионный механизм найден** (t08, t20): прописанная в Step 5 рула работает для буквального паттерна "how many of these N items meet criterion C", но gpt-5.4 НЕ переносит её на семантически близкие задачи:
   - "Check the actual catalogue item … if extra claim is absent, answer with <NO> and include the checked SKU" (t08) — модель probed весь family ради verify, отметила всё как tracked.
   - "Across all stores, how many units of product P are available?" (t20) — модель probed sibling SKUs того же family, отметила всё как tracked.
   
   Рула слишком специфична. Нужно обобщить формулировку — например: "Any time you read MORE records than will appear in your final answer's evidence, the extras must be silent."

3. **Bench shift повторился** (42 → 44). Сравнение с прошлыми экспериментами становится всё менее надёжным; нужна disciplined per-task категоризация после каждого прогона. **t41–t44 — новая категория "missing required policy/catalogue-addenda doc"** (4 always_fail с одинаковой ошибкой). Это потенциальный target для 010.

4. **Cost-neutral (~+7% tokens, +5% elapsed)** — изменение prompt'а не повлияло на объём work'и существенно. Avg reasoning tokens +33% — модель чуть больше думает над разделением silent vs tracked, но в абсолютных числах это 220 → 880 reasoning tokens, копейки.

5. **σ-aware вывод**: эффект **+4 wins на 4 target tasks** реальный (4/4 deterministic). Шум на off-target +/- сравним с σ=3.22 pp из 008. Чтобы отличить чистый сигнал от noise, нужен multi-run (3+ повтора) — но даже без него можем сказать: **на t13-t16 fix работает**, на t08/t20 рула не сработала из-за слишком узкой формулировки.

## Следующие шаги

- [ ] **009b — generalize Step 5**: переписать рулу обобщённо ("if you read more records than your answer cites, the extras must be silent"). Цель: подхватить t08 и t20 без регрессий на target. Risk: модель станет over-silent на legitimate evidence reads.
- [ ] **010-policy-docs-refs**: t41-t44 — все four always_fail с `missing required reference '/docs/<doc>.md'`. Похоже на 007 discount-refs pattern, но для policy-updates / catalogue-addenda / ops-policy-notes. Потенциал +4 wins.
- [ ] **011-fraud-selectivity**: t38-t40 fraud forensic chaos (recall ~100%, precision ~5%). Структурная проблема, требует chain-of-thought про точные критерии fraud.
- [ ] **012-multi-run на 009**: 2 повтора 009 для measurement σ на новом 44-task bench и подтверждения, что +4 target wins воспроизводятся deterministic.

## Артефакты прогона

- `agent/24-05-26-1.jsonl` — smoke debug log (t13-t16)
- `agent/24-05-26-2.jsonl` — full 44-task debug log
- `agent/ecom_mcp.log` — MCP tool calls
- `agent/smoke.log`, `agent/full_run.log` — stdout/stderr
- `failures.md` — категоризированный анализ losses

## Следующие шаги

- [ ] 009b — если single-run +9.5 pp подтверждён, прогнать 2-3 повтора для multi-run mean (cost 2× квоты).
- [ ] **010-security-relaxation** — t31 outcome mismatch (cat C, +1 win = на границе шума, делать вместе с другим fix'ом).
- [ ] **011-fraud-selectivity** — t38/t39/t40, chain-of-thought про exact match criteria. Партиал scores сейчас 0.07-0.08, chaos category.
- [ ] **012-new-tasks-triage** — t41/t42 always_fail на новом 42-task bench. Природа неизвестна, разведать failure_detail и tool sequences.

## Артефакты прогона

(после прогона: jsonl debug log, ecom_mcp.log, failures.md)
