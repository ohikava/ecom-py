# 017c — fraud-skill-tight

**Дата:** 2026-05-28
**Статус:** завершён (отрицательный результат)
**Автор/агент:** Ivan + Claude Opus 4.7 (1M context)
**Бранч/коммит:** `main @ f807e7b`
**Базлайн:** `017-skills-prototype-fraud` (66.18%) + `017b-016-rerun` (78.00%)

## Гипотеза

017 показал, что fraud skill активировался на 12/50 сессий (10 спурьезных
активаций на не-fraud задачах из-за слишком широкого `description`). Если
переписать description максимально жёстко («активируй ТОЛЬКО при буквальном
'fraud'/'Risk Ops'/'fraudulent'/'chargeback'»), over-activation упадёт,
не-fraud задачи перестанут регрессировать, и общий mean приблизится к 016
(78.32%) с сохранением fraud-выигрыша (+1 pp).

## Что меняем (diff vs 017)

Только `hermes_home/skills/ecom-fraud-forensic/SKILL.md` frontmatter:

```yaml
# было (017):
description: Use this skill when the task asks to identify fraudulent payment
records, fraud incidents, fraud hits, fraudulent transactions, or suspicious
payments... Triggers include "fraud", "fraudulent", "Risk Ops", "chargeback",
"fraud incident", "fraud hit", "suspicious payment", "anomaly"...

# стало (017c):
description: Behavioral fraud detection over archived payment records.
ACTIVATE ONLY when the task instruction text contains one of the literal
words "fraud", "fraudulent", "Risk Ops", or "chargeback" AND asks you to
identify specific payment records. DO NOT activate for: ordinary payment
recovery (3DS / card-security), refunds, basket checkout, catalog lookups,
customer verification, manager checks, store availability, count reports,
or any task that does not literally include one of those four trigger words.
If unsure, do NOT activate.
```

Тело скила (procedure, worked example, anti-patterns) — без изменений.

## Результат

| Метрика | 016 | 017b (rerun) | 017 (broad) | **017c (tight)** |
|---|---|---|---|---|
| Final | 78.32% | 78.00% | 66.18% | **75.69%** (49 task)¹ |
| Wins (1.0) | 39 | 39 | 32 | 36 |
| Skill activations | n/a | n/a | **12/50** | **5/50** |
| Wall-time | ~25 min | ~21 min | ~52 min | ~21 min |

¹ t48 повис на timeout, в финал не попал. С t48=0 score ≈ 74.18%.

**По fraud-блоку (один из основных целевых):**
| Slot | 016 | 017 | **017c** |
|---|---|---|---|
| t38 | 0.00 | 0.38 | **0.38** |
| t39 | 0.16 | 0.37 | **0.37** |
| t40 | 0.00 | 0.34 | **0.34** |
| t48 | 0.00 | 0.00 | timeout |

Fraud-выигрыш ровно тот же что в 017 — когда скил активирован на правильной
задаче, контент применяется идентично.

## Per-slot регрессии vs 017b (между 017b и 017c только skill добавлен)

| Slot | 017b | 017c | Loaded skill? |
|---|---|---|---|
| t13 | 1.00 | 0.00 | ❌ нет |
| t14 | 1.00 | 0.00 | ❌ нет |
| t41 | 1.00 | 0.00 | ❌ нет |
| t42 | 1.00 | 0.00 | ❌ нет |

**4 регрессии — ни одна не загружала скил.** Description-tightening сработал
(over-activation 12→5, и из 5 активаций 4 — реальные fraud-задачи). Но 4
phantom-регрессии указывают на **bloat tools spec** как индирекцию: даже когда
модель не вызывает `skill_view`, наличие 3 лишних тулов
(`skill_view`/`skills_list`/`skill_manage`) в системном промпте меняет
поведение DeepSeek на других задачах.

## Выводы

1. **Tight description работает** — over-activation упала в 2.4 раза.
2. **Но mean всё равно ниже baseline** на 2-4 pp. Сам факт включения
   `skills` toolset (3 лишних tool-def в системном промпте) сбивает
   DeepSeek на не-skill задачах.
3. **σ ≈ 0.32 pp** (по 017b vs 016), регрессия 017c — реальный эффект
   ≈7σ, не шум.
4. **Fraud-выигрыш +1 pp не компенсирует toolset-bloat −3 pp.**
   Net effect от добавления одного скила: отрицательный.

## Что дальше

Идея 017d: отключить `skill_manage` и `skills_list` из tools spec, оставить
только `skill_view`. Если модель всё равно может вызывать `skill_view` (имея
hardcoded знание о доступных скилах через системный промпт от hermes), то
3-tool → 1-tool может убрать большую часть индирекции.

Альтернативно: признать, что hermes-skills архитектура на DeepSeek-v4-pro
даёт net-negative и идти промпт-only путём (Phase 2 plan: A1/A5 через
post-process, не через prompt-rules).
