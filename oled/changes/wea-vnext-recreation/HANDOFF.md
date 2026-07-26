# Agent0 handoff: блок 1 завершён, начать Identity и Hello World

Статус: блок 1 реализован и проверен (`Ready for Block 2`). WEA vNext не подключена к live, а v1 остаётся единственным рабочим протоколом и writer ledger. `[CHAT][CHECK][REVIEW]`

Техническая модель: `design 0.7`, `schema 0.7`; план: `tasks 1.0`. `[DOC][CHECK]`

## С чего начать

1. Прочитать `verification.md`, затем блок 2 `tasks.md` и разделы Identity/Hello World в `spec.md`, `design.md` и `schema.md`.
2. Проверить, что текущая ветка содержит завершённый `src/wea_vnext/`, 128 проходящих тестов `tests/vnext` (плюс две Linux-регрессии, пропущенные на Windows) и тройку runtime из этого handoff.
3. Для блока 2 создать отдельную ветку и `worktree` от проверенного коммита блока 1. Если он уже опубликован и принят, использовать свежий `origin/main`; иначе явно перенести локальный коммит блока 1.
4. Выполнить только блок 2, закончить его тестами, self-roast и `codex exec review` до отсутствия замечаний. Блок 3 не начинать в том же PR. `[DOC][DERIVED]`

Повторный `git fetch origin` в сессии блока 1 не прошёл из-за отсутствия неинтерактивной GitHub-аутентификации. Локальный `origin/main` оставался на закреплённом в документации `940c230`; реализация выполнена в `codex/wea-vnext-block1-protocol-core`. Ничего не отправлено на GitHub. `[CHECK]`

## Что завершено в блоке 1

- `rulesets/0.6.json` и `executors/v0_6_0/` образуют неизменяемую стандартно-библиотечную смысловую замкнутость.
- Contract выбирает executor по точной тройке: ruleset SHA-256 `21538935ed5e0b3662589a3f631e8d7220ddc0bc12f7a182cb6c592b7848fa9b`, Tide interface `0.6`, manifest SHA-256 `8d2a71e15be535abbbd19eeb4c2b8909f29055f26c87989b26c3826c9f92b6b3`.
- Rules, payload, state и replay-байты детерминированы; replay использует точную runtime reference, возвращённую verifier, а exported incremental API пересобирает raw input и state классами выбранного executor. Для каждого разрешённого runtime-использования verifier загружает свежую проверенную closure вне обычного `sys.modules`; публичные facades сохраняют одну проверенную вселенную классов и исключений для стабильной Python-семантики. Подмена cache entry, parent-package binding или globals ранее выданной callable не отравляет последующее replay. State требует точную integer schema version, уникальные revision identities/idempotency keys и confirmed boundary, покрывающую каждое событие.
- Границы GitHub хранятся по неизменяемому `repository_id`; mutable `owner/name` остаётся только снимком boundary и не сохраняется в Event. `complete` требует настоящий boolean, opaque cursor не сортируется, порядок чтений задаёт положительный `read_sequence`, а подтверждённый boundary закрепляет точный batch hash и отклоняет расхождение. Равный sequence сравнивает hash до проверки capture time и создаёт устойчивый blocker; рост sequence не разрешает регрессию `captured_at`; неполная попытка не занимает sequence, поэтому полный retry той же границы остаётся допустимым.
- Выбор raw adapter fields выполняется внутри manifest-pinned executor; общий `store.py` только проверяет выбранную тройку, передаёт вход и оборачивает результат.
- Теневой writer допускает только `.wea_runs/vnext-shadow/`, отклоняет linked parent и Windows device names до внешнего создания, пишет private temp относительно проверенного directory handle, выполняет `fsync` и только затем атомарно публикует итоговое имя. Windows создаёт оба дочерних каталога относительно pinned non-reparse handles с запретом delete sharing. Linux до любого изменения ограничивает отдельный worker Landlock-правилом repo root, создаёт namespace относительно descriptors, использует `openat2` с `RESOLVE_BENEATH`/`RESOLVE_NO_SYMLINKS` и публикует hard-link через pinned shadow descriptor; неподдерживаемый POSIX fail closed.
- Wheel-тест доказывает package-data, изоляцию второго executor, игнорирование подложной копии старого manifest в чужом version package, исполнение только проверенных source bytes вместо bytecode cache и отказ принимать замену manifest, executor, ruleset либо parent import shim. Verifier отдельно сверяет версии ruleset path, содержимого ruleset и Tide interface; повреждённое глубокое дерево посторонней версии ограничивается итеративным traversal и не блокирует старый Contract. Непустые `semantic_dependencies` отклоняются fail closed, пока не существует проверки точных версий, установки и байтов зависимостей.
- Реестр содержит все 55 ID Spec. Последний review исправил порядок same-sequence conflict перед capture-time regression и закрыл непроверенные semantic dependencies; после регрессий, manifest sync и повторной независимой проверки пакет даёт `128 passed`, `2 skipped`, а review — `CLEAN`. `[CHECK][REVIEW]`

## Точная граница блока 2

Реализовать версионированные Identity-привязки постоянного GitHub account ID к Agent ID и `control_group_id`, неизменяемый `base_agent_id`, общий валидатор авторства и системный Contract `system_hello_world` только для Issue #1. Восстановление участников v1 должно использовать сохранённые Issue/comment/revision IDs, ledger history, idempotency keys и aliases; уже полученный mint не повторяется. `[CHAT][DERIVED]`

Перед любой правкой Issue #1 сначала получить полный read-only snapshot body, всех страниц `userContentEdits`, 11 известных комментариев, постоянных account/comment IDs и текущих hashes. Недоступная или неполная история блокирует внешний adapter, но не даёт права подменить revision ID одним `updatedAt`. `[CHECK][DERIVED]`

Проверка блока 2 по плану: `python -m pytest tests/vnext/test_identity.py tests/vnext/test_hello_world.py -q`, затем весь `tests/vnext`, `ruff check src/wea_vnext tests/vnext`, wheel smoke и ledger invariant. `[DOC][DERIVED]`

## Что не делать

- Не подключать `scripts/tide.py` или будущий `scripts/tide_vnext.py` к live.
- Не писать в рабочий ledger, GitHub Issues, labels или workflows.
- Не начислять `42 WEA` и не мигрировать участников по неполному snapshot.
- Не начинать Contract activation блока 3, профильные Work, payout или bootstrap.
- Не закрывать OD-11, OD-14, OD-28 или OD-29 догадкой. `[CHAT][DERIVED][REVIEW]`

## Известный baseline

Новый пакет даёт `128 passed`, `2 skipped` на Windows; skips — две исполняемые только на Linux регрессии rename-race. Свежий общий suite без предсуществующего collection blocker даёт `4400 passed`, `28 failed`, `2 skipped`, `2 xfailed`; набор 28 имён падений не изменился и целиком присутствует на чистом `origin/main`, где контрольный запуск дал `4271 passed`, `29 failed`, `2 xfailed`, включая дополнительный heartbeat CLI. Отдельно `tests/test_check_task_escrow_sync.py` импортирует отсутствующий `run_checks` уже на `origin/main`. Эти сбои не относятся к vNext и не должны расширять scope блока 2. `[CHECK]`

## Когда остановиться и спросить

Остановиться нужно, если невозможно доказать постоянный GitHub account ID или полную revision history, один account уже связан с противоречащими `base_agent_id`, старый mint нельзя однозначно восстановить либо блок 2 требует внешнего движения WEA. Вопрос фиксируется в OLED-документации с источником, а не решается скрытым допущением. `[DERIVED]`

Активный OLED-пакет остаётся в `oled/changes/wea-vnext-recreation/`; архивировать его можно только после реализации и проверки всего runtime. `[CHECK][DERIVED]`
