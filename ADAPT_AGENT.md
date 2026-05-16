# Адаптация стороннего агента под BitGN ECOM

Бенчмарк `bitgn/ecom1-dev` крутится так: `main.py` получает задачи от BitGN, для каждой задачи поднимает изолированный runtime VM (`bitgn.vm.ecom`) и отдаёт управление функции `run_agent(...)`. Чтобы посадить ваш агент на эти задачи, нужно реализовать **только эту функцию**. Всё, что вокруг (получение задач, скоринг, сабмит ран-а), переиспользуется как есть.

Ниже — пошаговый рецепт: что скопировать, что заменить и как запустить из общего `venv/` в корне репозитория.

---

## 1. Скелет проекта

Создайте папку рядом с `baseline/`, например `my_agent/`, и положите в неё следующие файлы. **Импорты из `baseline/` запрещены** — мы копируем код, чтобы папка была самодостаточной.

```
my_agent/
  main.py                 # копия baseline/main.py (только импорт run_agent поменять)
  agent.py                # ваша реализация (см. ниже шаблон)
  http_sync_client.py     # копия baseline/http_sync_client.py — без изменений
  debug_logger.py         # копия baseline/debug_logger.py — без изменений
  env_loader.py           # копия baseline/env_loader.py — без изменений
```

### 1.1 `main.py`

Скопируйте `baseline/main.py` целиком. В нём ничего менять не нужно — он уже импортирует `run_agent` из соседнего `agent.py`:

```python
from agent import run_agent
```

То есть достаточно положить рядом ваш `agent.py` с такой же сигнатурой.

### 1.2 Вспомогательные файлы

`http_sync_client.py`, `debug_logger.py`, `env_loader.py` копируются из `baseline/` **без правок**. Они переиспользуются вашим `agent.py`.

---

## 2. Контракт `run_agent`

Из `main.py` функция дёргается так (`baseline/main.py:87`):

```python
run_agent(
    model_id,
    trial.harness_url,
    trial.instruction,
    task_id=trial.task_id,
    debug_logger=debug_logger,
)
```

Поэтому ваш `agent.py` обязан экспортировать:

```python
def run_agent(
    model: str,
    harness_url: str,
    task_text: str,
    task_id: str | None = None,
    debug_logger: JsonlDebugLogger | None = None,
) -> None: ...
```

Внутри функция должна:
1. Открыть `EcomRuntimeClientSync(harness_url, http_client=HttpxSyncClient())`.
2. (Опционально, но улучшает скор) выполнить бутстрап: `tree /`, `read /AGENTS.MD`, `exec /bin/date`, `exec /bin/id` — и добавить ответы в контекст модели.
3. В цикле (≤ 30 шагов) спрашивать модель, какой tool позвать, диспатчить вызов в runtime, складывать результат в контекст.
4. Завершаться **обязательным** вызовом `vm.answer(AnswerRequest(...))` с осмысленным `Outcome` — иначе скор не засчитается.

---

## 3. Что скопировать из `baseline/agent.py`

Это не «опциональные хелперы», без них агент не соберётся. Скопируйте их в свой `agent.py` дословно:

| Блок в `baseline/agent.py` | Зачем нужен |
|---|---|
| Pydantic-модели `Req_Tree`, `Req_Find`, `Req_Search`, `Req_List`, `Req_Read`, `Req_Write`, `Req_Delete`, `Req_Stat`, `Req_Exec`, `ReportTaskCompletion`, `NextStep` (строки 36-132) | Это и есть «JSON-схемы инструментов» вашего агента + контейнер `NextStep` для структурированного ответа модели. |
| `OUTCOME_BY_NAME` (154-160) | Маппинг строкового outcome в protobuf enum для `AnswerRequest`. |
| `dispatch(vm, cmd)` (332-379) | Единая точка, превращающая pydantic-запрос в нужный RPC рантайма. Без неё придётся писать `if-elif` на 10 веток вручную. |
| Хелперы форматирования `_format_*`, `_render_command`, `_mark_truncated`, `_format_result`, `_format_tree_entry` (163-297) | Превращают protobuf-ответы рантайма в «shell-shaped» текст для модели. Без них модель видит сырой JSON и плохо ориентируется. **Очень важен `_mark_truncated`** — иначе агент будет «слепнуть» на больших каталогах. |
| `_to_jsonable_result`, `_connect_error_to_dict` (300-329) | Нужны, если хотите писать debug-log по аналогии с baseline. |
| Системный промпт `system_prompt` (135-144) | Содержит подсказку про `/bin/sql`, обработку безопасности и подмешивание `HINT` из env — конвенция бенчмарка. |
| Список `must = [...]` для бутстрапа (412-417) | Стандартный набор «обязательных» первых вызовов перед началом цикла. |

Менять смело можно только цикл инференса (`for i in range(30): ...`, строки 438-540) — это место, где в baseline вызывается OpenAI; именно его вы и замените своим агентом.

---

## 4. Подмена движка инференса

В `baseline/agent.py` цикл выглядит так:

```python
resp = client.beta.chat.completions.parse(
    model=model,
    response_format=NextStep,
    messages=log,
    max_completion_tokens=16384,
)
job = resp.choices[0].message.parsed   # job: NextStep
```

Замените эту пару строк на вызов вашего агента. Главные требования:

- Возвращаемое значение должно быть валидным `NextStep` (или вы вручную собираете объект `NextStep(function=Req_…)`).
- История сообщений должна быть в формате OpenAI-чата: `system → user(bootstrap output) → user(instruction) → assistant(tool_call) → tool(result) → ...`. Если ваш агент работает иначе — конвертируйте на входе/выходе.
- Если ваш агент сам управляет циклом tool-use, можно не возвращать по одному `NextStep` за итерацию, а внутри одного вызова обработать всё — но тогда не забудьте сами вызвать `dispatch(vm, ReportTaskCompletion(...))` в конце.

Параметр `model` — это просто строка из env (`MODEL_ID`), используйте её как селектор внутри своей обёртки.

---

## 5. Окружение и зависимости

Используется **общий `venv/` в корне репозитория** (`/Users/ivan/Documents/ai/ecom-py/venv`, Python 3.14). Создавать отдельное виртуальное окружение для своего агента не нужно.

### 5.1 Активация и установка зависимостей

```bash
cd /Users/ivan/Documents/ai/ecom-py
source venv/bin/activate

# зависимости BitGN SDK (из buf.build) + рантайма агента
pip install --extra-index-url https://buf.build/gen/python \
    bitgn-api-connectrpc-python \
    bitgn-api-grpc-python \
    bitgn-api-protocolbuffers-python
pip install -r baseline/requirements.txt
pip install --upgrade protobuf
```

(Это ровно те же шаги, что описаны в `baseline/PROJECT_INIT.md`, только в одном `venv/` на весь проект.)

Если в `my_agent/` появятся свои зависимости — просто добавьте их в этот же `venv` через `pip install <pkg>`.

### 5.2 Переменные окружения

Положите в корень репозитория `.env` (его подхватит `env_loader.py`):

```
BITGN_API_KEY=...
OPENROUTER_API_KEY=...        # либо ключ вашего провайдера
BENCH_ID=bitgn/ecom1-dev      # значение по умолчанию
MODEL_ID=<ваша модель>        # опционально
# HINT=...                     # опциональная подсказка, подмешивается в system prompt
```

### 5.3 Запуск

```bash
# из корня репозитория
source venv/bin/activate
cd my_agent

# все задачи
python main.py

# одна задача
python main.py t01

# подмножество
python main.py t01 t04
```

Логи каждого запуска пишутся в `DD-MM-YY-N.jsonl` рядом с `main.py` (см. `debug_logger.py`) — там видно каждый tool-call, raw-ответ модели и финальный скор. Это основной канал отладки при портировании.

---

## 6. Чек-лист интеграции

- [ ] Папка `my_agent/` самодостаточна: ни одного `import` из `baseline/`.
- [ ] `agent.py` экспортирует `run_agent(model, harness_url, task_text, *, task_id, debug_logger)`.
- [ ] Скопированы pydantic-модели `Req_*`, `ReportTaskCompletion`, `NextStep`, `OUTCOME_BY_NAME`, `dispatch`, форматтеры `_format_*`.
- [ ] Цикл ограничен ~30 шагами и **всегда** заканчивается `vm.answer(AnswerRequest(...))`.
- [ ] Корректно мапится `Outcome` (особенно `OUTCOME_DENIED_SECURITY` для prompt-injection задач).
- [ ] `exec /bin/sql` со SQL в `stdin` доступен модели — без него каталог-задачи фейлятся.
- [ ] `result.truncated` обрабатывается (см. `_mark_truncated`), иначе модель «слепнет» на больших ответах.
- [ ] `debug_logger` получает события `tool_result` / `llm_response` / `agent_completed` — иначе разбор фейлов будет невозможен.
- [ ] Запуск идёт из общего `venv/` в корне, не из отдельного окружения.
