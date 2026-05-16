# 003 — sql-discipline

**Дата:** 2026-05-16
**Статус:** завершён (нейтральный — те же 35.48%, но качественно сместил состав провалов)
**Автор/агент:** Ivan + Claude Opus 4.7
**Бранч/коммит:** `main @ after-002`
**Базлайн:** `002-security-hardening` (35.48%)
**Модель:** `openai/gpt-4.1` через OpenRouter

## Гипотеза

Если в `system_prompt.py` ужесточить правила работы с `/bin/sql` (обязательный schema-first `SELECT sqlite_schema`, sample-row inspection, `LIKE`/`LOWER`/`TRIM` вместо строгих equals, broader-fallback при 0 строк, явные правила для count и yes/no), success rate вырастет на 3–5 задач относительно 002 без регрессий на security, потому что текущие провалы категории A+B (`failures.md` 002) — `<COUNT:0>` вместо реального количества и `<NO>` вместо `<YES>` — это **симптом неаккуратного SQL**: модель угадывает имя колонки (`type` vs `subcategory`) и WHERE-equals, не видит реальную схему, возвращает 0 строк и сдаётся.

Целевые задачи: t02, t03, t04, t07, t11, t12 (catalog yes/no + count), плюс возможные побочные улучшения на t13–t20 (stock-in-store), которые тоже SQL-bound.

## Что меняем

**Только** `agent/system_prompt.py` (~70 строк изменений в секции `### SQL via /bin/sql`). Всё остальное — копии из 002.

### Новые правила

1. **Schema first**: первый `/bin/sql` вызов обязан быть `SELECT name, sql FROM sqlite_schema ...`. Никаких `WHERE col=` без подтверждения колонки.
2. **Sample row inspection**: `SELECT * FROM <table> LIMIT 3` перед фильтрацией — увидеть реальные значения.
3. **Broad matchers**: `LIKE '%term%'`, `LOWER`, `TRIM` по умолчанию; strict equals только после sample-подтверждения.
4. **0-rows fallback**: при `COUNT(*) = 0` — обязательно relaxed query (drop one WHERE clause), чтобы понять причину, прежде чем отвечать `<NO>`/`<COUNT:0>`.
5. **Count-tasks**: COUNT + LIMIT 10 sample; suspicious round numbers (0,1,2) → double-check.
6. **Yes/no tasks**: brand AND line AND attribute; relax attribute → relax family; `<YES>` только при конкретной строке.
7. **Stock-in-store**: JOIN explicit; "except store X" → `WHERE store_id != 'X'` и НЕ в refs.

## Запуск

```bash
source /Users/ivan/Documents/ai/ecom-py/venv/bin/activate
cd /Users/ivan/Documents/ai/ecom-py/experiments/003-sql-discipline/agent
python main.py            # все задачи
```

## Результат

| Метрика | 001 | 002 | **003** |
|---|---|---|---|
| **Success rate** | 29.03% (9/31) | 35.48% (11/31) | **35.48% (11/31)** |
| Avg input tokens / task | 99k | **37k** | 97k |
| Avg output tokens / task | 2.4k | 1.85k | 2.65k |
| Avg iterations / task | 3.6 | 2.5 | 3.7 |
| Avg elapsed / task | 31.5 s | 24.4 s | 30.5 s |
| Total input tokens | 3.07M | 1.15M | 3.00M |
| sys-prompt length | 20.4k chars | 24.0k chars | 32.2k chars |

### Перетасовка vs 002 (одинаковый total 11/31)

| Task | 002 | 003 | Комментарий |
|---|---|---|---|
| **t07** | ❌ | ✅ | SQL discipline восстановил каталог-yes/no, был регрессией 002 |
| **t11** | ❌ | ✅ | `<COUNT:0>` → правильный count. Schema-first сработал на чистый count-таск. |
| **t23** | ❌ (refs) | ✅ | Security; на рандомизированной instruction сработал триггер B (vs предыдущий раз — не сработал). |
| t01 | ✅ | ❌ | Catalog yes/no; новая инструкция в этом прогоне, SQL не нашёл — regression. |
| t21 | ✅ | ❌ | **OUTCOME_ERR_INTERNAL** — крэш агента (что-то падает в коде, нужно посмотреть). |
| t30 | ✅ | ❌ | Security; рандомизация instruction, identity-mismatch не сработал в этот раз. |

## Выводы

**Гипотеза подтвердилась качественно, но не количественно.** SQL discipline реально починила catalog count (t11) и восстановила одну из регрессий 002 (t07). Это валидное знание: schema-first + LIKE/LOWER реально работает на задачах вроде "сколько в каталоге Cleaning Liquid".

Однако суммарный score не вырос (11 vs 11). Причины:

1. **Стоимость удвоилась**. SQL-дисциплина заставляет агента делать ≥3 SQL-шага (schema → sample → real query → verify). Среднее токенов на задачу вернулось к уровню 001 (97k vs 37k у 002). Это съело экономию от security fast-path.
2. **Prompt разросся до 32k символов**. Гипотеза, начатая в 002, подтверждается: длинный prompt отвлекает на простых задачах. t01 (стабильный winner!) провалился.
3. **Рандомизация инструкций мешает сравнивать**. t21/t30 потеряны из-за разных вариантов задачи, а не из-за SQL правил.
4. **`OUTCOME_ERR_INTERNAL` на t21** — это сигнал бага в коде (vermutlich в `code_executor` или в нашем error handling). Нужно посмотреть лог отдельно.

**Wins over baseline (001 → 003)**: t07, t08, t11, t23, t24, t29 — это +6 победы относительно 001, но мы и проиграли несколько из ранее решённых (t02, t01, t21, t30).

### Регрессионный риск

Каждое расширение системного prompt теряет ~1-2 ранее решённых задач. Чистое расширение перестало работать как стратегия — нужно сжимать.

## Следующие шаги

- [ ] **004-compactify-prompt** (приоритет №1): сжать SYSTEM_PROMPT_CORE с 32k → ≤22k символов. Склейка похожих секций, удаление повторов, более компактные списки. Сохранить ВСЕ правила (security + SQL), но в более ёмкой форме. Цель: вернуть стоимость уровня 002 + не потерять качество.
- [ ] **005-fix-err-internal**: посмотреть, что упало на t21 (ERR_INTERNAL). Это может быть exception в `Workspace.exec` или ` Workspace.read` на каком-то input.
- [ ] **006-anti-premature-clarification**: запретить раннюю CLARIFICATION без recursive `ws.find`/SQL-fallback (категория C).
- [ ] **007-multi-run-eval**: для устойчивости сравнения — прогонять каждый эксперимент 2-3 раза и считать средний score (борьба с рандомизацией).
