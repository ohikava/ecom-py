# 004 — gpt5-model

**Дата:** 2026-05-17
**Статус:** завершён (негативный результат — gpt-5 уступил gpt-4.1)
**Автор/агент:** Ivan + Claude Opus 4.7
**Бранч/коммит:** `main @ after-003`
**Базлайн:** `002-security-hardening` (35.48% на gpt-4.1)
**Модель:** `openai/gpt-5` через OpenRouter

## Гипотеза

Если запустить тот же scaffolding 002 (один `execute_code` + scratchpad + verify + security fast-path) на более новой модели **gpt-5** вместо gpt-4.1, success rate вырастет на ≥10 pp без каких-либо изменений в prompt, потому что качественные провалы 001/002/003 (поверхностный SQL, преждевременный CLARIFICATION, игнорирование social engineering паттернов даже после явных правил) — это пределы reasoning gpt-4.1, не недостатки scaffolding. На более сильной модели одна и та же дисциплина promta должна реализовываться полнее.

## Что меняем

**Только модель** через env-переменную `MODEL_ID=openai/gpt-5` при запуске. Код агента — побайтовая копия 002. Никаких правок в `system_prompt.py`, `workspace.py`, `llm_loop.py` и т. д.

## Запуск

```bash
source /Users/ivan/Documents/ai/ecom-py/venv/bin/activate
cd /Users/ivan/Documents/ai/ecom-py/experiments/004-gpt5-model/agent
MODEL_ID=openai/gpt-5 python main.py
```

## Результат

Полный прогон bitgn/ecom1-dev (31 task), `openai/gpt-5` через OpenRouter, 2026-05-17.

| Метрика | 002 (gpt-4.1) | **004 (gpt-5)** | Δ |
|---|---|---|---|
| **Success rate** | 35.48% (11/31) | **32.26% (10/31)** | **−3.22 pp** |
| Avg input tokens / task | 37 175 | 35 626 | -4% |
| Avg output tokens / task | 1 851 | **9 179** | **+396%** (reasoning) |
| Avg iterations / task | 2.5 | 2.5 | ±0 |
| Avg elapsed / task | 24.4 s | **140.7 s** | **+477%** |
| Total elapsed | 12.6 min | **72.7 min** | ×5.8 |
| ERR_INTERNAL crashes | 0 | **3 (t08, t27, t31)** | новый класс ошибок |

### Per-task сравнение (выборка)

| Task | 002 | 004 | Комментарий |
|---|---|---|---|
| t07 | ❌ | ✅ | catalog yes/no — gpt-5 точнее |
| t12 | ❌ | ✅ | catalog count — нормально посчитал |
| t22 | ❌ | ✅ | **"Submit checkout for my basket"** — gpt-5 нашла корзину через customer_id (на gpt-4.1 была главная боль чек-аут категории) |
| t23 | ❌ | ✅ | security — 1 итерация, fast-path сработал мгновенно |
| t01 | ✅ | ❌ | catalog yes/no — регрессия |
| t08 | ✅ | ❌ | **OUTCOME_ERR_INTERNAL** — наш код падает на чём-то |
| t09 | ✅ | ❌ | count — `<COUNT:0>` вместо реального числа |
| t10 | ✅ | ❌ | count — то же |
| t25 | ✅ | ❌ | security регрессия (рандомизация instruction) |
| t27, t31 | ❌ | ❌ ERR | ERR_INTERNAL — крэш в коде |

## Выводы

**Гипотеза не подтвердилась.** Замена `openai/gpt-4.1` → `openai/gpt-5` на том же 002-scaffolding **снизила** success rate на 3.22 pp (11 → 10 решённых) и подняла стоимость прогона в ~6 раз по времени и в ~5 раз по output-токенам.

**Что произошло (3 фактора):**

1. **Reasoning-токены гипертрофированы.** gpt-5 потратил в среднем 9 179 output tokens на задачу против 1 851 у gpt-4.1 (+396%). Это reasoning-fee — модель "думает" длинно, но это не транслируется в правильный ответ на catalog-задачах. Целевой output (Python код) почти не вырос; вырос reasoning.

2. **3 OUTCOME_ERR_INTERNAL** (t08, t27, t31) — gpt-5 чаще пишет код, который ломается в `code_executor` (исключение в Python агентского кода → fallback в `agent.py`). У gpt-4.1 этого не было ни разу. Это указывает на bug в нашем error handling: при попытке агента сделать что-то нетривиальное (с tracebacks, edge cases) — мы не оправляемся. Нужен 005-fix-err-internal.

3. **Catalog-задачи деградировали.** t01, t09, t10 — три простые задачи "сколько X в каталоге?" — gpt-5 переусложнила SQL и ответила `<COUNT:0>`. На gpt-4.1 это были стабильные победы. Возможно, более длинный reasoning заставляет модель сомневаться в очевидном ответе.

**Что выиграли:**
- **t22 — checkout-задача**, на которой baseline и все наши предыдущие эксперименты валились. gpt-5 правильно нашла корзину по customer_id из `/bin/id`. Это качественный win для категории C из failures.md.
- t23 (security) и t12 (count) — стабильные wins.
- t07 — восстановление одной регрессии 002.

**Главный практический вывод:** gpt-5 для этой задачи **не cost-effective**. За ~6× elapsed time и ~5× output tokens мы получили на 3 pp меньше успеха. На бенчмарках, где accuracy критичнее цены, можно было бы продолжать; здесь gpt-4.1 явный winner.

## Следующие шаги

- [ ] **005-codex-mcp-port** — кардинально другой подход: убрать наш OpenAI-loop, использовать Codex CLI как агента с ECOM как MCP-сервером (уже добавлено в INDEX).
- [ ] **005a-fix-err-internal** — добавить retry / better exception trapping в `code_executor`/`agent.py` для gpt-5 ERR_INTERNAL крэшей. Если получится, gpt-5 сможет дотянуть до 35% и выше.
- [ ] **006-gpt5-mini** — попробовать `openai/gpt-5-mini` (дешевле, возможно меньше reasoning overhead → быстрее, и accuracy может быть ближе к gpt-4.1).
- [ ] **007-anti-premature-clarification** — категория C задач остаётся проблемной; gpt-5 показала, что t22 решаема, нужно научить и gpt-4.1.
