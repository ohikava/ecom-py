# 014 — failures (smoke 10-task, прерван на t08)

7 завершённых trial из 10 запланированных, **все 7 = 0.0**. Категоризация:

## Категория A: Codex timeout (>540 s) — 6 / 7

Модель упирается в `CODEX_TIMEOUT_SEC=540` и не успевает выдать финальный JSON.
Прокси-лог показывает что DeepSeek активно делает 10-30 round-trips на одну
BitGN-задачу (каждый round-trip = один SSE-стрим reasoning + opt tool call).

| Task | Detail                                                          |
|------|-----------------------------------------------------------------|
| t01  | TIMEOUT (контраст: одиночный smoke t01 = 1.00)                  |
| t02  | TIMEOUT                                                         |
| t03  | TIMEOUT + answer без `<NO>`                                     |
| t04  | TIMEOUT                                                         |
| t06  | TIMEOUT + answer без `<NO>`                                     |
| t07  | TIMEOUT + answer без `<NO>`                                     |

**Корень:** DeepSeek V4 Pro через OpenRouter работает в 5-10× медленнее
gpt-5.4 (через Codex auth) на тех же задачах. Возможные подпричины:
- DeepSeek генерит длинные reasoning chains (видно `reasoning_tokens` > 0 в каждом запросе).
- OpenRouter latency overhead (responses-emulation поверх chat completions).
- Наш прокси добавляет +1 hop (но micro-overhead, не объясняет 10×).

**Что попробовать:**
- CODEX_TIMEOUT_SEC=1200, WORKERS=3 (014.1).
- Сократить системный prompt — 014 пока тащит весь prompt из 011 (32k), который
  тюнили под gpt-5.4. Возможно DeepSeek тратит много reasoning'a именно
  на разбор длинного prompt.
- `deepseek-v4-flash` вместо `pro` (014.4).

## Категория B: Format-violation — отсутствие `<YES>/<NO>` токенов (3 / 7)

t03, t06, t07 завершились (или почти) с правильным семантическим ответом, но
без обязательных токенов `<YES>` или `<NO>`. BitGN evaluator проверяет их
буквально:
```
detail: ["Answer should contain '<NO>'"]
```

В `/AGENTS.MD` правило явно прописано: *"When answering yes/no questions —
include `<YES>` or `<NO>` tokens in the response."* GPT-5.4 это правило
выполнял; DeepSeek игнорирует — отвечает "No, the product is not available"
без угловых скобок.

**Корень:** более слабый instruction-following у DeepSeek vs frontier-моделей
OpenAI/Anthropic. Также `--output-schema` (где раньше message — просто
строка) теперь отключён, значит мы не можем enforce'нуть `<YES>/<NO>` через
regex pattern в schema.

**Что попробовать:**
- Усилить пример в INSTRUCTIONS: показать конкретный required format ответа.
- Добавить post-process на стороне `codex_agent.py`: если evaluator-known
  yes/no задача и в message нет `<YES>`/`<NO>` — попытаться восстановить.
- Вернуть `--output-schema` со строгим pattern на message для yes/no задач
  (узкая heuristic).

## Категория C: Качество ответа (1 / 7)

t05 — один из двух non-timeout. Модель прошла полный цикл, сделала 5 MCP-вызовов,
вернула финальный JSON. Но evaluator потребовал конкретный SKU
`FST-1KPF96UD` в ответе, а DeepSeek нашёл и назвал другой матч.

**Корень:** возможно SKU randomization бенчмарка ИЛИ модель потеряла
правильный SKU при поиске. На 1 trial не достаточно сигнала, чтобы
делать выводы — нужны повторы.

## Категория D: НЕ наблюдалось

- **MCP не подключается** — больше не воспроизводится (proxy фиксит).
- **`OUTCOME=Pending`** — не воспроизводится после prompt-усиления + enum.
- **Crash в codex** — 0 / 7.
- **Schema validation errors** — 0 / 7 (`--output-schema` отключён, парсер `_extract_task_result_json` справился).

## Smoke t01 в одиночном прогоне vs bench

| Когда             | Score | Time | Note                                                  |
|-------------------|-------|------|-------------------------------------------------------|
| Одиночный smoke   | 1.00  | ~120s | 4 tool calls, чистый ответ                          |
| Bench (1-ая)      | 0.00  | TIMEOUT | Сетапы идентичны; стохастика DeepSeek               |

Воспроизводимость низкая. Это противоречит характеру первой попытки и
требует n=3-5 повторов для оценки реальной success rate.
