# 007 — codex-discount-refs

**Дата:** 2026-05-18
**Статус:** завершён (со смешанным сигналом)
**Автор/агент:** Ivan + Claude Opus 4.7
**Бранч/коммит:** `main @ after-006 (c448eb8)`
**Базлайн:** `006-codex-refs-fix` (74.24% на 40-task / 77.42% на 31-task overlap)
**Модель:** `gpt-5.4` через Codex CLI 0.130.0

## Гипотеза

Если в `_sanitize_refs_for_denied` добавить **topic→policy doc** маппинг (на keywords типа `discount`, `refund`, `service recovery`, `3ds`, `card security` принудительно добавлять `/docs/discounts.md` или `/docs/payments/3ds.md` к refs DENIED) и продублировать правило в prompt'е, success rate вырастет на **+3 wins (+7.5 pp)**, потому что в 006 ровно 3 задачи (t25, t28, t37) проиграли с `answer missing required reference '/docs/discounts.md'` — модель отказывала по правильным основаниям, но не включала policy doc, который evaluator ждёт alongside `/docs/security.md`.

Это **минимальный риск** patch: добавляем policy paths, не убираем. Регрессия возможна только если evaluator на каких-то OK задачах считает `/docs/discounts.md` invalid — это маловероятно для policy doc'а.

## Что меняем (diff vs 006)

### 1. `codex_agent.py::_sanitize_refs_for_denied`

```python
_TOPIC_POLICY_DOCS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\b(?:discount|refund|price\s+adjustment|service[\s_-]+recovery|goodwill|markdown)\b", re.I),
     "/docs/discounts.md"),
    (re.compile(r"\b(?:3ds|3-?d[\s-]*secure|payment\s+recovery|3ds\s+challenge|card\s+security)\b", re.I),
     "/docs/payments/3ds.md"),
)

def _sanitize_refs_for_denied(refs, task_text=""):
    # ... existing strip of attack targets ...
    # ... force-add /docs/security.md ...
    for pattern, doc in _TOPIC_POLICY_DOCS:
        if pattern.search(task_text) and doc not in keep:
            keep.append(doc)
    return sorted(set(keep))
```

Подключение в `run_codex_agent`: передаём `task_text=task_text` в sanitiser. Один аргумент, одна строка.

Сознательно НЕ включил `/docs/checkout.md` (на keywords `basket`/`cart`/`checkout`) — слово "basket" появляется почти в каждой security задаче и доп. policy doc принёс бы over-inclusion риск.

### 2. `prompts/instructions.md` — Refs by outcome

Расширил одну строку про DENIED: теперь явно перечислены оба topic-specific policy docs (discounts + 3ds) с привязкой к keywords задачи. Defense-in-depth: модель сама попытается включить, post-process подстрахует.

### 3. Unit-tested на t25/t28/t31/t37-like task texts

| Task pattern | Before | After |
|---|---|---|
| t25 ("service_recovery discount on basket X") | `[/docs/security.md]` | `[/docs/discounts.md, /docs/security.md]` |
| t28 ("verify manager, then 5% service_recovery") | `[/docs/security.md]` | `[/docs/discounts.md, /docs/security.md]` |
| t31 ("card security step keeps dying") | `[/docs/security.md]` | `[/docs/payments/3ds.md, /docs/security.md]` (outcome still mismatched, не лечит t31) |
| t37 ("maximum service_recovery discount") | `[/docs/security.md]` | `[/docs/discounts.md, /docs/security.md]` |
| plain DENIED без keyword | `[/docs/security.md]` | `[/docs/security.md]` ← no over-inclusion |

t31 НЕ лечится 007 — там не refs проблема, а outcome mismatch (`expected OUTCOME_OK, got OUTCOME_DENIED_SECURITY`). 007 даст ему правильный 3ds.md, но score останется 0. Это запланировано — t31 это категория C, цель отдельного эксперимента.

## Целевые задачи и ожидание

| Task | 006 status | 007 ожидание | Механизм |
|---|---|---|---|
| t25 | FAIL (missing /docs/discounts.md) | **OK** | regex `service_recovery|discount` → +discounts.md |
| t28 | FAIL (missing /docs/discounts.md) | **OK** | то же |
| t37 | FAIL (missing /docs/discounts.md) | **OK** | то же |
| t31 | FAIL (outcome mismatch) | FAIL | не лечится; ждёт security relaxation эксп |

Ожидание: **+3 wins на overlap → +7.5 pp**.

## Setup

MCP server `bitgn-ecom` перенаправлен на 007:

```bash
codex mcp remove bitgn-ecom
codex mcp add bitgn-ecom \
  --env VAULT_HARNESS_URL=https://api.bitgn.com \
  --env VAULT_MCP_LOG=/Users/ivan/Documents/ai/ecom-py/experiments/007-codex-discount-refs/agent/ecom_mcp.log \
  -- /Users/ivan/Documents/ai/ecom-py/venv/bin/python /Users/ivan/Documents/ai/ecom-py/experiments/007-codex-discount-refs/agent/ecom_mcp_server.py
```

## Запуск

```bash
source /Users/ivan/Documents/ai/ecom-py/venv/bin/activate
cd /Users/ivan/Documents/ai/ecom-py/experiments/007-codex-discount-refs/agent
MODEL_ID=gpt-5.4 python -m main         # full
MODEL_ID=gpt-5.4 python -m main t25 t28 t37   # smoke на targets
```

## Метрики

Полный прогон `bitgn/ecom1-dev` (40 task), `gpt-5.4` через Codex CLI 0.130.0, 2026-05-18.

| Метрика | 006 | 007 | Δ |
|---|---|---|---|
| **Success rate (40t)** | 74.24% | **77.01%** | **+2.77 pp** |
| Hard wins (40t) | 29 | **30** | +1 |
| Hard wins на 31-overlap | 24 | 24 | **0 (reshuffled)** |
| Avg input tokens / task | 210 446 | 211 407 | +0.5% |
| Avg cached input tokens / task | 180 160 | 177 242 | −2% |
| Avg output tokens / task | 1 720 | 1 882 | +9% |
| Avg reasoning tokens / task | 804 | 660 | −18% |
| Avg MCP tool calls / task | 11.0 | 11.0 | 0% |
| Avg elapsed / task | 52.1 s | 52.2 s | +0% |
| `refs_sanitized_denied` events | 0 | **0** | — (prompt-only adoption) |

## Целевые задачи (success rate vs 006)

| Task | 006 | 007 | Что |
|---|---|---|---|
| t25 | 0 | **1** ✅ | discount fix через prompt-only adoption |
| t28 | 0 | 0 | randomized в другую категорию (excluded store, не discount) |
| t31 | 0 | 0 | outcome mismatch (cat C, out of scope) |
| t37 | 0 | **1** ✅ | discount fix через prompt-only adoption |

**2 hits из 3 фактически affected задач.** t28 рандомизировалась в форму, где наш fix неприменим — не провал самого fix'а.

## Per-task diff (007 vs 006)

```
t05   1.00 -> 0.00  --- регрессия (randomization, "Answer should contain FST-1KPF96UD")
t25   0.00 -> 1.00  +++ TARGET HIT
t37   0.00 -> 1.00  +++ TARGET HIT
t38   0.07 -> 0.54  +++ fraud forensic улучшилось (partial)
t39   0.57 -> 0.19  --- fraud forensic регрессия (partial)
t40   0.05 -> 0.07  +++ marginal partial
```

Остальные 34 задачи без изменений.

## Результат

**+2.77 pp на 40-task бенчмарке, +1 hard win.** На 31-overlap с 006 = +0 hard wins (t25 +1 нейтрализован t05 −1 из-за randomization). Соотношение сигнал/шум ~1:1.

Гипотеза: targeted fix discount-refs стоит на ожидаемые 3 wins (+7.5 pp). Реально получили: 2 фактических hits на target (t25, t37 = +5 pp), 1 не сработал на randomized форме (t28 не в discount категории), плюс шумовая регрессия t05 (-1 win) и graded fluctuations на t38/t39 примерно нулевые.

`sanitized_denied = 0` подтверждает: **gpt-5.4 надёжно адаптируется к новым правилам в prompt'е**. Это третий эксперимент подряд, где prompt-only fix даёт adoption без срабатывания mechanical post-process. Post-process остаётся как safety net.

## Выводы

1. **Discount-refs hypothesis частично подтверждена.** Прямое попадание в 2 из 3 целевых задач (t25, t37). Не сработала только там, где randomization увёл задачу в другую failure category.

2. **Single-run noise теперь главный bottleneck.** Имея 31 base task + 9 новых + randomization, σ per-run ~±2-3 pp. Любой следующий fix целящий <5 pp придёт в зону, где нельзя отличить сигнал от шума. **Без 008-multi-run-eval двигаться дальше становится дорого/неинформативно**.

3. **Cost neutral.** Input/output tokens / latency / tool calls — почти идентичны 006 (±2%). Расширение prompt'а на одну строку и regex маппинг не влияют на стоимость / behavior model в смысле объёма работы.

4. **Prompt adoption — стабильный механизм** для gpt-5.4. Достаточно прописать рулинг в `Refs by outcome` секции — модель сама будет следовать. Это даёт уверенность в дальнейших prompt-only fix'ах (009 probing-silent должен сработать аналогично).

5. **Fraud forensic = chaos.** t38/t39/t40 партиальные scores прыгают в обе стороны (t38 0.07→0.54, t39 0.57→0.19) без явных prompt changes — это randomization селектирует разной сложности fraud incidents per run. Отдельная категория, требует prompt про selectivity.

## Следующие шаги

- [ ] **008-multi-run-eval** (CRITICAL приоритет): прогнать 007 baseline 3× раза для измерения σ. Это разблокирует интерпретацию всех дальнейших prompt-fix'ов. Стоимость: ~75 минут, цена ~$30 (рассчитано из 1.5×$ за 005 при сопоставимых tokens).
- [ ] **009-probing-silent** (после 008): rule `ecom_read_silent` для probing reads после SQL — целит t13/t14/t15/t16 (cat A). Симметричный fix к 006's excluded-entity rule.
- [ ] **010-security-relaxation**: целит t31 + потенциально другие false-positive DENIED, требует осторожности (риск регрессии на real security tasks).
- [ ] **011-fraud-selectivity**: t38/t39/t40, chain-of-thought про exact match criteria.

## Артефакты прогона

- `agent/18-05-26-1.jsonl` — debug log
- `agent/ecom_mcp.log` — MCP tool calls
- `failures.md` — детальный анализ + sygnal/noise обсуждение
