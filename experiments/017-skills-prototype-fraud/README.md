# 017 — skills-prototype-fraud

**Дата:** 2026-05-28
**Статус:** завершён (отрицательный результат на mean, валидация механизма)
**Автор/агент:** Ivan + Claude Opus 4.7 (1M context)
**Бранч/коммит:** `main @ f807e7b (после 016)`
**Базлайн:** `016-hermes-fixes-phase1` (78.32% на 50 task)
**Модель:** `deepseek/deepseek-v4-pro` через OpenRouter
**Harness:** Hermes CLI с включённым native `skills` toolset

## Гипотеза

Если вынести fraud-forensic знание из монолитного `instructions.md` в отдельный
Hermes-скил с progressive disclosure (метаданные в системном промпте через
`skills_list`, полное содержимое — по запросу через `skill_view`), DeepSeek
автономно подключит его на fraud-задачах и поднимет их с 0/0/0.16 → ≥0.5 каждая.
Прототип валидирует механизм перед полным refactor'ом всех 10 доменов в скилы.

## Что меняем (diff vs 016)

1. **`hermes_home/config.yaml`**:
   - убрал `skills` из `disabled_toolsets`,
   - добавил `skills` в `platform_toolsets.cli` рядом с `bitgn-ecom`.
2. **`hermes_agent.py`**:
   - `-t bitgn-ecom` → `-t bitgn-ecom,skills` (запятая, не два отдельных `-t` —
     второй перетёр бы первый, наблюдалось эмпирически).
3. **`hermes_home/skills/ecom-fraud-forensic/SKILL.md`**:
   - YAML frontmatter `name` + `description` (≤1024 chars),
   - тело: behavioral fraud patterns (impossible-travel, rapid-fire device,
     cross-customer fingerprint sharing), worked example на cust_042 cluster,
     anti-patterns (никогда не CLARIFICATION на отсутствие fraud-флага,
     не цитировать baseline pay_001..pay_080).

## Результат

| Slot (fraud) | 015 | 016 | **017** | Δ vs 016 |
|---|---|---|---|---|
| t38 | 0.20 | 0.00 | **0.38** | +0.38 |
| t39 | 0.31 | 0.16 | **0.37** | +0.21 |
| t40 | 0.53 | 0.00 | **0.34** | +0.34 |
| t48 | 0.00 | 0.00 | 0.00 | 0 |

| Метрика | 016 | **017** | Δ |
|---|---|---|---|
| Final | 78.32% | **66.18%** | **−12.14 pp** |
| Wins (1.0) | 39 | 32 | −7 |
| Partial | 1 | 3 | +2 (all fraud) |
| Crashes | 0 | 0 | 0 |
| Wall-time | ~25 min | ~52 min | +108% |
| `skill_view` calls | n/a | 14 (12/50 sessions) | — |

## Выводы

1. **Гипотеза подтверждена частично.** Skill-механизм работает: DeepSeek
   автономно вызвал `skill_view('ecom-fraud-forensic')` на нужных задачах,
   применил behavioral patterns, поднял все 3 fraud-партиалы на +0.21–0.38.
2. **Но mean упал на −12.14 pp.** Скил активировался спурьезно на 10/12
   не-fraud задачах (description содержал слишком много триггеров: "payment",
   "archive", "customer"). Это съело budget на не-fraud задачах.
3. **Регрессии не объясняются только over-activation.** Из 7 потерянных
   слотов (1.0→0.0) только 1 (t14) реально загружал скил. Остальные 6 —
   variance + что-то ещё (см. 017b/017c для разбора).
4. **Wall-time 2× от 016.** `skill_view` тратит ~10–20s на задачу + есть
   доп. reasoning-цикл от расширенного tools spec.

## Следующие шаги

- [x] **017b** — повторить 016 без изменений, измерить σ. → σ ≈ 0.32 pp.
- [x] **017c** — узкий description ("активируй ТОЛЬКО при буквальном 'fraud' /
      'Risk Ops' / 'fraudulent'"). → 75.69%, over-activation 5/50 vs 12/50.
- [ ] **017d** — отключить `skill_manage` (модели не нужно создавать скилы) и
      возможно `skills_list`, оставить только `skill_view`. Проверить, не
      bloat ли tools spec даёт побочный эффект.
- [ ] Если 017d не закрывает регрессии — признать что skill-механизм
      требует слишком много compensating fixes и идти промпт-only путём.
