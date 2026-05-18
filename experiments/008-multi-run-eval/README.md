# 008 — multi-run-eval

**Дата:** 2026-05-18
**Статус:** частично завершён (2/3 валидных run; quota-limit прервал run 3)
**Автор/агент:** Ivan + Claude Opus 4.7
**Бранч/коммит:** `main @ after-007 (e8e5cdb) + WORKERS patch`
**Базлайн:** `007-codex-discount-refs` (77.01% на одном прогоне)
**Модель:** `gpt-5.4` через Codex CLI 0.130.0

## Гипотеза

Если прогнать 007 baseline **N=3 раза** с тем же scaffolding'ом (WORKERS=3 для скорости), мы получим эмпирическую оценку σ aggregate score и per-task pass rate. Ожидание: **σ ≈ 1.5–3.5 pp**. С этим числом мы получим threshold для интерпретации последующих маленьких prompt-эксп ([0..2σ] = шум, [>2σ] = реальный сигнал).

Это measurement experiment, не agent change. **`agent/` папки тут нет** — используем напрямую `experiments/007-codex-discount-refs/agent/`, никаких изменений в prompt'е, MCP-сервере или scaffolding.

## Что меняем (relative 007)

**Только scaffolding-патч в 007's `main.py`** (применён в этом же коммите, не отдельный эксперимент): добавлен `WORKERS=N` env-knob через `ThreadPoolExecutor`. Defaults to 1 (sequential, byte-identical к 007 первому прогону). `JsonlDebugLogger.log()` теперь под threading lock'ом для безопасной concurrent записи.

`run_agent` / `codex_agent.py` / `ecom_mcp_server.py` / prompts — **без изменений**. Параллельность только в trial-loop.

Smoke на 4 задачах (t01-t04, WORKERS=3) дал 100% score, output корректно интерливится с `[task_id]` префиксами. Race-condition тест прошёл.

## Структура

```
experiments/008-multi-run-eval/
├── README.md            # этот файл
├── aggregate.py         # парсит results/run*.jsonl, считает stats, пишет summary.md
└── results/
    ├── run1.jsonl       # JSONL из 1-го прогона
    ├── run2.jsonl       # из 2-го
    ├── run3.jsonl       # из 3-го
    └── summary.md       # generated, per-task + aggregate stats
```

## Протокол

3 прогона baseline'а 007 sequential между прогонами (чтобы не путать confounder'ы — каждый прогон независимый full benchmark), но **внутри прогона** используем `WORKERS=3` для скорости.

```bash
source /Users/ivan/Documents/ai/ecom-py/venv/bin/activate

# Из директории 007 (используем её main.py и MCP конфиг как есть)
cd /Users/ivan/Documents/ai/ecom-py/experiments/007-codex-discount-refs/agent

# Прогон 1
MODEL_ID=gpt-5.4 WORKERS=3 python -m main
# rename последний созданный JSONL → 008/results/run1.jsonl

# Прогон 2 (отдельный bench run, новые randomized instructions)
MODEL_ID=gpt-5.4 WORKERS=3 python -m main
# → run2.jsonl

# Прогон 3
MODEL_ID=gpt-5.4 WORKERS=3 python -m main
# → run3.jsonl

# Аггрегировать
cd /Users/ivan/Documents/ai/ecom-py/experiments/008-multi-run-eval
/Users/ivan/Documents/ai/ecom-py/venv/bin/python aggregate.py
```

## Ожидаемые числа

| Метрика | Ожидание |
|---|---|
| Wall time per run (WORKERS=3) | 10–14 минут |
| Wall time 3 прогона sequential | 30–45 минут |
| Cost per run (cached pricing) | ~$30 |
| Cost 3 прогона | ~$90 |
| σ aggregate score | 1.5–3.5 pp |
| 95% CI half-width (n=3) | ±1.7–4 pp |
| always_pass (k=3) | ≥22 задач (стабильные t01-t12, etc.) |
| always_fail (k=0) | t31 (cat C structural), потенциально t14/t15/t16 (cat A) |
| flaky (0<k<3) | ~5–10 задач |

## Verification

1. Smoke с WORKERS=3 на 4 задачах прошёл (см. выше).
2. `JsonlDebugLogger` thread-safe (`threading.Lock` обёрнут вокруг write+flush).
3. Three full runs successfully produce three valid `runN.jsonl` files.
4. `aggregate.py` runs without exceptions and writes `summary.md`.

## Метрики (n=2, run 3 corrupted by quota)

Run 1 + Run 2, оба с WORKERS=3 на 42-task бенчмарке (BitGN расширил с 40 до 42).
Третий прогон **прерван ChatGPT daily usage limit** на задаче t13 — 30 последующих задач имели `codex exec rc=1` с 0 tokens. Файл перенесён в `results/corrupted/run3-ratelimit.jsonl`.

Сообщение от Codex CLI: `"You've hit your usage limit. ... try again at 11:00 PM."` — суточная квота через `codex login` (ChatGPT Plus/Pro), а не транзиентный rate limit.

| Run | Score | Hard wins / Total | Wall time |
|---|---|---|---|
| Run 1 | 62.56% | 26 / 42 | ~11 min |
| Run 2 | 67.11% | 28 / 42 | ~13 min |
| ~~Run 3~~ | (21.43% после quota cliff) | — | — |
| **Mean (n=2)** | **64.83%** | — | — |
| **StDev (n=2)** | **3.22 pp** | — | — |
| **95% CI** | **±4.46 pp** (very wide на n=2) | — | — |

## Главные findings

### 1. Большая дисперсия между прогонами

Range run1↔run2 = 4.55 pp, σ = 3.22 pp на n=2. На n=2 эта оценка очень неточная (95% CI на саму σ огромная), но порядок величины уже информативен.

### 2. **007 single-run (77.01%) — outlier минимум на 3σ от 008 mean**

007 single-run gave 77.01%. 008 2-run mean = 64.83%, σ ≈ 3.22 pp → 77.01% это +12.18 pp выше mean, или ~3.8σ выше.

Это **либо**:
- **(A)** Бенчмарк server-side изменился между 2026-05-17 (007 run) и 2026-05-18 (008 runs). Поддерживается тем, что bench вырос с 40 → 42 задач, и **t11/t12 always-fail в 008 но always-pass в 005-007**, и **t38/t39/t40 partial scores схлопнулись** (0.54/0.19/0.07 → 0.08/0.07/0.08). Это похоже на server-side изменение difficulty или scoring.
- **(B)** WORKERS=3 parallel mode systematically хуже WORKERS=1 sequential. Race conditions, hidden rate-limit retries, MCP-server contention.
- **(C)** 007 single-run был lucky +3.8σ outlier. Маловероятно, но возможно при больших σ.

**Гипотеза (A) — наиболее вероятная** (физически наблюдаемое изменение bench), но (B) тоже требует проверки.

### 3. Параллелизация эмпирически попадает в quota раньше

3 прогона × 42 задачи × ~11 запросов/задачу ≈ 1300 codex exec request blocks за ~30 минут. Это превысило ChatGPT daily quota. На WORKERS=1 sequential тот же total cost, но за 80 минут — могло уложиться в rate buckets.

Парallel пять раз ускоряет fill rate квоты. **Дальнейшие experiments → ограничивать запуски в окне 24h**.

### 4. Категоризация задач (n=2)

- **always_pass (25 tasks)** — стабильное ядро: t01-t08, t17-20, t22-24, t26-27, t29-30, t32-37. Score=1.0 в обоих runs.
- **always_fail (13 tasks)** — t11, t12, t13-16, t25, t28, t38-42. Score=0 или partial<0.1 в обоих runs. Это **real failure categories**, не randomization шум.
- **flaky (4 tasks)** — t09, t10, t21, t31. Score=1.0 в одном run, =0 в другом.

t11, t12 — **новая систематическая failure** (always-pass в 005-007 → always-fail в 008). Сильный сигнал что bench изменился (или parallel mode хуже на этих специфических задачах).

t31 — был always-fail в 005-007 (структурный outcome mismatch), стал flaky в 008. Видимо randomization дала форму задачи без emotional pressure, модель ответила OK.

## Результат

**Headline на n=2**: 64.83% ± 3.22 pp.

**Реинтерпретация прошлых экспериментов:**

| Эксперимент | Single-run | Probable real | Confidence |
|---|---|---|---|
| 005 baseline (gpt-5.4 + Codex) | 64.52% | ~63-66% | high — близко к 008 mean |
| 006 refs-fix (overlap) | 77.42% | 70-74% (?)... | medium — bench shifted |
| 007 discount-refs | 77.01% | unclear | low — outlier vs 008 |
| 008 mean | 64.83% | true on новом 42-task bench | medium (n=2) |

Все single-run цифры до 008 теперь под подозрением. Bench-shift confounder делает прямое сравнение exp-to-exp ненадёжным.

## Выводы

1. **σ ≥ 3 pp подтверждена.** На n=2 это lower bound; реальная σ может быть выше. **2σ threshold для интерпретации новых fix'ов ≥ 6 pp.** Маленькие +2-5 pp fix'ы из прошлой очереди (007, 009-discount, 010-probing) **в зоне шума на single-run measurement** — нужны 3+ повтора.

2. **Bench-shift between 007 and 008 — likely.** Объяснение чтобы +12 pp gap без изменения scaffolding'а. Без знания этого мы могли бы потратить ещё несколько экспериментов гонясь за призраком регрессии. Сейчас **ясно: новый bench-baseline = 008's ~65%**, не 007's 77%.

3. **Quota-bound research.** ~80 codex exec total per day на ChatGPT Plus/Pro. 1 эксперимент = 42 задачи × 1 run = 42 exec. То есть **максимум ~2 эксперимента/день** при single-run. Для σ-based интерпретации (3 runs) **<1 эксперимент/день**. Это сильное ограничение на cadence.

4. **WORKERS=3 параллельное mode валидно функционально**, но quota fillrate × 3-4. Параллелизация ускоряет wall time, не cost. Стратегически: оставить для эксперимента, использовать в основном для re-run baseline'а после prompt change.

## Следующие шаги

- [ ] **Дождаться quota reset (23:00) и сделать Run 3 + Run 4** — увеличить n до 4 для лучшей σ. Также: один из этих прогонов сделать с WORKERS=1 (sequential), чтобы разграничить **(A) bench-shift** vs **(B) parallel-mode regression**.
- [ ] **Решить про bench-shift**: если runs 3-4 подтвердят 008 mean ~65%, признать что наш текущий honest baseline это 65%, а не 77%. Обновить INDEX с замечанием про bench-version drift.
- [ ] **Recalibrate experiment ROI**: prioritize fix'ы с potential ≥ 6 pp (always-fail tasks, mechanistic fixes), depreciate prompt nudges с potential <5 pp.
- [ ] **009-codex-probing-silent** оставить как идея но запускать только после установления stable baseline на новом 42-task bench.
- [ ] **Опциональный 008b** — после quota reset, run на WORKERS=1 sequential 42-task для прямого сравнения с parallel.

## Артефакты

- `results/run1.jsonl`, `results/run2.jsonl` — валидные прогоны
- `results/corrupted/run3-ratelimit.jsonl` — quota-prerванный прогон, сохранён как evidence
- `results/summary.md` — generated by `aggregate.py`
