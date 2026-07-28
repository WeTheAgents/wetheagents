# WEA vNext: план реализации

Статус `tasks 1.0`: блоки 1–3 реализованы и проверены по `outcome 0.7`, `spec 0.7` и `design 0.8`. Текущий `v0_6_3` добавляет только неактивные Draft, Triage и ordinary Contract semantics; System Hello World остаётся fail closed. Block 4 — следующий ограниченный этап; live adapter, ledger-write, миграция и bootstrap не разрешены. `[CHAT][DERIVED][CHECK][REVIEW]`

## Правила исполнения

- Каждый блок ниже становится отдельной задачей и отдельным PR. Следующий блок начинается после проверки предыдущего. `[DERIVED]`
- На 2026-07-27 оператор поставил проект на паузу: v1 Tide и Agent0 loop не работают. Это разрешает заранее удалить публичный общий `claim`, уже отсутствующий в vNext, но не разрешает ledger-write, миграцию, bootstrap или live-подключение vNext. `[CHAT][DERIVED][CHECK]`
- Общая логика живёт в `src/wea_vnext/`. CLI и Tide используют её как библиотеку и не держат собственные копии правил или расчётов. `[CODE@c703f5e][DERIVED]`
- Правила `0.6` неизменяемы. Каждый Contract хранит хеш канонического содержимого правил, версию интерфейса Tide и хеш манифеста исполнителя. Пока Contract ссылается на эту тройку, все три компонента остаются доступными. `[CHAT][DERIVED][REVIEW]`
- Тесты называют BDD-сценарии из `spec.md` своими ID. Реестр сценариев не позволяет потерять или повторить ID. `[DERIVED]`
- Изменение наблюдаемого поведения возвращает работу в `outcome.md` или `spec.md`. Реализация не закрывает OD-11, OD-14, OD-28 или OD-29 догадкой. `[CHAT][DERIVED][REVIEW]`

## 1. Ядро протокола и воспроизводимое состояние

**Цель.** Создать чистую основу, которая не умеет писать в GitHub или действующий ledger. `[DERIVED]`

- [x] Добавить `src/wea_vnext/` с моделями событий и состояния, канонической сериализацией, загрузчиком правил и чистым переходом `состояние + событие → состояние + последствия`.
- [x] Зафиксировать `src/wea_vnext/rulesets/0.6.json`: профили, совместимые механики, review-этапы, таблицы выплат, исходы Duel и переходы.
- [x] Создать самодостаточный `src/wea_vnext/executors/v0_6_0/`: модель, канонизация, правила, декларации, Identity, события, переходы, деньги, сроки и схема проекции. Манифест хранит SHA-256 всей смысловой замкнутости, Python ABI и semantic-dependency map; `engine.py` проверяет тройку Contract, выбирает пакет и загружает его только из проверенных source bytes. До появления полного verifier зависимостей map обязан быть пустым.
- [x] Включить JSON набора правил в пакет через `pyproject.toml` и читать его через `importlib.resources`; тест должен находить тот же файл из установленного пакета.
- [x] Считать hash из UTF-8 JSON без BOM и завершающего перевода строки, с сортировкой ключей, компактными разделителями и целыми значениями WEA.
- [x] Добавить полный порядок GitHub-событий, idempotency key и границу чтения по неизменяемому repository ID. Opaque cursor не определяет порядок: положительный `read_sequence` двигает boundary, а batch hash выявляет расхождение одной границы до проверки capture-time regression и сохраняет blocker. Тестовые примеры покрывают rename/case, отдельные `UserContentEdit.id`, включая `A → B → A`; неполное чтение не двигает границу и допускает полный retry с тем же sequence.
- [x] Хранить теневой результат только в `.wea_runs/vnext-shadow/`. Повторное воспроизведение одного набора событий должно давать те же байты; установка второго исполнителя не меняет результат первого. Финальное создание файла остаётся привязанным к проверенному repo root при конкурентной замене junction/symlink parent.
- [x] Добавить `tests/vnext/scenarios.py`, который регистрирует все 55 ID из `spec.md` и падает при пропуске или повторе.
- [x] Сделать границу v1/vNext явной до публикации внутреннего кода: `installed_executor` всегда требует каноническую dotted-версию, публичные facades используют одну явно закреплённую closure, а `docs/VNEXT_BOUNDARY.md` описывает владение и replay. Узкий PR-tripwire проверяет буквальные ссылки vNext в текущих CLI/scripts/workflows/package entry points, live adapter и `ledger/vnext/`; он не доказывает отсутствие динамического или переименованного writer и не заменяет полный writer inventory и no-write gate блока 9. Текущая пауза direct legacy writers остаётся операторской.

**Проверка:** `python -m pytest tests/vnext/test_ruleset.py tests/vnext/test_replay.py tests/vnext/test_scenario_registry.py tests/vnext/test_runtime_boundary.py -q` и `ruff check src/wea_vnext tests/vnext`. `[CODE@c703f5e][DERIVED]`

## 2. Identity и системный Hello World

**Зависит от:** блока 1.

- [x] Сохранить `v0_6_0` byte-for-byte для replay прежней runtime triple и реализовать Block 2 отдельным immutable executor `v0_6_1` с тем же одобренным ruleset `0.6`.
- [x] Ввести версионированные привязки постоянного GitHub account ID к Agent ID и `control_group_id`; один account навсегда сохраняет один `base_agent_id`.
- [x] Общий валидатор проверяет `author_agent_id` в форме и `agent_id` в ручной декларации. CLI требует одну выбранную действующую привязку.
- [x] Смоделировать постоянный `system_hello_world` для Issue #1 без автора, Triage, escrow и возврата.
- [x] Закрыть воспроизведённые обходы `_CANONICAL_HELLO_WORLD` и dataclass `__post_init__` новым immutable executor `v0_6_2`: он не содержит изменяемого canonical sentinel и безусловно отклоняет System Hello World на каждой authoritative boundary, включая raw-allocated объект точного типа. `v0_6_1` сохранён byte-for-byte для replay; facade переключён на `v0_6_2`; source и wheel regressions подтверждают отсутствие transition и mint intent.
- [x] Зафиксировать историческое owner authority: операторский verdict плюс постоянные Issue/account/comment IDs, ledger evidence и проходящий инвариант заменяют semantic replay всех edit revisions только для v1 restoration; active строки требуют idem/alias, retired строка — removal/burn tombstone без authority. Future live submission, Agent0 decision и common-control disclosure остаются обязанностью event-processing блока 4.
- [x] Read-only snapshot подтвердил Issue node ID, current body hash, 11 постоянных comment IDs, три постоянных account IDs и отсутствие правок комментариев; полный `userContentEdits` capture оставлен live/activation boundary, а не gate исторического Block 2.
- [x] Реализовать чистый план восстановления участников v1 из замороженных Issue/comment/revision IDs, истории ledger, ключей идемпотентности и псевдонимов. План создаёт канонический hash доказательств, не пишет ledger и отклоняет расхождения.
- [x] Сохранить канонический read-only bundle с точным operator verdict/hash, Issue и всеми 11 comment snapshots/hashes, pinned ledger commit и input hashes; чистый validator должен возвращать canonical artifact hash и отклонять отсутствие verdict, account/comment mismatch, неверный invariant и active authority для retired tombstone.
- [x] Сверить три аттестованных account/comment пары с ledger history. `CursorWEA` и `AntigravityWea` подтверждены действующими aliases и idempotency keys; удалённый `khattab-crow` подтверждён mint + removal/burn и сохраняется только как `used_retired` tombstone. Нового mint, Identity-authority или изменения баланса нет; оба invariant-checker подтверждают `19025 = 10000 + 9025`, active escrow `0`.

**Сценарии:** S-03D, S-03E, S-03F, S-09, S-09B, S-09C.
**Проверка:** `python oled/changes/wea-vnext-recreation/evidence/check_hello_world_attestation.py`; `python -m pytest tests/vnext/test_hello_world_attestation.py -q` (обязательны ноль skips); `python -m pytest tests/vnext/test_identity.py tests/vnext/test_hello_world.py -q`; `python scripts/check_invariant.py`. `[CHAT][DERIVED]`

## 3. Draft, Triage и атомарный Contract

**Зависит от:** блоков 1–2.

- [x] Обновить общий валидатор и тестовые примеры для Issue Form, CLI и Tide. Формально корректный Issue остаётся Draft и не создаёт Task или escrow.
- [x] Записать Triage/Negativa как бесплатную либо отдельно оплаченную treasury-роль. Повтор после правки body не получает вторую выплату.
- [x] Проверить точные ревизии Triage, исключения оператора и согласия автора.
- [x] Одним переходом списать полный bank у автора, создать escrow, Contract и Task. Любая ошибка оставляет все четыре объекта отсутствующими.

**Сценарии:** S-02A, S-02C, S-02H, S-02I.
**Проверка:** `python -m pytest tests/vnext/test_intake.py tests/vnext/test_contract_activation.py -q`. `[CHAT][DERIVED]`

## 4. Первый полный путь `direct-pr`

**Зависит от:** блока 3. Это первый сквозной срез обычной задачи.

- [ ] Разбирать только комментарии с заголовком `### Декларация WEA`; остальной текст считать обсуждением.
- [ ] Читать все страницы `userContentEdits` у Issue и IssueComment. Недоступная или неполная история блокирует цикл; один `updatedAt` не заменяет ID ревизии.
- [ ] Выводить future Hello World submission, Agent0 decision и common-control disclosure только из принятых `GitHubEvent` внутри confirmed boundary; проверять actor/object/revision/body/effective time и глобальную одноразовость evidence IDs. Исторический operator-attested v1 bundle не является fallback этого пути.
- [ ] Создавать Work первым допустимым Deliverable. Следующие Deliverables сохраняют Work ID и получают следующую ревизию.
- [ ] Добавить поколения назначения роли проверки, полный Review Deliverable, решение автора, Final, выплаты и возврат остатка. После `completed` новый verdict требует продолженного поколения с целями и сроком; вторую выплату из bank оно не создаёт.
- [ ] Реализовать `wea submit <issue>` через общий валидатор и `wea next <issue>` как чтение подтверждённого состояния. CLI не пишет состояние сам.
- [ ] Сохранять ledger-переход раньше GitHub-проекции. Комментарий, label и закрытие Issue повторяются по детерминированному projection ID без второй выплаты.

**Сценарии:** S-01, S-01B, S-01C, S-03A, S-03B, S-03C, S-05A, S-05C, S-05D, S-05E, S-05F, S-05G, S-05H, S-06, S-06B, S-13, S-13B.
**Проверка:** `python -m pytest tests/vnext/test_direct_pr_flow.py tests/vnext/test_cli.py tests/vnext/test_projection.py -q`. `[CHAT][DERIVED]`

## 5. Общие механики, сроки и защита Contract

**Зависит от:** блока 4.

- [ ] Реализовать PoD, Progressive, Linear, Winner Take All и Best-X для `spec-only` и `direct-pr`; Finite и Infinite используют один набор денежных инвариантов.
- [ ] Добавить `birdie`, семидневное решение автора, истечение этапов и единый stop из `active` или `paused`.
- [ ] Материализовать срок при входе в этап. Сдвигать только ещё не наступившие сроки на подтверждённую длительность body-паузы.
- [ ] Во время паузы разрешать только декларацию остановки и завершение полного Review, который GitHub зафиксировал до паузы и в срок.
- [ ] Поддержать бесплатные, treasury- и bank-funded роли без дополнительного финансового состояния задачи.
- [ ] Действующий Contract сохраняет прежние правила, версию интерфейса и исполнителя после установки новых версий. Манифест и байты прежнего результата входят в проверку.

**Сценарии:** S-02B, S-02D, S-02E, S-02F, S-02G, S-02J, S-05B, S-06C, S-06D, S-07A, S-07B, S-07C.
**Проверка:** `python -m pytest tests/vnext/test_mechanics.py tests/vnext/test_deadlines.py tests/vnext/test_pause.py tests/vnext/test_roles.py -q`. `[CHAT][DERIVED]`

## 6. `full-build` и параллельные Work

**Зависит от:** блока 5.

- [ ] Реализовать этапы Spec, redteam Spec, выбор, реализация, review реализации и Final.
- [ ] Одна Work хранит всю линию участия агента. У выбранных Best-X Work этап и статус развиваются независимо.
- [ ] Победитель Spec получает право реализовать её. Автор может выбрать другую Spec или остановить задачу после просрочки или обнаруженного дефекта.
- [ ] Release выводится из допустимых `full-build` Work и завершённых ролей, включая бесплатные; Duel и Infinite Work не дают такого права.
- [ ] Реализовать полный цикл Release: детерминированное приглашение, открытие сессии Agent0, участие и явное закрытие. CLI и хранилище используют один Contract, а отсутствующая сегодня команда `wea release close` появляется вместе со сквозным тестом.

**Сценарии:** S-04A, S-04B, S-04C, S-04D, S-10.
**Проверка:** `python -m pytest tests/vnext/test_full_build.py tests/vnext/test_release_lifecycle.py tests/vnext/test_cli_release.py -q`. `[CHAT][DERIVED][REVIEW]`

## 7. Duel

**Зависит от:** блоков 3 и 5.

- [ ] Реализовать open и invited join. Первый участник выбирает сторону; второй допустимый join задаёт `duel_start_at`.
- [ ] Материализовать шесть абсолютных слотов, их границы и сдвиг при паузе.
- [ ] Реализовать возврат при несостоявшемся Duel и принятые выплаты при одном или двух завершивших участниках. Duel не создаёт Release.

**Сценарии:** S-08A, S-08B, S-08C, S-08D, S-08, S-08E, S-08F, S-08G.
**Проверка:** `python -m pytest tests/vnext/test_duel.py -q`. `[CHAT][DERIVED]`

## 8. Domain, Access и служебные подтверждения

**Зависит от:** блока 2. Можно вести параллельно с блоками 4–7 после стабилизации ядра.

- [ ] Хранить Domain вне root WEA и выдавать один действующий Access на семь дней. Access прекращает право WEA независимо от внешнего GitHub permission.
- [ ] Сохранять отдельное подтверждение внешней выдачи или отзыва и отчёт `matched / grant-missing / revoke-missing`; первая версия оставляет внешний grant/revoke ручным действием Agent0 или оператора.
- [ ] Для bootstrap, финансовой коррекции и `replay_repair` сохранять два отдельных подтверждения одного хеша: оператора и Agent0. На первом этапе это две роли одного владельца, а не независимые ключи.
- [ ] Делать финансовую коррекцию только добавлением компенсирующих проводок. Для неверного Identity, cursor, статуса или Work без денежной разницы добавлять `replay_repair` с `effective_from_transaction`, областью действия и операцией `executor_override / void_event / supersede_record / cursor_reset`; замена исполнителя действует и для будущих событий этой области.
- [ ] Описать мягкий путь обучения, Release для trainees и границу ручной модерации без машинного статуса отключения.

**Сценарии:** S-11A, S-11B, S-13C.
**Проверка:** `python -m pytest tests/vnext/test_access.py tests/vnext/test_correction.py tests/vnext/test_replay_repair.py -q`. `[CHAT][DERIVED][REVIEW]`

## 9. Теневой прогон, миграция и переключение

**Зависит от:** блоков 1–8. Само переключение требует нового явного подтверждения оператора и Agent0. `[CHAT][DERIVED]`

- [ ] Составить `documentation-inventory.json` и `writer-inventory.json`. Каждый workflow, CLI-команда и script, способный менять ledger или протокольное состояние, получает одно решение `replace / disable / historical-read-only`; неизвестный путь блокирует переключение.
- [x] Досрочно отключить публичный общий `wea claim`: удалить CLI-команду, `--force`, milestone shim, GitHub `claim-fast` writer и действующие инструкции; удалить scheduled Tide/auto-triage writers, чтобы операторская пауза была fail closed. Исторические claim-chain/TTL/integrity проверки остаются для чтения v1; claim-подобный Duel join остаётся отдельным будущим событием профиля Duel. Этот шаг перенесён вперёд решением оператора после остановки v1 Tide и Agent0 loop.
- [ ] Явно заменить v1 `register`, `rename`, `accept`, `ranking`, `duel-winner`, `verify`, `assign`, `pending/process_pending`, Tide и `label-paid`. До решения OD-28 и OD-29 не классифицировать `gauntlet mint` и пути achievement/revoke/transform догадкой.
- [ ] Сверить balances, escrow, незавершённые Issues, history, idempotency keys, Identity и Hello World. Сохранить frozen hashes, opening supply и reconciliation hash.
- [ ] Построить канонический `genesis.json` как событие 0 с полным начальным состоянием Agents, Identity, balances, использованных ключей и ссылок на историю v1. Удаление `state/` и повтор из genesis плюс событий должны дать те же байты.
- [ ] Прогнать vNext в теневом режиме без записи в ledger и GitHub. Каждый отчёт связывает границу GitHub, hash набора правил, вход и воспроизводимый выход.
- [ ] Доказать нулевые незакрытые обязательства v1 либо оформить каждое вручную до переключения.
- [ ] Остановить v1: отключить новые запуски, дождаться завершения всех заданий записи в ledger, зафиксировать HEAD и проверить его хеш. Все пути записи v1 переводятся на общий helper транзакций с блокировкой и повторной проверкой epoch и ожидаемого remote HEAD непосредственно перед коммитом.
- [ ] Под той же блокировкой `ledger-writes` и через compare-and-swap создать запись bootstrap и `genesis.json` с двумя процедурными подтверждениями, закрыть прежние учётные данные или пути записи и включить только `scripts/tide_vnext.py`.
- [ ] После первого события vNext запретить автоматический возврат к v1. Денежные исправления идут через коррекцию, а вычисленное нефинансовое состояние — через `replay_repair`.
- [ ] Обновить root-документацию, Issue Form, labels, CLI help, workflow guards и проверки синхронизации в том же переключении.

**Проверка:** `python -m pytest tests/vnext -q`, затем `python -m pytest -q`, `ruff check .`, `python scripts/check_invariant.py`, `python scripts/check_ledger_schema.py` и `python scripts/check_doc_sync.py`. Отдельные тесты доказывают одинаковый хеш прежнего исполнителя, восстановление после удаления `state/`, отказ каждого пути записи v1 после epoch, отказ запоздавшего процесса, пустую очередь при bootstrap и нефинансовое восстановление без изменения WEA. `[CODE@c703f5e][DERIVED][REVIEW]`

## Покрытие требований

| Требования Spec | Блоки и доказательство |
| --- | --- |
| R-01 | 4: решение автора и точный источник |
| R-02 | 3, 5: Contract, stop и защита body |
| R-03 | 2, 4: Work, декларации и Identity |
| R-04 | 6: `full-build` |
| R-05 | 4, 5: review и роли |
| R-06 | 4, 5: Final и решение автора |
| R-07 | 5: `birdie` и версии правил |
| R-08 | 7: Duel |
| R-09 | 2: Identity и Hello World |
| R-10 | 6: Release из Work и завершённых ролей |
| R-11 | 8: Domain и Access |
| R-12 | 8, 9: обучение, governance и синхронизация документации |
| R-13 | 1, 4, 8, 9: Tide, проекция, ledger и коррекция |

Все 55 BDD-сценариев имеют один основной блок. Табличные правила механик и payout проверяются в блоках 1 и 5, даже если у строки нет отдельного сценария. `[DERIVED]`

## Граница следующей сессии

Block 3 закрыт после adversarial review и повторной проверки. Следующая сессия начинает Block 4 отдельным worktree и PR от свежего `origin/main`: первый полный `direct-pr` path с accepted GitHubEvent revisions и confirmed boundary. `v0_6_0…v0_6_3` не меняются; новая closure по-прежнему fail closed для System Hello World. Никаких live-write, `scripts/tide_vnext.py`, `ledger/vnext/`, migration/bootstrap или переключения без отдельного gate. `[CHAT][DERIVED][CHECK][REVIEW]`
