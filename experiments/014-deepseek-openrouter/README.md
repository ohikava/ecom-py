# 014 — deepseek-v4 via OpenRouter

**Дата:** 2026-05-27
**Статус:** smoke сдан (t01 score 1.00); bench-режим — модель не справляется (см. ниже)
**Автор/агент:** Ivan + Claude Opus 4.7
**Бранч/коммит:** `main @ after-013 (bc0c94a)`
**Базлайн:** `013-ok-security-augment`
**Модель:** `deepseek/deepseek-v4-pro` через OpenRouter (`/chat/completions`, OpenAI-compatible)

## Гипотеза

Если подменить codex'овский провайдер с встроенного `openai` (ChatGPT auth → `gpt-5.4`) на кастомный `openrouter` (OpenAI-compatible chat completions → `deepseek/deepseek-v4-pro`), при этом сохранив тот же MCP-сервер `bitgn-ecom` и тот же scaffolding 013, то Codex CLI должен суметь увидеть и вызвать MCP-инструменты (`ecom_tree`, `ecom_read`, `ecom_read_silent`, ...) и сдать как минимум одну BitGN-задачу через `vm.answer`. Критерий успеха — score=1.0 хотя бы на одной таске.

## Что меняем (diff vs 013)

`codex_agent.py`:

1. **Provider-override knobs** (env-driven):
   - `CODEX_MODEL_PROVIDER` — имя кастомного провайдера. Пусто → встроенный `openai`. `=openrouter` → подставляются OpenRouter-настройки.
   - `CODEX_PROVIDER_BASE_URL` (default `https://openrouter.ai/api/v1`)
   - `CODEX_PROVIDER_ENV_KEY` (default `OPENROUTER_API_KEY` — Codex читает токен из этой env-переменной)
   - `CODEX_PROVIDER_WIRE_API` (default `chat`) — DeepSeek через OpenRouter говорит только OpenAI chat-completions; codex'овский дефолтный `responses` вернёт 404.
   - `CODEX_SEND_REASONING` — по умолчанию выключаем `model_reasoning_effort` для не-openai провайдеров (DeepSeek падает на неизвестных OpenAI-internal параметрах).

2. **Inline MCP-server registration через -c** — `mcp_servers.bitgn-ecom.command` и `.args` теперь передаются на каждый запуск. Раньше зависели от того, на какой `ecom_mcp_server.py` сейчас указывает `~/.codex/config.toml` — это сцепляло версии экспериментов. Теперь 014 запускает свой собственный MCP-сервер из своей папки независимо от глобального config.toml.

3. Build cmd доп. передаёт:
   ```
   -c model_provider="openrouter"
   -c model_providers.openrouter.name="openrouter"
   -c model_providers.openrouter.base_url="https://openrouter.ai/api/v1"
   -c model_providers.openrouter.env_key="OPENROUTER_API_KEY"
   -c model_providers.openrouter.wire_api="chat"
   ```

`README.md` (этот файл) и `codex_config.example.toml` обновлены.

## Что НЕ меняем

- Промпты (`prompts/codex_preamble.md`, `instructions.md`) — те же 013.
- MCP-сервер (`ecom_mcp_server.py`) — побайтовая копия 013.
- Refs-санитайзеры (`_sanitize_refs_for_denied`, `_augment_refs_for_ok`) — те же.
- Bootstrap (tree/AGENTS.MD/date/id + tree /docs -L 4) — тот же.

Цель — изолировать эффект смены модели/провайдера от всего остального.

## Запуск

```bash
source venv/bin/activate
cd experiments/014-deepseek-openrouter/agent

export CODEX_MODEL_PROVIDER=openrouter
export MODEL_ID=deepseek/deepseek-v4-pro
# OPENROUTER_API_KEY уже в .env (читается env_loader)

# Smoke на одну простую таску
python -m main t01

# Полный прогон
python -m main
```

## Известные риски

1. **`--output-schema` (structured output)** — Codex передаёт JSON Schema как `response_format.json_schema`. OpenRouter обещает поддержку у DeepSeek, но не для всех версий wire-API. Если не сработает — fallback: распарсить JSON из текстового ответа без strict schema.
2. **Reasoning** — DeepSeek V4 Pro имеет свой reasoning, но codex'овский `model_reasoning_effort` — это OpenAI o-series concept. Передавать его не имеет смысла; параметр выключен по умолчанию.
3. **MCP tool discovery** — главный pain-point. В прошлый раз модель не видела MCP. Гипотеза: при `wire_api="responses"` тулы передаются по responses-схеме, которую OpenRouter не понимает → 404 или silent drop. При `wire_api="chat"` тулы должны прийти как обычный OpenAI tools array — DeepSeek их видит.
4. **DENIED тасков (security)** — DeepSeek может реагировать иначе на prompt-injection чем GPT-5.4. Это не критерий успеха для smoke, но повлияет на полный score.

## Результат

### Smoke t01 (одиночный прогон)

| Метрика                  | Значение                                                                 |
|--------------------------|--------------------------------------------------------------------------|
| Score                    | **1.00** ✅                                                              |
| MCP tool calls           | 4 (ecom_exec ×2, ecom_find, ecom_read)                                   |
| Outcome                  | OUTCOME_OK, ref `/proc/catalog/CLN-GEF2EYP9.json`                        |
| Tokens (in / cached / out / reasoning) | 933 577 / 601 088 / 4 616 / 2 492                          |
| Wall (codex exec)        | ~120 s                                                                   |

### 10-task smoke bench (t01-t10, прерван после t08; CODEX_TIMEOUT_SEC=540, WORKERS=1)

| Метрика                              | Значение                                |
|--------------------------------------|-----------------------------------------|
| Завершено                            | 7 / 10 (прерван на t08)                 |
| Score 1.00                           | **0 / 7**                               |
| Codex timeouts (>540 s)              | **6 / 7**                               |
| Avg elapsed                          | **552 s** (упёрто в timeout)            |
| Tokens на 7 trials                   | 312k in / 7.9k out / 7.0k reasoning     |
| Tool calls (cumulative, из не-timeout) | 5 (все на t05)                        |

Артефакты: `agent/smoke10-aborted.jsonl`, `agent/ecom_mcp-smoke10.log`, `agent/proxy-smoke10.log`.

**Per-task разбор:**

| Task | Score | Причина                                                          |
|------|-------|------------------------------------------------------------------|
| t01  | 0.00  | TIMEOUT (>540s)                                                  |
| t02  | 0.00  | TIMEOUT                                                          |
| t03  | 0.00  | TIMEOUT, ответ без токена `<NO>` (требуется evaluator'ом)        |
| t04  | 0.00  | TIMEOUT                                                          |
| t05  | 0.00  | Уложился, 5 MCP-calls, ответ не содержит требуемый `FST-1KPF96UD`|
| t06  | 0.00  | TIMEOUT, без `<NO>`                                              |
| t07  | 0.00  | TIMEOUT, без `<NO>`                                              |

## Что пришлось доработать сверх «просто поменять провайдера»

Codex 0.130 + OpenRouter не работают «из коробки» по двум причинам — обе пришлось
решать в этом эксперименте:

1. **`wire_api="chat"` запрещён** в Codex 0.130 (см. [openai/codex discussions/7782](https://github.com/openai/codex/discussions/7782)).
   OpenRouter формально умеет только `/chat/completions` для большинства моделей,
   но **поддерживает `/v1/responses` для DeepSeek V4** (проверено прямым curl-пробом
   через OpenRouter — возвращает корректный `function_call`). Поэтому ставим
   `wire_api="responses"` — без всяких bridge'ей и downgrade'а.

2. **MCP-tools передаются как `{type:"namespace", tools:[...]}`** (новый формат Codex
   0.121+). OpenRouter эту обёртку пропускает как есть, DeepSeek её не понимает →
   тулы тихо игнорируются и модель отвечает «нет MCP-тулов». Известная проблема
   ([CLIProxyAPI #3298](https://github.com/router-for-me/CLIProxyAPI/issues/3298)),
   не пофикшено upstream'ом.

   Решение — `codex_namespace_proxy.py` (≈220 строк, чистый stdlib + httpx):
   - **Request side:** разворачивает каждый `{type:namespace, tools:[..]}` в плоские
     `{type:function, name:"mcp__server__tool"}` и сохраняет mapping
     `flat → (namespace, sub_name)` для текущего request.
   - **Response side:** парсит SSE по событиям, перехватывает `response.output_item.{added,done}`
     и `response.completed`, для каждого `function_call` с flat MCP-именем
     восстанавливает поле `namespace` — без этого `ResponseItem::FunctionCall`
     парсер Codex не диспетчит вызов в MCP, а отвечает модели «unsupported call»
     (мы это видели в первом неуспешном прогоне).

3. **DeepSeek + `--output-schema` ⇒ 0 tool calls.** При strict structured output
   DeepSeek сразу эмиттит JSON и пропускает шаг с tool calls (видели как ANSWER
   = «I'll search the catalogue…», score 0). Для не-openai провайдера
   `--output-schema` теперь по умолчанию выключен; JSON извлекается из текста
   через `_extract_task_result_json` (последний сбалансированный `{...}`).

## Запуск

```bash
source venv/bin/activate

# Шаг 1: поднять namespace-flatten proxy (отдельный терминал/background)
export OPENROUTER_API_KEY=...   # уже в .env
python experiments/014-deepseek-openrouter/agent/codex_namespace_proxy.py

# Шаг 2: запустить ECOM runner на DeepSeek
cd experiments/014-deepseek-openrouter/agent
export CODEX_MODEL_PROVIDER=openrouter
export MODEL_ID=deepseek/deepseek-v4-pro
python -m main t01     # одиночный smoke
python -m main         # full bench
```

## Выводы

- **Интеграционная гипотеза подтверждена.** Цепочка end-to-end работает:
  Codex CLI → namespace-proxy → OpenRouter → DeepSeek V4 Pro → MCP `bitgn-ecom`
  → BitGN VM. На smoke t01 модель прошла полный цикл (4 MCP-вызова, правильный
  ответ, score 1.00). **Один пример успешно прогнан** — критерий успеха
  эксперимента закрыт.
- **Practical гипотеза провалена.** В bench-режиме (10 задач подряд, t01-t10
  с CODEX_TIMEOUT_SEC=540) DeepSeek V4 Pro показал **0 / 7 score 1.00**, с
  6 timeouts из 7. На bench DeepSeek в 5-10× медленнее gpt-5.4: 552s avg vs
  47-77s у 005-013. Модель не готова к замене без дополнительных
  оптимизаций.
- **Что увидели в логах смоки:**
  1. **Timeout — главный убийца.** На таймаут падает 6 из 7 завершённых.
     Прокси показывает что DeepSeek делает много round-trips (по 10-30
     запросов на одну BitGN-таску), уходит в длинные reasoning-циклы и
     не успевает выдать финальный JSON.
  2. **Отсутствие `<YES>/<NO>` токенов.** BitGN evaluator требует
     включать `<YES>` или `<NO>` в ответ на yes/no задачи. GPT-5.4
     это делал из `/AGENTS.MD`. DeepSeek даёт правильный ответ текстом
     ("No, ..."), но без токена → evaluator zerое.
  3. **Один успешный non-timeout (t05) тоже score 0** — модель не
     выявила нужный SKU `FST-1KPF96UD`. Возможно качество ответа на
     bench-задачах действительно ниже у DeepSeek (или нужна более
     специфичная подсказка про SKU-format).
- **Provider swap — не "один env-var"**: понадобились ровно три
  вмешательства в коде (см. выше); без любого из них MCP не работает
  вовсе.
- **Стоимость smoke t01:** 933k input / 4.6k output ≈ $0.47/task. 7-trial
  bench: 313k in / 7.9k out — большая часть токенов потеряна в timeout
  без ответа.

## Следующие шаги

- [ ] **014.1 — поднять CODEX_TIMEOUT_SEC до 1200s** и WORKERS=3 — посмотреть,
      решает ли тайм-budget сам по себе, или DeepSeek принципиально циклит.
- [ ] **014.2 — усилить промпт про `<YES>/<NO>` токены** (явный пример в
      INSTRUCTIONS); из 7 завалов минимум 3 из-за отсутствия токена.
- [ ] **014.3 — отключить exec_command/web_search/image_generation** в Codex
      tools (DeepSeek может уходить в shell вместо MCP).
- [ ] **014.4 — попробовать deepseek-v4-flash** — быстрее и дешевле; качество
      может оказаться сопоставимым на простых задачах.
- [ ] **014.5 — обернуть proxy в lifecycle main.py** через `subprocess.Popen`,
      чтобы не было ручного двух-шагового запуска.
