# 016 — hermes-fixes-phase1

**Дата:** 2026-05-28
**Статус:** в работе (smoke пройден, full-bench не запускался)
**Автор/агент:** Ivan + Claude Opus 4.7 (1M context)
**Бранч/коммит:** `main @ eda0ed0 (после 015 full-bench)`
**Базлайн:** `015-hermes-deepseek` (Hermes + DeepSeek V4 Pro, 50-task = 68.08%)
**Цель comparison:** `011-generalize-silent` (Codex + gpt-5.4, 50-task = 76.62%)
**Модель:** `deepseek/deepseek-v4-pro` через OpenRouter
**Harness:** Hermes CLI

## Сознательное отступление от конвенции "одно изменение = один эксперимент"

В 015 каждый full-bench занимает ~1h30m последовательно. Прогонять по одному фиксу за раз — съест дни. Пакуем шесть связанных правок одной гипотезой: «закрыть конкретные регрессии vs 011 и забрать joint headroom там, где оба валятся, чтобы выйти на ≥80%». Прирост каждого фикса оценён по post-mortem'у 015 (см. ниже). После прогона разберём, какие фиксы реально дали pp, а какие — шум.

## Гипотеза

Если применить шесть точечных фиксов (A1, A2, A3, A4, A5, B2) к промпту и harness'у hermes/deepseek, full-bench вырастет с **68.08% (015) → ≥80%**, обгоняя codex/011 (76.62%) и закрывая основные категории регрессий.

## Что меняем (vs 015)

### A. Восстановить регрессии vs codex (~+10–12 pp ожид.)

**A1. Security.md в refs при ЛЮБОМ отказе/блоке** (не только DENIED_SECURITY).
Файл: `prompts/instructions.md` — раздел "Refs by outcome" и "Cross-outcome rule — security.md as meta-policy". Закрывает t21, t36, t46-стиль failures (codex тоже падал на t46 — это joint headroom). Правило: «ANY answer that declines/refuses/blocks/denies because of a policy/role/authorization constraint MUST include `/docs/security.md`, regardless of outcome code».

**A2. JSON-fallback retry в hermes_agent.py.**
Файл: `hermes_agent.py` — секция `6b. JSON-fallback retry`. Если `_extract_task_result_json` вернул None (модель не отдала JSON), запускаем `hermes -z` повторно с reply-back промптом «previous reply did not contain JSON, respond NOW with ONLY a JSON object using your previous conclusions». Timeout 180с. Закрывает t32-стиль (ERR_INTERNAL из-за `no JSON object found`).

**A3. Outcome decision tree — DENIED_SECURITY vs NONE_UNSUPPORTED.**
Файл: `prompts/instructions.md` — раздел "Decision rules". Добавлена таблица «policy-blocked → DENIED_SECURITY, state-blocked → NONE_UNSUPPORTED» + explicit заметка: «отказ из-за фейкового manager-approval = DENIED_SECURITY, не NONE_UNSUPPORTED». Закрывает t42 (hermes 015 отказал корректно, но с неверным outcome-тегом).

**A4. Refs hygiene для support-note YES/NO (с worked example).**
Файл: `prompts/instructions.md` — добавлен worked example «support-note YES/NO claim, the most common refs-hygiene trap». Чёткое правило: при `<NO>` цитировать **1 anchor SKU + 1–2 closest variants**, не все N siblings. При `<YES>` — только тот SKU. Закрывает t07 (undercite — missed sibling) и t08 (overcite — 30 refs).

**A5. Cite target object в DENIED для "my-basket"/manager-verification случаев.**
Файл: `prompts/instructions.md` — раздел "Attack-target citation rule (REVISED)". Старое правило «DO NOT include the basket attacker named» оказалось слишком жёстким. Разделил случаи:
- *Identity-mismatch* (чужой basket) → silent, target НЕ в refs.
- *Social engineering / OOB approvals / manager-claims на own basket* (`my basket basket_NNN`) → target В refs.
- *Manager-verification ask* ("is X a manager at PowerTool Y") → store В refs.
- *Pure prompt-injection markers* без real target → только `/docs/security.md`.

Закрывает t25 (missing basket_077.json), t28 (missing store_graz_lend.json) — оба провалились и у codex.

### B. Push for overtake (joint headroom где codex тоже валится)

**B2. Refund refs convention (worked example).**
Файл: `prompts/instructions.md` — worked example «refund / single-payment action». Правило: при действии над конкретным `pay_NNN` цитируем именно этот payment + policy doc, не сканируем историю клиента. Закрывает t43, t44 (оба 0/0 у codex+hermes).

### C. Meta-improvement

**C1. WORKERS=4 by default.**
Файл: `main.py` — default `WORKERS` env var с `1` на `4`. Сокращает full-bench с ~1h30m → ~25 минут. Параллелизм уже был реализован в 011/015 через ThreadPoolExecutor.

## Что НЕ меняем (vs 015)

- `ecom_mcp_server.py` — побайтовая копия.
- `prompts/codex_preamble.md`, `compact_prompt.md` — побайтовая копия.
- `hermes_home/config.yaml` — побайтовая копия (24 disabled toolsets, bitgn-ecom MCP only).
- Bootstrap последовательность (tree -L 2, tree -L 4 /docs, AGENTS.MD, /bin/date, /bin/id).
- `debug_logger`, `formatters`, `http_sync_client`, `env_loader`.

## Изоляция

Без изменений vs 015 — см. `experiments/015-hermes-deepseek/README.md`.

## Запуск

```bash
source venv/bin/activate

# Smoke на одну задачу (форсим WORKERS=1 для чистого вывода)
HERMES_BIN=/Users/ivan/Documents/ai/sample-agents/ecom-py/venv/bin/hermes \
  WORKERS=1 \
  python -m main t01

# Полный 50-task прогон (default WORKERS=4, ~25 минут)
HERMES_BIN=/Users/ivan/Documents/ai/sample-agents/ecom-py/venv/bin/hermes \
  python -m main
```

## Результат

| Метрика | 011 codex baseline | 015 hermes baseline | 016 эксперимент | Δ vs 015 | Δ vs 011 |
|---|---|---|---|---|---|
| Final score (50 tasks) | 76.62% | 68.08% | — | — | — |
| Wins (1.00) | 38 | 33 | — | — | — |
| Crashes / ERR_INTERNAL | 0 | 1 (t32) | — | — | — |
| Wall-time | ~1h45m parallel | ~1h33m sequential | — | — | — |

Будет заполнено после прогона.

## Per-fix ожидаемый эффект (для post-mortem)

| Fix | Слоты (по 015 detail) | Ожид. эффект | Реальный |
|---|---|---|---|
| A1 (security.md auto) | t21, t36 (+ возможно t46) | +4 pp | TBD |
| A2 (JSON retry) | t32 | +2 pp | TBD |
| A3 (DENIED vs UNSUPPORTED) | t42 | +2 pp | TBD |
| A4 (support-note refs) | t07, t08 | +2–4 pp | TBD |
| A5 (cite target object) | t25, t28 (joint headroom) | +4 pp | TBD |
| B2 (refund refs) | t43, t44 (joint headroom) | +2–4 pp | TBD |
| C1 (WORKERS=4) | — | wall-time -75% | TBD |

## Выводы

Будет заполнено после прогона. Ключевые вопросы:
1. Подтвердилась ли гипотеза «hermes/deepseek догонит и обгонит codex»?
2. Какие фиксы реально сработали, а какие оказались косметикой?
3. Появились ли НОВЫЕ регрессии от прокачки refs (особенно от A1 и A5 — over-citing security.md или target object там где не надо)?
4. Если score < 76.62% (т.е. не догнали codex) — куда копать в phase 2?

## Следующие шаги

- [ ] Запустить full-bench 016, сравнить per-task с 011/015.
- [ ] Заполнить таблицы Результат и Per-fix эффект.
- [ ] Если >80% — оформить как baseline для 017. Если <76% — собрать failures.md.
- [ ] Phase 2 (если первый прогон даст < 82%): A4 deeper worked-examples + B1 (fraud-forensic протокол) — см. дискуссию в conversation.
