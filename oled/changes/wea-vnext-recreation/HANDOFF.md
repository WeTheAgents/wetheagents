# Agent0 handoff: интеграция Block 2 не готова к main

Статус блока 1: `Ready for Block 2` (исторический gate пройден). Статус интеграции: `Not ready`. Воспроизведённый обход canonical Issue gate через globals экспортированного Python-класса закрыт новым immutable executor `v0_6_2`: он навсегда fail closed и не содержит изменяемого sentinel; `v0_6_1` сохранён byte-for-byte. Block 2 остаётся открытым, потому что Agent0 decision/submission/disclosure ещё не выводятся из подтверждённых GitHub events и отсутствует полный read-only snapshot Issue #1. Блок 3 и merge в `main` не начинать. Проект поставлен оператором на паузу; scheduled Tide/auto-triage/claim-fast writers удалены, WEA vNext не подключена к live и не пишет в ledger или GitHub. `[CHAT][CHECK][REVIEW]`

Техническая модель: `design 0.7`, `schema 0.7`; план: `tasks 1.0`. Активный OLED-пакет остаётся в `oled/changes/wea-vnext-recreation/`. `[DOC][CHECK]`

## Репозиторий и ветки

- Свежий `origin/main`: `2337eeca75432baffc13be6bbf9c687b6cf98423`; `git fetch origin` прошёл 2026-07-27. Integration основана на `940c230` и отстаёт на четыре `btc-snapshot` commit; перед будущим publish требуется интеграция свежего main и повтор проверок.
- Блок 1: `codex/wea-vnext-block1-protocol-core`, commit `47dd52e25c849c0a9d0508492a0dcb1c47ce9030`.
- Локальная интеграция блока 1: `codex/wea-vnext-integration`, merge commit `8ef2f6d`.
- Блок 2: `codex/wea-vnext-block2-identity-hello-world`, commit `125898f`; объединён в integration merge commit `67f5a50`.
- Очистка устаревших baseline-контрактов тестов: `codex/wea-vnext-baseline-test-hygiene`, commit `19397f0`; объединена в integration merge commit `e5f900d`.
- Удаление общего claim и fail-closed pause legacy writers: integration commit `98413ec`.
- Security successor System Hello World `v0_6_2`: integration commit `4043290`.
- Интеграционная ветка: `codex/wea-vnext-integration`. Dirty main worktree не изменялся; ничего не отправлено на GitHub. `[CHECK]`

## Что реализовано

- `identity.py`: постоянный GitHub account ID, versioned account/Agent и control-group bindings, неизменяемый `base_agent_id`, общий resolver для Issue Form, ручной декларации и CLI.
- Block 1 executor `v0_6_0` и первоначальный Block 2 executor `v0_6_1` сохранены byte-for-byte. Security fix выпущен отдельным `v0_6_2`, поэтому прежние Contracts продолжают replay своих closure.
- Common-control gate отклоняет участие того же Agent ID; authority повторно выводится из точного registry. Для общей группы selection и settlement разрешаются только после exact public disclosure, привязанной к Contract ID, Work ID и revision ID.
- `identity_hello_world.py`: постоянный `system_hello_world` только для Issue #1, нулевые bank/review/escrow/task effects, один account mint key и `42 WEA` только на `base_agent_id` после уникальной Work. Текущий executor `v0_6_2` навсегда fail closed; permanent Issue ID и hash одобренного body могут появиться только в новой immutable версии после аутентифицированного snapshot.
- Hello World state закрепляет один канонический системный Contract. Mint требует точную revision декларации Agent0, действующую versioned binding роли `agent0` и решение о механической уникальности; caller-supplied boolean не является authority.
- System Contract принимает runtime triple только через per-load verifier capability внутри manifest-verified executor closure; после bind loader удаляет capability из module globals. Caller-supplied hashes, прямой импорт или вызов приватного binder не дают mint authority.
- `identity_migration.py`: чистый канонический план v1 restoration без ledger effects. Comment/revision/ledger/idempotency/alias evidence IDs нельзя повторно использовать между строками.
- v1 Hello World restoration помечает account mint key использованным без нового mint; одни evidence IDs нельзя предъявить для двух accounts.
- Root facades `identity.py`, `hello_world.py` и `migration.py` используют одну проверенную closure. Wheel smoke проверяет новые модули установленного пакета.
- Публичный общий `wea claim`, включая `--force`, milestone shim и GitHub `claim-fast` writer, удалён как отсутствующий в принятом vNext-контракте. Scheduled Tide и auto-triage writers удалены, поэтому операторская пауза fail closed. После будущего restart первая валидная Deliverable создаст Work; claim-подобный Duel join останется отдельным Duel-путём. Исторические v1 claim-chain/TTL/integrity проверки и ledger history сохранены read-only. `[CHAT][CHECK][REVIEW]`
- Изменение legacy Tide ограничено отклонением общего claim; существующий Duel claim-like путь сохранён. Ledger, GitHub Issues, labels и workflows не изменялись. `[CHECK][REVIEW]`

## Runtime и проверки

Тройка текущего Block 2 executor `v0_6_2`:

- ruleset SHA-256: `21538935ed5e0b3662589a3f631e8d7220ddc0bc12f7a182cb6c592b7848fa9b`;
- Tide interface: `0.6`;
- executor manifest SHA-256: `975b071d5bb49e14afd71d5b9c07d6113750884c1a9cc9c9b487324b71b100c7`.

Прежние manifest SHA-256 остаются: `v0_6_0` — `8d2a71e15be535abbbd19eeb4c2b8909f29055f26c87989b26c3826c9f92b6b3`, `v0_6_1` — `dc8298657c13202350d9394e9d198c6a0746dd9bbb230c48a254cad38cd7f2b2`. `[CHECK][REVIEW]`

Последние локальные проверки на Windows после authoritative-boundary hardening: полный suite — `4444 passed, 18 skipped, 11 xfailed`, без failures; полный `tests/vnext` — `159 passed, 18 skipped`; focused source/wheel gate — `32 passed`; claim/lifecycle/Tide/docs/start до successor — `126 passed`. Skips — сохранённые поведенческие тесты, ожидающие аутентифицированный snapshot Issue #1, и platform-specific проверки. Ruff, Pyright, compileall, doc-sync и ledger invariant — PASS. Повторный fresh-context review `v0_6_2` вернул пустой findings list. Итоговые команды находятся в `verification.md`. `[CHECK][REVIEW]`

## Следующий обязательный шаг блока 2

1. Получить аутентифицированный полный read-only snapshot Issue #1: exact body bytes/hash, все страницы `userContentEdits`, все комментарии, постоянные account/comment IDs и revision IDs.
2. Выводить Hello World submission, Agent0 decision и common-control disclosure только из принятых `GitHubEvent` внутри confirmed boundary; доказать actor, object/revision identity, exact body, effective time и глобальную одноразовость evidence IDs.
3. Сопоставить frozen GitHub evidence с v1 ledger history, idempotency keys и aliases; сформировать операторский набор `V1IdentityEvidence` и Hello World mint-use rows.
4. Любое противоречие account → `base_agent_id`, повтор evidence ID, неполная history или неоднозначный mint останавливает блок. Read-only выгрузка и pure plan не разрешают запись в ledger/GitHub; блок 3 до закрытия этих пунктов не начинать. `[DERIVED][REVIEW]`

## Команды повторной проверки

```powershell
python -m pytest tests/vnext/test_identity.py tests/vnext/test_hello_world.py -q
python -m pytest tests/vnext -q
ruff check src/wea_vnext tests/vnext
pyright src/wea_vnext
python -m pytest tests/vnext/test_packaging.py -q
python -m compileall -q src/wea_vnext
python scripts/check_invariant.py
git diff --check
```

## Когда остановиться

Остановиться, если нет полного revision history, невозможно доказать постоянный GitHub account ID, один account связан с противоречащими `base_agent_id`, старый mint нельзя однозначно восстановить либо дальнейший шаг требует внешнего движения WEA. Не закрывать OD-11, OD-14, OD-28 или OD-29 предположением. OLED-пакет не архивировать до реализации и проверки всего runtime. `[DERIVED]`
