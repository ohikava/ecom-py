# 007-codex-discount-refs — failures

40 задач, 30 hard wins, 8 hard fails + 2 partial fails (t38, t40), 1 средний partial (t39).

## Headline сводка

| Срез | 006 | 007 | Δ |
|---|---|---|---|
| Final on 40-task | 74.24% | **77.01%** | **+2.77 pp** |
| Hard wins on 40 | 29 | 30 | +1 |
| Hard wins on 31-overlap | 24 | 24 | **0** (reshuffled) |
| Avg input tokens / task | 210k | 211k | +0.5% |
| Avg elapsed / task | 52.1s | 52.2s | +0% |
| Avg tool calls / task | 11.0 | 11.0 | 0% |
| `sanitized_denied` events | 0 | **0** | — (prompt adoption работает напрямую) |

## Целевые задачи

| Task | 006 | 007 | Detail |
|---|---|---|---|
| t25 | 0 | **1** ✅ | discount fix через prompt сработал |
| t28 | 0 | 0 | рандомизировалась в другую категорию (refs/exclusion на Praterstern store) — наш fix не применим |
| t31 | 0 | 0 | outcome mismatch (cat C) — out of scope 007 |
| t37 | 0 | **1** ✅ | discount fix через prompt сработал |

**2 из 3 ожидаемых wins реализованы**. t28 не починился, но не нашему fix-у — она просто была рандомизирована в другую failure category.

## Per-task diff (007 vs 006)

```
t05   1.00 -> 0.00  --- регрессия (randomization)
t25   0.00 -> 1.00  +++ TARGET, discount fix
t37   0.00 -> 1.00  +++ TARGET, discount fix
t38   0.07 -> 0.54  +++ fraud forensic улучшилось (partial)
t39   0.57 -> 0.19  --- fraud forensic регрессия
t40   0.05 -> 0.07  +++ marginal
```

## Что показывают результаты

### 1. Prompt-only adoption работает (третий раз подряд)

`sanitized_denied = 0` событий за весь прогон. Это значит: model сама включила `/docs/discounts.md` в refs DENIED, потому что мы добавили правило в `prompts/instructions.md`. Mechanical post-process `_sanitize_refs_for_denied` (новые topic→policy mapping) не сработал ни разу.

Это **третий эксперимент подряд**, где prompt rule достаточен для adoption gpt-5.4 (005→006 `ecom_read_silent`, 006 `_sanitize_refs_for_denied` mechanical post-process — оба 0 событий, model выполнила правила prompt'а). Post-process остаётся как safety net на случай регрессии модели.

### 2. Randomization съела половину выигрыша

На 31-task overlap **число hard wins не изменилось** (24 → 24):
- +t25 (наш fix)
- −t05 (randomization)
- остальные стабильны

То есть **2 из ожидаемых 3 wins реализованы**, но на 31-overlap они visible как **+0 pp** из-за компенсирующей рандомной регрессии. На полном 40-task видно +1 hard win (t37) → +2.77 pp.

Это **критический сигнал в пользу 008-multi-run-eval**. При σ ~±2-3 pp на одном прогоне, нынешний результат "+2.77 pp" может быть полностью шумом. Только многократный прогон даст доверительный интервал.

### 3. Fraud forensic — chaos category

| Task | 005 | 006 | 007 |
|---|---|---|---|
| t38 | (new) | 0.07 | 0.54 |
| t39 | (new) | 0.57 | 0.19 |
| t40 | (new) | 0.05 | 0.07 |

Каждая randomized в новую форму на каждом прогоне, score прыгает в обе стороны. Модель находит все fraud payments (recall ~100%) на t39/t40, но over-includes (54-203 false positives). Это структурная проблема selectivity, нужен отдельный эксп.

## Несработавшие категории (т.е. остались как в 006)

### A: probing reads (t13, t14, t15, t16)

Все 4 fail'а одинаковые: `answer contains invalid reference '/proc/catalog/...'` — модель прочитала кандидата через `ecom_read`, который не contributed. Нет prompt rule для probing reads через `ecom_read_silent`. **Цель эксперимента 008**.

### C: false-positive DENIED (t31)

Outcome mismatch без refs-проблемы. **Цель эксперимента 010** (security relaxation).

### t05: новая регрессия — answer-content проблема

```
Detail: Answer should contain 'FST-1KPF96UD'
```

Это новая категория: модель **не нашла нужный продукт** в каталоге. На randomized форме задачи. Нет refs-проблемы — просто wrong answer. Нужно смотреть конкретный prompt + tool calls для t05 чтобы понять, что пошло не так. Возможно false-positive security DENIED, или search не нашёл нужный SKU.

### t28: randomization shift

В 006 t28 был discount-related ("verify Luisa, then add service_recovery"), в 007 рандомизировался в excluded-store category (Praterstern). Наш discount fix к нему не применим в этой форме. Можно бы поймать через `CODEX_STRIP_EXCLUSIONS=1` (off by default в 006/007), но это другой experiment.

## Что показывает мета-анализ

1. **Target hit rate 2/3** — fix работает на тех задачах, где randomized в expected категорию. Это **lower bound** эффективности; на multi-run прогоне 3/3 ожидается чаще.

2. **Сигнал effect-to-noise = 1:1** — на одном прогоне +2.77 pp при σ ~±2-3 pp неинтерпретируем как pure improvement или noise.

3. **Cost neutral** — input/output tokens, elapsed, tool calls между 006 и 007 практически идентичны. Это значит prompt rules не повлияли на behavior model в смысле объёма работы — только на final refs decision.

4. **Прогнозы по pp-вкладу из README **+3 wins / +7.5 pp** оказались слишком оптимистичными в одно-прогонной выборке. Реалистичный single-run эффект: +1-2 hard wins, остальные кейсы либо рандомизированы в другие категории, либо съедены реверс-регрессиями.

## Приоритет следующих экспериментов (обновлённый)

| # | Эксперимент | Status | Ожидание |
|---|---|---|---|
| 008 | **multi-run-eval (3× 006 baseline + 3× 007)** | **CRITICAL** | измерение σ; без него любой <+5 pp интерпретировать нельзя |
| 009 | probing-silent (cat A: t13-t16) | high priority после 008 | +3-4 wins (если σ позволит видеть) |
| 010 | security relaxation (t31) | medium | +1 win |
| 011 | fraud selectivity (t38, t39, t40) | medium, chaotic | t.b.d. |

## Рекомендация

Перед очередными prompt-экспериментами **запустить 008-multi-run-eval** на 3-4 прогонах текущего 007. Это даст:
- σ для score (вероятно ±2-3 pp)
- стабильную mean (наиболее вероятно 75-78%)
- per-task probability of failure (некоторые задачи failing 100% времени = real category, некоторые 30% = randomization)
- честную базу для последующих сравнений
