# Agent0 handoff: inactive vNext в main, Block 2 evidence открыт

В `main` опубликован проверенный, но неактивный внутренний пакет WEA vNext: Block 1 завершён, внутренняя кодовая часть Block 2 реализована. Block 2 не закрыт — нет аутентифицированного полного snapshot Issue #1 и factual reconciliation с v1 evidence. Block 3, live Tide, ledger/GitHub writes, migration и bootstrap не разрешены. OLED-пакет остаётся активным. `[CHAT][CHECK][REVIEW]`

Статус Block 1: `Ready for Block 2`. Техническая модель: `design 0.7`; schema `0.7`; план `tasks 1.0`. `[CHECK]`

Постоянная карта границы: `docs/VNEXT_BOUNDARY.md`. Если непонятно, где менять логику, сначала использовать её, затем `spec.md` и сценарный ID; исторический Contract всегда replay по сохранённой тройке, а не по «последней» версии executor.

## Репозиторий и интеграция

- Рабочая ветка: `codex/wea-vnext-integration`.
- Boundary commit: `d79aa42961671e6acc0812a5f06569e7a6d05acd`.
- Свежий интегрированный `origin/main`: `3d310081f398c2927a46278b472e84dec2a54105`.
- Merge commit перед финальным handoff: `bb3f40d`.
- Publish target: commit, содержащий этот handoff; проверить через `git rev-parse origin/main` после fetch.
- Другой локальный worktree с checkout `main` содержит пользовательские незакоммиченные файлы и намеренно не изменялся. Remote `main` — источник истины для продолжения. `[CHECK]`

## Что находится в main

- Immutable executors `v0_6_0`, `v0_6_1` и security successor `v0_6_2`; старые executor closures при boundary-hardening не менялись.
- Manifest-verified replay, deterministic state transition, shadow-only storage и реестр всех 55 BDD-сценариев Block 1.
- Versioned Identity, common-control disclosure, fail-closed System Hello World и pure v1 migration plan внутренней части Block 2.
- `installed_executor(version)` без default и с canonical dotted-semver validation. Исторические тесты явно называют `0.6.0`; candidate facades declarations/identity/Hello World/migration/projection используют одну closure `0.6.2`.
- PR guard `.github/workflows/guard-vnext-boundary.yml` запускает narrow boundary tripwire на disposable `windows-latest` runner.
- Legacy baseline-тесты пересмотрены: устаревшие контракты удалены или переписаны под принятую pause/no-general-claim семантику; production code не утяжелялся ради старых ожиданий.

## Точная граница v1 / vNext

- Наличие `src/wea_vnext/` в `main` не активирует vNext. `scripts/tide_vnext.py`, `ledger/vnext/` и vNext epoch отсутствуют.
- Scheduled v1 Tide, Agent0 loop, auto-triage и claim-fast остановлены/удалены. Однако прямые legacy CLI и maintenance writers ещё вызываемы: текущая пауза операторская, не общий code-enforced epoch guard. Не запускать эти mutation paths.
- Общий claim удалён; после будущего restart первая валидная Deliverable создаёт Work. Duel join остаётся отдельной механикой.
- Автор будущего Final пишет выбор обычным текстом; только формальная декларация Agent0 меняет protocol state. Legacy `accept`/`ranking`/transform syntax не является активной vNext-инструкцией.
- Boundary tripwire ловит literal vNext references в CLI/scripts/workflows/package entry points и отсутствие известных adapter/namespace. Он не доказывает отсутствие dynamic/renamed writer. Полный writer inventory и behavioral no-write proof остаются обязательным Block 9 activation gate.

## Свежие проверки после integration

- Полный suite: `4453 passed, 18 skipped, 11 xfailed`.
- `tests/vnext`: `168 passed, 18 skipped`.
- Boundary regression: `9 passed`.
- Ruff: PASS.
- Pyright `src/wea_vnext`: `0 errors, 0 warnings`.
- Compileall: PASS.
- Ledger invariant: PASS, `19025 = 10000 + 9025`; active escrow `0`.
- Ledger schema и doc sync: PASS.
- Frozen executors: `git diff --exit-code a22edf2 -- src/wea_vnext/executors` — PASS.
- HTML manifest и внутренние ссылки пересобраны и проверены.
- Последняя независимая fresh-context boundary проверка: `[]`. `[CHECK][REVIEW]`

## Следующий обязательный шаг: завершить Block 2

1. Получить аутентифицированный полный read-only snapshot GitHub Issue #1: exact body bytes/hash, все страницы `userContentEdits`, все комментарии, постоянные account/comment IDs и revision IDs.
2. Выводить Hello World submission, Agent0 decision и common-control disclosure только из принятых `GitHubEvent` внутри confirmed boundary; доказать actor, object/revision identity, exact body, effective time и глобальную одноразовость evidence IDs.
3. Сопоставить frozen GitHub evidence с v1 ledger history, idempotency keys и aliases; сформировать операторский набор `V1IdentityEvidence` и Hello World mint-use rows.
4. Повторить независимый review и verification. До закрытия этих пунктов не начинать Block 3 и не добавлять live adapter или writer.

Любое противоречие account → `base_agent_id`, повтор evidence ID, неполная history или неоднозначный mint останавливает Block 2. Read-only capture и pure plan разрешены; записи в ledger/GitHub — нет. OD-11, OD-14, OD-28 и OD-29 остаются открытыми и не закрываются предположением. `[DERIVED][REVIEW]`

## Быстрый повтор gate

```powershell
$env:PYTHONPATH='src'
python -m pytest tests/vnext -q --tb=short
python -m pytest -q --tb=short
ruff check src/wea_vnext tests/vnext
pyright src/wea_vnext
python -m compileall -q src/wea_vnext
python scripts/check_invariant.py
python scripts/check_ledger_schema.py
python scripts/check_doc_sync.py
git diff --check
```
