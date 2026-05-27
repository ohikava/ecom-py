# 015 — hermes-deepseek

**Дата:** 2026-05-27
**Статус:** smoke сдан (t01 score 1.00); full-bench не запускался
**Автор/агент:** Ivan + Claude Opus 4.7
**Бранч/коммит:** `main @ after-014 (bc0c94a)`
**Базлайн:** `011-generalize-silent` (Codex CLI + gpt-5.4)
**Модель:** `deepseek/deepseek-v4-pro` через OpenRouter
**Harness:** Hermes CLI (`hermes -z`) вместо Codex CLI (`codex exec`)

## Гипотеза

Если перенести scaffolding 011 (промпты, MCP-сервер, refs sanitizers, bootstrap)
с Codex CLI на Hermes CLI, поменяв провайдер на OpenRouter + DeepSeek V4 Pro,
то пайплайн end-to-end заработает (минимум 1 пример сдан) при условии полной
изоляции: агенту доступен ТОЛЬКО `bitgn-ecom` MCP, никаких встроенных тулсетов
(терминал, файлы, веб, браузер, code execution, …).

## Что меняем (diff vs 011)

Все промпты (`prompts/codex_preamble.md`, `prompts/instructions.md`,
`compact_prompt.md`) и MCP-сервер (`ecom_mcp_server.py`) — побайтовая копия
из 011. Меняется только:

1. **`codex_agent.py` → `hermes_agent.py`** — subprocess backend:
   - `codex exec --json --output-schema schema.json ...` → `hermes -z PROMPT
     --model deepseek/deepseek-v4-pro --provider openrouter -t bitgn-ecom
     --ignore-rules --yolo`.
   - `--ignore-rules` отключает auto-injection AGENTS.md / SOUL.md / memory.
   - `-t bitgn-ecom` явно подключает MCP-сервер к toolbox (без `-t` режим
     `-z` не передаёт MCP-тулы модели — это поведение oneshot-ветки в
     `hermes_cli/oneshot.py:105`).
   - `--yolo` авто-аппрувит tool-call'ы (oneshot повис бы на approval-запросе).
   - JSON-схема ответа теперь живёт **в промпте** (`_HERMES_JSON_TAIL`), не в
     `--output-schema` (у Hermes такого флага нет). Извлекаем JSON из текста
     последним сбалансированным `{...}` блоком (та же логика что в 014).

2. **`hermes_home/config.yaml`** — изолированный HERMES_HOME с:
   - `model.default: deepseek/deepseek-v4-pro`, `model.provider: openrouter`.
   - `mcp_servers.bitgn-ecom`: command/args указывают на нашу копию
     `ecom_mcp_server.py`; per-task env (`VAULT_HARNESS_URL`,
     `VAULT_MCP_REFS`, `VAULT_MCP_LOG`) приходит через `${VAR}` интерполяцию
     против env родительского процесса hermes.
   - `agent.disabled_toolsets`: **все 24 встроенных тулсета** (web, browser,
     terminal, file, code_execution, vision, video, image_gen, video_gen,
     x_search, moa, tts, skills, todo, memory, session_search, clarify,
     delegation, cronjob, messaging, homeassistant, spotify, yuanbao,
     computer_use). Проверено `hermes tools list` — все disabled.
   - `platform_toolsets.cli: [bitgn-ecom]` — для CLI-платформы оставляем
     ТОЛЬКО MCP-сервер, никакой native composite вроде "hermes-cli".
   - `auxiliary.*: provider=""` — отключаем aux LLM-calls (vision,
     web_extract, compression), чтобы агент не мог фан-аутить на другие
     модели.
   - `model_catalog.enabled: false` — никаких HTTP-запросов за каталогом
     моделей во время прогона.

3. **`main.py`** — то же самое что в 011, только `from codex_agent import
   run_agent` → `from hermes_agent import run_agent`; default `MODEL_ID` →
   `deepseek/deepseek-v4-pro`.

4. Всё остальное (debug_logger, formatters, http_sync_client, env_loader,
   refs sanitizers, bootstrap последовательность tree/AGENTS.MD/date/id +
   `/docs` -L 4) — побайтовая копия из 011.

## Изоляция (важная часть задачи)

Агенту физически **недоступно** (проверено):

| Что | Как закрыли |
|---|---|
| Интернет / web search / fetch | `web`, `browser`, `x_search` отключены в `disabled_toolsets` |
| Запуск shell-команд на хосте | `terminal`, `code_execution` отключены |
| Запись/чтение файлов хоста | `file` отключён |
| Удаление файлов | `file` отключён + `ecom_delete` идёт через ВИРТУАЛЬНЫЙ MCP (не трогает host FS) |
| Долгоживущие задачи / cron | `cronjob`, `messaging`, `delegation`, `moa` отключены |
| Чтение skills / памяти hermes | `skills`, `memory`, `session_search` отключены |
| Aux LLM calls (vision, compression) | `auxiliary.*.provider=""` |
| HTTP к каталогу моделей | `model_catalog.enabled=false` |

Единственный канал наружу — `bitgn-ecom` MCP, который ходит ТОЛЬКО на
`VAULT_HARNESS_URL` (BitGN ECOM VM). Никакой другой сетевой активности с
точки зрения LLM-агента нет.

## Запуск

```bash
source venv/bin/activate

# Smoke на одну задачу
HERMES_BIN=/Users/ivan/Documents/ai/sample-agents/ecom-py/venv/bin/hermes \
  python -m main t01

# Полный 50-task прогон (когда дело дойдёт)
HERMES_BIN=/Users/ivan/Documents/ai/sample-agents/ecom-py/venv/bin/hermes \
  python -m main
```

Текущий venv проекта (`/Users/ivan/Documents/ai/ecom-py/venv/`) исполняет
наш Python (main.py, ecom_mcp_server.py). Hermes CLI живёт в соседнем venv
(`/Users/ivan/Documents/ai/sample-agents/ecom-py/venv/`); указываем явный
путь через `HERMES_BIN`, иначе `hermes_agent.py` пытается найти его рядом
с `sys.executable` и промахивается.

## Что пришлось доработать сверх «просто поменять подсистему»

1. **`hermes mcp` SDK не установлен в venv-е, где живёт hermes.**
   `hermes mcp test bitgn-ecom` и `hermes -z` падали с
   `name 'StdioServerParameters' is not defined` из-за `try/except ImportError`
   на `from mcp import ...` в `tools/mcp_tool.py`. Лечится:
   `/Users/ivan/Documents/ai/sample-agents/ecom-py/venv/bin/pip install mcp`
   (поставит mcp 1.27.1 + transitive deps).

2. **`hermes -z` без `-t bitgn-ecom` не подключает MCP.**
   Naked `hermes -z PROMPT` фоллбэчит на config-defined toolsets, и oneshot-
   ветка при resolve'е сводит набор тулов до пустого, если ни одного
   built-in/MCP имени не указано в `-t`. Симптом: модель сразу возвращает
   stub-JSON `{"message":"", "outcome":"", ...}` за 8 символов stdout,
   ноль MCP-вызовов. Лечится явным `-t bitgn-ecom`.

3. **Hermes фильтрует env при спавне stdio-MCP.**
   `tools/mcp_tool._build_safe_env` пропускает только PATH/HOME/XDG_*,
   так что `VAULT_HARNESS_URL` из env родительского процесса до MCP-сервера
   НЕ доходил → MCP-сервер падал с `FATAL: VAULT_HARNESS_URL not set`,
   stdio-handshake обрывался, в `logs/agent.log` появлялось
   "unhandled errors in a TaskGroup (1 sub-exception)". Лечится через
   `${VAR}` интерполяцию в `mcp_servers.bitgn-ecom.env` (поддерживается
   `_interpolate_env_vars`, см. `tools/mcp_tool.py:2131`).

4. **`hermes -z` не отдаёт token usage.**
   В oneshot-режиме stdout = только финальный текст ответа, без telemetry.
   Session JSON (`hermes_home/sessions/*.json`) тоже не сохраняет per-message
   usage. → `input_tokens`/`output_tokens`/`reasoning_tokens` остаются 0
   в `agent_metrics`. **Лимитация задокументирована**; для cost-tracking
   на полном прогоне понадобится либо парсить state.db (SQLite), либо
   обернуть OpenRouter requests через прокси, либо переключиться с `-z` на
   `chat -q -Q --verbose`. **Время и кол-во tool-calls** мы трекаем
   корректно: elapsed_ms через `time.time()`, tool_calls через дельту
   `ecom_mcp.log` (ловим строки `[ecom-mcp HH:MM:SS] ecom_<name>(...)`).

## Smoke (t01)

```
$ HERMES_BIN=.../hermes python -m main t01
```

| Метрика | Значение |
|---|---|
| Score | **1.00** ✅ |
| Outcome | `OUTCOME_OK` |
| Message | `<YES> FST-APSRIZJW — Heco Zinc Plated HECO 3DW-64B Nut Bolt and Washer bolt 8mm 40mm 50pc, EUR 53.00` |
| MCP tool calls | 7 (ecom_exec SQL, ecom_find, ecom_search, ecom_read) |
| Elapsed | 62.9 s |
| Tokens (in/out/reasoning) | n/a (см. limitation #4 выше) |
| Bootstrap reads | tree /, tree /docs, AGENTS.MD, /bin/date, /bin/id |
| Грамотный fallback на NEUTRAL toolset? | да, отвечает SQL + targeted read |

Прогнан дважды (на двух рандомизациях t01 — Heco TopFix GTU-YPJ и Heco
3DW-64B), оба раза 1.00. Цепочка end-to-end стабильна.

## Verification

- ✅ MCP-сервер виден ТОЛЬКО как `bitgn-ecom` (нет других тулов).
  Подтверждено `hermes tools list` под `HERMES_HOME=hermes_home/`.
- ✅ Все 24 встроенных toolset отключены в isolated config.
- ✅ Smoke t01 → 1.00 на двух подряд прогонах (разные рандомизации).
- ✅ Tool-calls трекаются (7 вызовов на t01).
- ✅ Время трекается (63 с).
- ⚠️ Токены не доступны через `-z`. Лимитация, не блокер для smoke; для
  full-bench нужно решить (см. limitation #4).
- ⚠️ Hermes CLI лежит в **отдельном** venv (sample-agents), нужно ставить
  `mcp` пакетом туда же. Документировано в инструкции выше.

## Выводы

1. **Гипотеза подтверждена end-to-end на smoke.** Same prompts, same MCP,
   same refs-sanitizers — Hermes + DeepSeek V4 Pro проходит t01 на 1.00
   без какого-либо тюнинга промптов под новый стек. Это позволит на
   следующем шаге запустить полный bench и сравнить score с 011 чисто по
   эффекту смены модели/CLI, а не комбинации с другими правками.

2. **Изоляция работает.** Агент не может ходить в интернет, читать/писать
   файлы хоста, запускать shell — только `bitgn-ecom` MCP. Сравнимо по
   tool-surface с Codex-прогонами 005-013.

3. **Hermes как harness — рабочий, но требует трёх костылей** (см.
   "Что пришлось доработать"). Самые неочевидные: явный `-t MCP_NAME` для
   `-z` и `${VAR}` интерполяция в config.env (иначе MCP-сервер сразу
   падает без env). Документировано здесь, чтобы 016+ запускался с нуля.

4. **Стоимость одного прогона t01** оценочно сопоставима с 014 (DeepSeek V4
   Pro на OpenRouter, ~$0.5/1M in $1.5/1M out). Точные цифры — после
   фикса token-tracking'а.

## Следующие шаги

- [ ] **015.1 — full 50-task** для замера vs 011 (gpt-5.4) и vs 014
      (deepseek через Codex) — три точки сравнения на одной задаче, разные
      harness'ы и модели.
- [ ] **015.2 — токены через state.db или прокси-парсинг.**
      Hermes пишет per-turn usage в SQLite — посмотреть схему
      `hermes_home/state.db`, добавить читалку в `hermes_agent.py`.
- [ ] **015.3 — multi-run на t01-t05** для оценки шума на smoke.
- [ ] **016 — Hermes + другая модель** (например, Claude Sonnet 4.6 через
      Anthropic) для четвёртой точки сравнения.

## Артефакты прогона

- `agent/smoke.log` — финальный smoke (score 1.00 на двух подряд прогонах)
- `agent/27-05-26-*.jsonl` — debug-логи (последний = smoke run)
- `agent/ecom_mcp.log` — список всех MCP-вызовов на smoke
- `agent/hermes_home/config.yaml` — изолированный Hermes config
- `agent/hermes_home/logs/agent.log` — telemetry hermes runtime
- `agent/hermes_home/sessions/session_*.json` — детальные транскрипты
  (включая reasoning trace DeepSeek'а)
