# Agent0 handoff: код блока 2 готов, закрыть evidence-gate

Статус блока 1: `Ready for Block 2` (исторический gate пройден). Внутренняя кодовая часть блока 2 (Identity и системный Hello World) реализована; сам блок 2 остаётся открытым до полного read-only snapshot Issue #1 и фактической сверки v1 evidence. Блок 3 не начинать. WEA vNext не подключена к live, v1 остаётся единственным рабочим протоколом и writer ledger. `[CHAT][CHECK][REVIEW]`

Техническая модель: `design 0.7`, `schema 0.7`; план: `tasks 1.0`. Активный OLED-пакет остаётся в `oled/changes/wea-vnext-recreation/`. `[DOC][CHECK]`

## Репозиторий и ветки

- Cached `origin/main`: `940c230aa3ce3ccd4067cd148c1d45cea1277792`; `git fetch origin` не прошёл из-за отсутствия неинтерактивной GitHub-аутентификации.
- Блок 1: `codex/wea-vnext-block1-protocol-core`, commit `47dd52e25c849c0a9d0508492a0dcb1c47ce9030`.
- Локальная интеграция блока 1: `codex/wea-vnext-integration`, merge commit `8ef2f6d`.
- Блок 2: `codex/wea-vnext-block2-identity-hello-world`, отдельный worktree от integration commit.
- Ничего не отправлено на GitHub; dirty main worktree не изменялся. `[CHECK]`

## Что реализовано

- `identity.py`: постоянный GitHub account ID, versioned account/Agent и control-group bindings, неизменяемый `base_agent_id`, общий resolver для Issue Form, ручной декларации и CLI.
- Block 1 executor `v0_6_0` и его manifest triple сохранены byte-for-byte; Block 2 добавлен отдельным `v0_6_1`, поэтому прежние Contracts продолжают replay старой closure.
- Common-control gate отклоняет участие того же Agent ID; authority повторно выводится из точного registry. Для общей группы selection и settlement разрешаются только после exact public disclosure, привязанной к Contract ID, Work ID и revision ID.
- `identity_hello_world.py`: постоянный `system_hello_world` только для Issue #1, нулевые bank/review/escrow/task effects, один account mint key и `42 WEA` только на `base_agent_id` после уникальной Work. Executor `v0_6_1` fail closed не активирует этот Contract, пока в следующей неизменяемой версии не закреплены permanent Issue ID и hash одобренного body из аутентифицированного snapshot.
- Hello World state закрепляет один канонический системный Contract. Mint требует точную revision декларации Agent0, действующую versioned binding роли `agent0` и решение о механической уникальности; caller-supplied boolean не является authority.
- System Contract принимает runtime triple только через per-load verifier capability внутри manifest-verified executor closure; после bind loader удаляет capability из module globals. Caller-supplied hashes, прямой импорт или вызов приватного binder не дают mint authority.
- `identity_migration.py`: чистый канонический план v1 restoration без ledger effects. Comment/revision/ledger/idempotency/alias evidence IDs нельзя повторно использовать между строками.
- v1 Hello World restoration помечает account mint key использованным без нового mint; одни evidence IDs нельзя предъявить для двух accounts.
- Root facades `identity.py`, `hello_world.py` и `migration.py` используют одну проверенную closure. Wheel smoke проверяет новые модули установленного пакета.
- Live Tide, v1-код, ledger, GitHub Issues, labels и workflows не изменялись. `[CHECK][REVIEW]`

## Runtime и проверки

Тройка Block 2 executor `v0_6_1`:

- ruleset SHA-256: `21538935ed5e0b3662589a3f631e8d7220ddc0bc12f7a182cb6c592b7848fa9b`;
- Tide interface: `0.6`;
- executor manifest SHA-256: `dc8298657c13202350d9394e9d198c6a0746dd9bbb230c48a254cad38cd7f2b2`.

Прежний `v0_6_0` manifest SHA-256 остаётся `8d2a71e15be535abbbd19eeb4c2b8909f29055f26c87989b26c3826c9f92b6b3`. `[CHECK][REVIEW]`

Последние локальные проверки на Windows: `26 passed, 16 skipped` для Identity/Hello World; skips — сохранённые поведенческие тесты, ожидающие аутентифицированный snapshot Issue #1. Packaging smoke `1 passed`; `154 passed, 18 skipped` для полного `tests/vnext`; Ruff и Pyright — PASS. Итоговый независимый review — `CLEAN` после fail-closed gate канонического Issue. Неработоспособный отдельный `register_account` удалён, атомарный onboarding выполняется только через `register_agent`. Итоговые команды находятся в `verification.md`. `[CHECK][REVIEW]`

## Следующий обязательный шаг блока 2

1. Получить аутентифицированный полный read-only snapshot Issue #1 до любой правки: exact body bytes/hash, все страницы `userContentEdits`, все комментарии, постоянные account/comment IDs и revision IDs.
2. Сверить фактическое число комментариев и не доверять старому числу `11` без нового evidence.
3. Сопоставить frozen GitHub evidence с v1 ledger history, idempotency keys и aliases; сформировать операторский набор `V1IdentityEvidence` и Hello World mint-use rows.
4. Любое противоречие account → `base_agent_id`, повтор evidence ID, неполная history или неоднозначный mint останавливает блок и требует решения оператора.
5. Read-only выгрузка и pure plan не разрешают запись в ledger/GitHub. Фактический импорт или mint требует отдельной разрешённой транзакционной границы; блок 3 до закрытия этой сверки не начинать. `[DERIVED][REVIEW]`

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
