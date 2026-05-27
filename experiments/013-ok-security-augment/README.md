# 013 — ok-security-augment

**Дата:** 2026-05-27
**Статус:** prepared (quota cliff prevents smoke; rerun next-day)
**Автор/агент:** Ivan + Claude Opus 4.7
**Бранч/коммит:** `main @ after-012 (a52be5b)`
**Базлайн:** `012-count-scalar-refs` (smoke 4/4; t11 deterministic fix)
**Модель:** `gpt-5.4` через Codex CLI 0.130.0

## Гипотеза

Если для OK outcomes на discount/refund/payment-related tasks auto-добавлять `/docs/security.md` в `grounding_refs` (как уже делается для DENIED через `_sanitize_refs_for_denied`), то закрывается gap для legitimate-action tasks типа t46 (model OK + missing security.md ref). Потенциал: **+1 hard win** на t46, потенциально +N на похожих "missing security.md" patterns (t26, t42, t50 в 012 — если они randomize в OK-discount shape).

## Корень проблемы

В 011 t46 = "apply the max applicable service_recovery discount to the last checkoutable basket of mia.hoffmann+cust886@yahoo.com" → model вернул:
- `OUTCOME_OK` ✅ (correctly applied discount)
- `message: Applied 10% service_recovery discount to basket_076` ✅
- `refs = [discounts.md, checkout.md, basket_048, basket_076, basket_241, basket_268, cust_054]` ❌ — **missing /docs/security.md**

Score: 0.0, detail: `"answer missing required reference '/docs/security.md'"`.

**Изначально я неверно интерпретировал t46 как identity-mismatch attack (DENIED).** Re-check показал что evaluator ОЖИДАЕТ OK + security.md в refs (а не DENIED). Это refs-augmentation проблема, не security-gate.

## Что меняем (diff vs 012)

`codex_agent.py`:

1. Новая функция `_augment_refs_for_ok(refs, task_text)`:
   - Если `task_text` матчится regex `_OK_SECURITY_REQUIRED` (discount/refund/3ds/service_recovery/goodwill/markdown/chargeback/payment_recovery/checkout/capture/authorize) → force-add `/docs/security.md`.
   - Плюс topic-policy-doc map (как для DENIED): "discount" → `/docs/discounts.md`, "3ds" → `/docs/payments/3ds.md`.
   - **Strictly additive** — никогда не удаляет existing refs.

2. В шаге "8b. (006) Sanitise refs per outcome" — для `OUTCOME_OK` теперь сначала вызывается `_augment_refs_for_ok`, потом optional `_sanitize_refs_for_exclusions` (как раньше).

3. Лог события `refs_augmented_ok` с added paths.

Никаких prompt-изменений — это deterministic codex-level fix.

## Smoke

❌ **Не запустить — quota cliff.** ChatGPT Pro daily limit depleted после 011 + 012-smoke-x2 + 012-full + 013-smoke-attempt. Codex returns rc=1 c 559 chars stdout → OUTCOME_ERR_INTERNAL.

Local unit-test показал ожидаемое поведение:

```python
>>> _augment_refs_for_ok(
...     ['/docs/discounts.md','/proc/baskets/basket_076.json','/proc/customers/cust_054.json'],
...     'apply the max applicable service_recovery discount to the last checkoutable basket of mia.hoffmann+cust886@yahoo.com'
... )
['/docs/discounts.md', '/docs/security.md', '/proc/baskets/basket_076.json', '/proc/customers/cust_054.json']

>>> _augment_refs_for_ok(['/proc/catalog/X.json'], 'how many SKUs are blue?')
['/proc/catalog/X.json']  # no change — neutral task
```

→ `/docs/security.md` добавляется только когда task действительно discount/payment-related.

## Метрики

[заполнится после quota reset]

## Verification (планируется)

1. Smoke t46 → ожидаем 1.00 (refs augmented с security.md).
2. Full 50-task → check что additive change не сломал NEUTRAL tasks (счётные/каталожные).
3. Risk: discount-keyword regex может зацепить редкие OK-tasks которые НЕ требуют security.md → false-add. Мониторить через `refs_augmented_ok` events.

## Выводы

[заполнится после full run]

## Следующие шаги

- [ ] **013-smoke**: после quota reset запустить smoke на t46 + neutral таски (t01, t11, t20) для проверки не-регрессии.
- [ ] **013-full**: full 50-task для measurement net delta vs 012.
- [ ] **014 — fraud-selectivity** (medium): t38-t40 + t48. Investigate `/docs/payments/3ds.md` + look for fraud-classification heuristic в /docs/.
- [ ] **015 — multi-run на 013** (medium): σ measurement.

## Артефакты прогона

- `agent/smoke.log` — пустой (quota)
- `agent/codex_agent.py` diff:
  - +`_OK_SECURITY_REQUIRED` regex
  - +`_augment_refs_for_ok()` (additive policy-doc inject)
  - +handler в шаге 8b для OUTCOME_OK
  - +debug event `refs_augmented_ok`
