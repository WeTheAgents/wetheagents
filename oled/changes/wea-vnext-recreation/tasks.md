# WEA vNext: план реализации

Статус `tasks 1.2`: **implemented / review pending**. Spec 0.9 reference runtime implemented and verified. The operator approved the S-11A, S-11B, and S-13C accepted-future scope correction. Passes 31 and 32 found and fixed the two sides of the S-13 Flat PoD birdie next-action gap. Pass 33 must verify the corrected package. Blocks 1–4 remain immutable historical evidence. `[CHAT][DERIVED][CHECK][REVIEW]`

## Правила исполнения

- Historical blocks below were separate tasks. The current Spec `0.9` delivery is one behavior-complete task and one PR with five internal verification groups. `[DERIVED]`
- На 2026-07-27 оператор поставил проект на паузу: v1 Tide и Agent0 loop не работают. Это разрешает заранее удалить публичный общий `claim`, уже отсутствующий в vNext, но не разрешает ledger-write, миграцию, bootstrap или live-подключение vNext. `[CHAT][DERIVED][CHECK]`
- Общая логика живёт в `src/wea_vnext/`. CLI и Tide используют её как библиотеку и не держат собственные копии правил или расчётов. `[CODE@c703f5e][DERIVED]`
- Rulesets and executors `0.6.x` and `0.7/v0_7_0` are immutable. Spec `0.9` receives ruleset/Tide interface `0.8` and executor `v0_8_0`; every Contract keeps its exact runtime triple while replay can reference it. `[CHAT][DERIVED][REVIEW]`
- Тесты называют BDD-сценарии из `spec.md` своими ID. Реестр сценариев не позволяет потерять или повторить ID. `[DERIVED]`
- Изменение наблюдаемого поведения возвращает работу в `outcome.md` или `spec.md`. Реализация не закрывает OD-11, OD-14, OD-28 или OD-29 догадкой. `[CHAT][DERIVED][REVIEW]`

## Current delivery: Spec 0.9 reconciliation

**Outcome:** one manifest-pinned pure runtime can replay and prove all 67 current BDD scenarios without changing live GitHub, ledger, migration, or bootstrap state. S-11A, S-11B, and S-13C remain accepted-future and non-effective.

**Authority:** Outcome/Spec `0.9`; design/schema `1.0`; delta/migration `0.9`. No open behavior decision exists.

### Group A — successor closure, schedules, and exact approval

- [x] Capture hashes for `rulesets/0.7.json` and every file in `executors/v0_7_0/` before edits.
- [x] Add canonical `rulesets/0.8.json` with exact depth × mode rules, schedule shapes, acceptance authority, role funding, pause kinds, release gate, and no profiles/Infinite/hidden fee.
- [x] Copy the complete closure to `executors/v0_8_0/`; update only successor version constants, rules validation, `StageSchedule`, `PlanStage`, `StageContract` deadlines, and manifest coverage.
- [x] Re-pin `resolution_plan.py` to exact executor `0.8.0`; keep old facades and closures unchanged.
- [x] Prove exact author/payer authority, strict Plan-to-decision source order, complete Plan/schedule binding, one debit, one escrow, first-child-only materialization, and replay atomicity.

**Scenarios:** S-01C, S-02A, S-02C, S-02H, S-02I, S-05C, plus inherited S-56…S-59.

**Files:** `rulesets/0.8.json`, `executors/v0_8_0/{rules,intake,manifest}.py/json`, `resolution_plan.py`, `test_current_bdd_{authority,plan_activation,plan_approval,plan_decision,plan_bank}.py`, packaging/runtime tests.

**Checkpoint:** focused tests are green; historical hash comparison is exact; no live path references `0.8.0`.

### Group B — Work and atomic mode settlement

- [x] Add sealed append-only runtime state, exact accepted GitHub sources, canonical replay, derived financial/stage projection, and deterministic Work/revision identity.
- [x] Implement Flat PoD acceptance with hash-bound pinned-validator replay or author fallback, one equal slot per Work, atomic payout, immediate slot-cap close, close/expiry refund, and failure rollback.
- [x] Implement Ranked author order, continuous rank validation, underfill refund, atomic settlement, selected revision, decision deadline, and no-winner expiry.
- [x] Implement Frontier snapshot uniqueness, hash-bound normalized output, pinned validator replay, configured and paid prior-art comparison, exact-revision `needs_author`, semantic Get-10 equivalence keys, immediate Linear/Fibonacci payout, close/expiry, and unused suffix refund.
- [x] Implement Work scope and immutable cross-stage selected input records.
- [x] Freeze author and participant authority on first Work. Require exact public common-control disclosure before selection or settlement in every mode.

**Scenarios:** S-03B, S-03F, S-04A, S-06C, S-07A, S-07B, S-61…S-64, S-67, S-68, S-69, S-70.

**Files:** `executors/v0_8_0/lifecycle.py`, `test_current_bdd_{work_scope,ranked_progression,mode_expiry,birdie,flat_pod,ranked_settlement}.py`, existing Frontier/progression tests.

**Checkpoint:** every mode conserves program escrow and simulated payment failure leaves no acceptance, cursor, status, or money effect.

### Group C — progression, pauses, roles, stop, and replan

- [x] Materialize the next child Contract and its deterministic Task from one exact accepted revision without author debit or approval; close each completed or stopped Task with its exact result; reject Flat PoD as a selected source at Plan intake; pause later outcome ambiguity without money movement.
- [x] Implement exact current Issue-revision evidence for `body_integrity_pause` and resume. Offset only deadlines that were open at pause start.
- [x] Implement Agent0 `risk_pause` from one exact active Triage/review role generation. Reject stale, inactive, unassigned, and unrelated role warnings.
- [x] Keep submissions open during `risk_pause`. Block stage decisions, keep deadlines running, preserve the pause on body resume, and require the author to resolve it.
- [x] Permit only frozen pre-pause role evidence and resolution during `risk_pause`. Reject new role assignments and keep role settlement separate from stage settlement.
- [x] Implement frozen role target sets, positive assignment-relative deadlines, generations, complete/timely evidence, late Agent0 resolution, `free/treasury` settlement, replacement races, and terminal closure of every active role escrow.
- [x] Bind each role result and downstream blocker to the assigned generation's frozen Agent ID and GitHub account.
- [x] Implement ordered stop: resolve a complete timely pre-boundary result first, ignore incomplete/later evidence, preserve legal settlements, refund unused escrow once, and close without a final reward.
- [x] Store each suffix replan as the next full Triage Plan revision plus a later exact author approval. Bind future Contracts to that revision.

**Scenarios:** S-02B, S-02J, S-04B, S-04D, S-05A, S-05D…S-05H, S-65, S-66, plus compatible pause/deadline scenarios.

**Files:** `executors/v0_8_0/lifecycle.py`, `test_current_bdd_{plan_stop,body_pause,risk_pause,defect_replan,role_generations,role_timing,role_stop_order,post_stop,role_deadline}.py`.

**Checkpoint:** replay is idempotent; deadlines move once; partial role evidence cannot block stop or create payment/Release.

### Group D — Duel, eligibility, Release, feedback, and next action

- [x] Implement two joins, six ordered move windows, increasing accepted move numbers, expired-slot skips, first-completer decision timing, immediate no-completer final-move stop, pause offsets, unchanged Duel payouts, and no Duel Release.
- [x] Keep Implement participation open to every eligible Agent ID; selected Spec authors get no implicit privilege or duty.
- [x] Create non-Triage Release invitations only from pinned completed Work/role outcomes. Gate Triage Release on successful whole-Plan completion.
- [x] Store declined/stopped/downstream-blocked Triage outcome as linked negative feedback without Release.
- [x] Expose pure `next_action` with exact Plan revision/stage/Contract/depth/mode/actor/role/Work-control/deadline context and prove zero writes.

**Scenarios:** S-04C, S-08, S-08A…S-08G, S-10, S-13, plus compatible Release/projection scenarios.

**Files:** `executors/v0_8_0/lifecycle.py`, `resolution_plan.py`, `test_current_bdd_{implement_eligibility,triage_release,next}.py`, existing Duel tests.

**Checkpoint:** Duel timing/payouts match the inherited table; `next_action` is a pure projection; Triage gets no early Release.

### Group E — exact registry, integration, and durable evidence

- [x] Register exactly 67 current IDs: 41 compatible scenarios plus 26 changed or added scenarios. Register S-11A, S-11B, and S-13C as accepted-future. Keep historical references separate.
- [x] Make registry tests parse the normative Spec `0.9` delta and inherited compatibility list without confusing historical duplicate headings.
- [x] Update package data and manifest tests for ruleset `0.8` and `v0_8_0` while preserving all older wheel/replay cases.
- [x] Run focused current-BDD tests, all `tests/vnext`, full repository tests, Ruff, Pyright, manifest/canonical checks, ledger schema/invariant checks, and phase-boundary checks.
- [ ] Perform the final independent `codex exec review`, lean cut, and regenerate `HANDOFF.md`, `verification.md`, and `WEA_vNext_REVIEW.html` from fresh evidence.

**Checkpoint commands:**

```powershell
python -m pytest tests/vnext/test_current_bdd_*.py -q
python -m pytest tests/vnext -q
python -m pytest -q
ruff check src/wea_vnext tests/vnext oled/changes/wea-vnext-recreation/build_review_html.py
pyright src/wea_vnext
python scripts/check_invariant.py
python scripts/check_ledger_schema.py
python scripts/check_doc_sync.py
python oled/changes/wea-vnext-recreation/build_review_html.py
git diff --check
```

### Scope stop

Do not add or change a live Tide/CLI writer, `ledger/vnext/`, GitHub Issue state, task funding, migration record, bootstrap, Domain/Access behavior, OD-11, OD-14, OD-28, or OD-29. A discovered need for any item stops implementation and returns to the operator.

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

## 4. Resolution Plan intake и первый child Contract

**Зависит от:** blocks 1–3 как immutable historical foundation; `outcome 0.8`, `spec 0.8`, `design 0.9`. **Статус:** complete; verified in the inactive `v0_7_0` boundary.

- [x] До изменений записать hashes `v0_6_0…v0_6_3` и `rulesets/0.6.json`; после реализации доказать byte-for-byte отсутствие изменений.
- [x] Сначала создать `test_resolution_plan_rules.py`, `test_resolution_plan_intake.py` и `test_resolution_plan_activation.py`; initial RED дал 20 ожидаемых failures из-за отсутствующего executor `0.7.0` после исправления test-package imports.
- [x] Добавить канонический `rulesets/0.7.json` без profile aliases и Infinite. Проверить все разрешённые depth × mode строки и каждую независимо недопустимую форму S-59, exact finite payouts и formal reject taxonomy.
- [x] Добавить полную immutable closure `v0_7_0` с пустым semantic-dependency map. Сохранить общие replay/Identity/manifest boundaries, зарезервировать `plan-escrow:` и заменить profile intake на exact `Draft → TriageAssessment → ResolutionPlanRevision → AuthorPlanDecision` chain.
- [x] Поддержать initial Triage proposal, append-only author amendment, `approve/request_revision/decline` и semantic warning без veto. Все source revisions/hashes, authority snapshots, parent links и feedback evidence входят в canonical state.
- [x] Реализовать atomic approval: один author debit полного bank, один program escrow, Plan и только first Stage Contract/Task. Future templates и symbolic selectors сохраняются, но future Contracts отсутствуют; replay identical, conflicting evidence, foreign subclass и post-validation mutation fail closed.
- [x] Добавить явный facade `src/wea_vnext/resolution_plan.py`, закреплённый на `0.7.0`; старый `intake.py` facade остаётся на `0.6.3`. Обновить package/manifest tests без подключения CLI или live Tide.
- [x] Запустить focused tests, весь `tests/vnext`, полный repository suite, Ruff, ledger schema/invariant checks и phase-boundary checks; записать фактические результаты только в `verification.md` через OLED Verify.

**Сценарии:** S-56, S-57, S-58, S-59. S-60…S-68 остаются принятым downstream контрактом, не обещанием Block 4.

**Focused proof:** `python -m pytest tests/vnext/test_resolution_plan_rules.py tests/vnext/test_resolution_plan_intake.py tests/vnext/test_resolution_plan_activation.py -q`.

## Очередь после Block 4

Это dependency map, а не разрешение расширять текущий PR:

1. generic Stage execution для Ranked и Flat PoD, accepted GitHubEvent/Work revisions, underfill, deadlines, roles и settlement;
2. Frontier execution, normalized validator/`needs_author`, snapshot uniqueness и новый Get 10 epoch;
3. Explore/Duel execution;
4. selector resolution, automatic next Contract, paused replan suffix и Release по Implement depth;
5. Domain/Access, затем отдельный shadow/migration/bootstrap gate.

The current Spec `0.9` delivery completes items 1–4. The next active block starts with a new Domain/Access cut. The archived Block 6 is not executable.

Точные block numbers и cuts после Block 4 должны учитывать реальные размеры и найденные seams; их нельзя выводить из старых profiles.

## Исторический roadmap tasks 1.0 — superseded после Block 4

Следующие разделы сохраняют прежнюю декомпозицию для traceability, но не являются исполняемым планом Spec 0.8.

### Archived 5. Общие механики, сроки и защита Contract

**Зависит от:** блока 4.

- [ ] Реализовать PoD, Progressive, Linear, Winner Take All и Best-X для `spec-only` и `direct-pr`; Finite и Infinite используют один набор денежных инвариантов.
- [ ] Добавить `birdie`, семидневное решение автора, истечение этапов и единый stop из `active` или `paused`.
- [ ] Материализовать срок при входе в этап. Сдвигать только ещё не наступившие сроки на подтверждённую длительность body-паузы.
- [ ] Во время паузы разрешать только декларацию остановки и завершение полного Review, который GitHub зафиксировал до паузы и в срок.
- [ ] Поддержать бесплатные, treasury- и bank-funded роли без дополнительного финансового состояния задачи.
- [ ] Действующий Contract сохраняет прежние правила, версию интерфейса и исполнителя после установки новых версий. Манифест и байты прежнего результата входят в проверку.

**Сценарии:** S-02B, S-02D, S-02E, S-02F, S-02G, S-02J, S-05B, S-06C, S-06D, S-07A, S-07B, S-07C.
**Проверка:** `python -m pytest tests/vnext/test_mechanics.py tests/vnext/test_deadlines.py tests/vnext/test_pause.py tests/vnext/test_roles.py -q`. `[CHAT][DERIVED]`

### Archived 6. `full-build` и параллельные Work

**Зависит от:** блока 5.

- [ ] Реализовать этапы Spec, redteam Spec, выбор, реализация, review реализации и Final.
- [ ] Одна Work хранит всю линию участия агента. У выбранных Best-X Work этап и статус развиваются независимо.
- [ ] Победитель Spec получает право реализовать её. Автор может выбрать другую Spec или остановить задачу после просрочки или обнаруженного дефекта.
- [ ] Release выводится из допустимых `full-build` Work и завершённых ролей, включая бесплатные; Duel и Infinite Work не дают такого права.
- [ ] Реализовать полный цикл Release: детерминированное приглашение, открытие сессии Agent0, участие и явное закрытие. CLI и хранилище используют один Contract, а отсутствующая сегодня команда `wea release close` появляется вместе со сквозным тестом.

**Сценарии:** S-04A, S-04B, S-04C, S-04D, S-10.
**Проверка:** `python -m pytest tests/vnext/test_full_build.py tests/vnext/test_release_lifecycle.py tests/vnext/test_cli_release.py -q`. `[CHAT][DERIVED][REVIEW]`

### Archived 7. Duel

**Зависит от:** блоков 3 и 5.

- [ ] Реализовать open и invited join. Первый участник выбирает сторону; второй допустимый join задаёт `duel_start_at`.
- [ ] Материализовать шесть абсолютных слотов, их границы и сдвиг при паузе.
- [ ] Реализовать возврат при несостоявшемся Duel и принятые выплаты при одном или двух завершивших участниках. Duel не создаёт Release.

**Сценарии:** S-08A, S-08B, S-08C, S-08D, S-08, S-08E, S-08F, S-08G.
**Проверка:** `python -m pytest tests/vnext/test_duel.py -q`. `[CHAT][DERIVED]`

### Archived 8. Domain, Access и служебные подтверждения

**Зависит от:** блока 2. Можно вести параллельно с блоками 4–7 после стабилизации ядра.

- [ ] Хранить Domain вне root WEA и выдавать один действующий Access на семь дней. Access прекращает право WEA независимо от внешнего GitHub permission.
- [ ] Сохранять отдельное подтверждение внешней выдачи или отзыва и отчёт `matched / grant-missing / revoke-missing`; первая версия оставляет внешний grant/revoke ручным действием Agent0 или оператора.
- [ ] Для bootstrap, финансовой коррекции и `replay_repair` сохранять два отдельных подтверждения одного хеша: оператора и Agent0. На первом этапе это две роли одного владельца, а не независимые ключи.
- [ ] Делать финансовую коррекцию только добавлением компенсирующих проводок. Для неверного Identity, cursor, статуса или Work без денежной разницы добавлять `replay_repair` с `effective_from_transaction`, областью действия и операцией `executor_override / void_event / supersede_record / cursor_reset`; замена исполнителя действует и для будущих событий этой области.
- [ ] Описать мягкий путь обучения, Release для trainees и границу ручной модерации без машинного статуса отключения.

**Сценарии:** S-11A, S-11B, S-13C.
**Проверка:** `python -m pytest tests/vnext/test_access.py tests/vnext/test_correction.py tests/vnext/test_replay_repair.py -q`. `[CHAT][DERIVED][REVIEW]`

### Archived 9. Теневой прогон, миграция и переключение

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

## Историческое покрытие tasks 1.0

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

Эта таблица описывает только superseded Spec 0.7. Current Spec 0.8 scenarios S-56…S-59 принадлежат Block 4; S-60…S-68 распределятся после его evidence по очереди выше. `[DERIVED]`

## Resume handoff tasks 1.1

| Lane/group | Status | Dependency or blocker | Exact next action | Proof/evidence gap |
| --- | --- | --- | --- | --- |
| Block 4 rules tests | complete | none | retain exact ruleset/manifest bytes | focused and vNext suites green |
| Block 4 authority/feedback | complete | none | retain S-56/S-57 regressions | feedback chain and formal-only reject tests green |
| Block 4 atomic activation | complete | none | retain S-58 one-debit group | atomic activation/idempotency tests green |
| Historical isolation | complete | none | no action | old paths have no diff; runtime/packaging suite green |
| Downstream execution | planned later | Block 4 evidence informs cut | retain queue without code in this branch | S-60…S-68 hooks absent |
| Live/migration/bootstrap | blocked by explicit phase authority | separate operator + Agent0 gate | no action | intentionally absent |

Immediate next action: use `oled-design` to reconcile design/schema/delta/migration with accepted Outcome/Spec `0.9`. Then use `oled-tasks` before any code or test change. Ruleset `0.7` and executors `v0_6_0…v0_7_0` remain immutable. No live writer, `scripts/tide_vnext.py`, `ledger/vnext/`, migration, bootstrap, Issue activation, or WEA funding is authorized. `[CHAT][DERIVED][CHECK]`
