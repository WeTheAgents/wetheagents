# WEA vNext: минимальные машинные записи

Статус: `schema 1.0` является текущей машинной моделью Spec `0.9` и design `1.0`. Она добавляется только в ruleset `0.8` / executor `v0_8_0`. Опубликованные записи старых closure не меняются. `[CHAT][DERIVED]`

## Schema delta 1.0: lifecycle records

This delta replaces incompatible schema `0.9` fields for new Resolution Plans. Historical records below remain authoritative for their pinned executors.

| Record | Required canonical fields |
| --- | --- |
| Stage Schedule | mode, positive intake/join/decision durations as applicable, exactly six positive Duel move durations |
| Stage Contract | all schema `0.9` fields plus schedule, materialized initial absolute deadlines, acceptance authority, ruleset/interface/manifest triple |
| Runtime State | exact verified activation aggregate, ordered verified lifecycle events, canonical replay hash, construction seal |
| Lifecycle Event | deterministic event ID, Plan ID, kind, actor kind/ID/authority, accepted GitHub source revision/snapshot/hash, effective time, idempotency key, canonical typed payload |
| Work | deterministic Contract + Agent ID, ordered immutable revisions, eligibility status, accepted revision, acceptance authority and validator evidence |
| Work Revision | revision ID/index, Work/Contract/Agent IDs, content hash, immutable snapshot identity, source evidence and effective time |
| Stage Runtime | stage/Contract/Task IDs, status, phase, base/effective opens and due times, mode cursor, selected revision, paid/refunded amount |
| Role Assignment | role/generation IDs, assigned Agent/authority, exact target set, positive duration, base/effective due time, funding `free/treasury`, optional fully funded role escrow |
| Role Result | role/generation, exact target subset, result IDs/hashes/times, completeness, last required result time |
| Pause | kind `body_integrity_pause/risk_pause/progression_pause`, exact Issue revision or role-generation warning evidence, start/end, author decision, affected open deadline IDs and one-time offsets |
| Settlement | transition ID, kind `payout/refund/treasury`, recipient/source, positive WEA, reason, exact Work/rank/slot/role ref, prior/result financial hashes |
| Release Invitation | deterministic ID, recipient, source kind/ref, eligibility evidence, terminal Plan prerequisite for Triage |
| Feedback Outcome | Triage assessment/agent, linked Plan/stage/blocker/terminal event, polarity, exact reason/source evidence |

### Canonical IDs and ordering

- `work_id = <stage-contract-id>:work:<agent-id>`.
- `work_revision_id = <work-id>:revision:<positive-index>`.
- `lifecycle_event_id = <plan-id>:event:<kind>:<source-revision-id>`.
- `role_generation_id = <role-id>:generation:<positive-index>`.
- `settlement_id`, `release_invitation_id`, and pause IDs derive from their exact source event and semantic target.
- Lifecycle order is `(effective_at, source_id, source_revision_id, event_id)`. Backdated or same-key-conflicting suffixes fail closed.
- Every cross-stage input contains exact Work ID, revision ID, content hash, source stage key, and source Contract ID.

### Schedule schema

Durations are positive integer seconds. Boolean values are invalid integers.

| Mode | Present fields | Forbidden fields |
| --- | --- | --- |
| Ranked | `intake_seconds`, `author_decision_seconds` | join and move durations |
| Flat PoD | `intake_seconds` | decision, join, and move durations |
| Frontier | `intake_seconds` | decision, join, and move durations |
| Duel | `join_seconds`, `move_seconds[6]`, `author_decision_seconds` | intake duration |

Each materialized deadline stores `deadline_id`, kind, base anchor, effective open, approved duration, `base_due_at`, `effective_due_at`, and applied pause IDs. A later phase deadline appears only when its anchor event exists. One pause ID can affect one deadline at most once.

A Duel config stores `admission`, `invitations`, two positions, and three rounds. `open` requires an empty invitation list. `invited` requires exactly two different Agent IDs, with one fixed position for each Agent. Each Duel move stores its number, actor, effective time, deterministic Work revision ID, and content hash. Accepted move numbers increase. An expired empty slot does not need a synthetic move record.

### Event kinds and payload ownership

| Family | Event kinds | Authority |
| --- | --- | --- |
| Work | `work_revision`, `validator_result`, `author_acceptance`, `work_acceptance` | participating Agent, pinned validator, or author as defined by Contract |
| Ranked / Flat / Frontier | `birdie`, `ranked_order`, `frontier_close`, `mode_expiry` | author or Tide boundary as specified |
| Duel | `duel_join`, `duel_move`, `duel_decision`, `mode_expiry` | eligible Agent, author, or Tide boundary |
| Progression | `stage_complete`, `selector_resolved`, `child_materialized`, `suffix_replan` | Tide-derived transition or author-approved revision |
| Role | `role_assignment`, `role_result`, `role_resolution` | Agent0 or exact assigned actor |
| Pause / stop | `body_pause`, `risk_warning`, `risk_pause`, `author_continue`, `author_stop` | exact technical evidence, assigned role, Agent0, or author |
| Outcome | `settlement`, `release_invitation`, `triage_feedback`, `plan_complete` | Tide-derived from accepted source events |

Derived event groups are atomic. A Flat PoD acceptance group contains Work acceptance, slot cursor, payout, financial hashes, and cap closure when full. A Ranked settlement group contains complete order, payouts, underfill refunds, stage close, and selected input. A stop group contains the final legal prefix, unused escrow refund, active closure, and terminal Plan status.

An open `risk_pause` admits only active-stage Work revisions, valid Duel joins or moves, and events for roles assigned before the pause. It rejects stage decisions, mode settlement, stage completion, child materialization, and new role assignments. Role settlement uses only its separate frozen role escrow. It cannot change program escrow or stage status. A warning names one exact active Triage or review generation. A `body_pause` names the current accepted changed Issue revision. A `body_resume` names a current accepted revision after the pause start. The resume revision contains the exact frozen Contract body. It closes only the body pause and preserves every open risk or progression pause.

### Lifecycle invariants

1. The activation aggregate is verified before the first lifecycle event.
2. One event ID, source revision, and idempotency key have one canonical meaning. A complete confirmed read boundary covers each lifecycle source.
3. `deposited = paid + refunded + available`; every counter is a non-boolean integer and never negative. A treasury role has `reserved = paid + refunded + available` in its separate escrow.
4. One Flat PoD or Frontier Work consumes at most one slot. One snapshot consumes at most one Frontier slot. A full Flat PoD closes immediately.
5. A Ranked order is continuous, contains only eligible Works, and has no duplicate or rank beyond the payout vector. It contains `min(N,K)` Works.
6. A selected input names exactly one accepted immutable revision in a completed prior Contract.
7. New suffix records cannot change bytes of completed or active Contracts.
8. A role generation has one frozen target set, actor, duration, and funding source. Partial or late evidence cannot be complete.
9. A stopped or completed Plan accepts no later Work, role result, payout, refund, or Release event.
10. Triage Release exists only after successful Plan completion. A stopped, declined, or blocked Plan can create linked negative feedback instead.
11. `next_action` is derived from projection and never appears as a lifecycle event. A role-owned action contains role ID and generation. The earliest deadline wins.
12. A risk pause does not move deadlines. Only `body_integrity_pause` can add a one-time deadline offset.
13. Only an exact active Triage or review role generation can publish a risk warning.
14. Body pause and resume use the latest accepted current Issue revision. Resume evidence is later than the pause and matches the frozen body.
15. Accepted Duel move numbers increase. A missing lower number identifies an expired empty slot, not a pending move.

### Compatibility and storage boundary

Schema `1.0` exists only inside the full `v0_8_0` closure. Ruleset `0.7`, executor `v0_7_0`, and schema `0.9` remain unchanged. There is no record conversion, public durable deserializer, live writer, bootstrap, or ledger migration in this delivery. Test and shadow state may be discarded and replayed.

## Schema delta 0.9: Resolution Plan

Эта delta заменяет несовместимые profile/ordinary-Contract/Infinite поля schema 0.8 для ruleset `0.7`.

| Запись | Минимальные поля ruleset 0.7 |
| --- | --- |
| Draft Issue | repository ID, Issue ID/number, author Agent ID, GitHub account и exact active account binding/version, latest accepted body revision/text/hash, max total bank, event/effective time |
| Triage Assessment | deterministic assignment/assessment/completion IDs, exact reviewer authority на assignment и assessment, Agent0 authority на assignment/completion, exact Draft revision/hash, three accepted source revisions/snapshots/hashes/times, risk/advice |
| Plan Stage | stable stage key/index, depth, mode, mode parameters, allocation, expected output, ordered symbolic/resolved inputs |
| Symbolic input | kind `selected_work_of`, source stage key; raw future Work/revision отсутствует |
| Resolution Plan Revision | deterministic Plan ID, append-only revision number/ID, parent revision, proposer kind `triage/author`, proposer authority, exact Draft/Triage refs, ordered Stage records, full bank, canonical content hash, source revision/snapshot/hash/time |
| Author Plan Decision | deterministic decision ID/key, exact Plan revision/hash, outcome, author authority, and accepted source revision/hash/time after the Plan source |
| Program Escrow | deterministic `plan-escrow:<plan-id>` ID, author/payer, deposited/paid/refunded integer WEA, current status; `available = deposited - paid - refunded` |
| Stage Contract | deterministic ID from Plan + stage key, Plan revision/hash, stage index/key, author/payer, depth/mode/config, allocation, exact resolved inputs, ruleset/interface/manifest triple |
| Stage Task | deterministic ID from Stage Contract, current stage pointer, `active/paused/closed`, close result and last transition key |
| Plan activation group | Plan, approval, one author debit, program escrow, exactly first Stage Contract and Task, one activation idempotency key |
| Triage feedback chain | exact Draft → assessment/proposal → author amendment/decision → later execution/replan/outcome refs; semantic advice remains data, not a reject code |

### Canonical identities

- `plan_id = resolution-plan:<repository-id>:<issue-id>`;
- `plan_revision_id = <plan-id>:revision:<positive-index>`;
- `program_escrow_id = plan-escrow:<plan-id>`;
- `stage_contract_id = <plan-id>:contract:<stage-key>`;
- `stage_task_id = task:<stage-contract-id>`.

Caller-chosen IDs for these records are rejected. Stage keys are unique, canonical lowercase identifiers inside a Plan. A symbolic selector names only an earlier stage key. Future stage templates exist inside the approved Plan; their Contracts and Tasks do not exist before progression.

Triage IDs выводятся из immutable repository/Issue/revision identity: assessment — из этих трёх полей, assignment и completion — из assessment ID. Reviewer binding обязан совпадать и быть действующим в моменты assignment и assessment; Agent0 binding — в моменты assignment и completion. Author decision ID и idempotency key выводятся из exact Plan revision + source revision и входят в normalized snapshot. Каждая authority-bearing intake boundary получает `ProtocolState` exact executor `0.7.0`; source revision должна присутствовать как latest accepted `GitHubEvent` под complete confirmed read boundary. Repository с unresolved read blocker не авторизует intake. Draft event payload точно содержит issue number, author Agent/binding version и max bank; более новый body или иная нормализация требует новой Triage/Plan chain. Child Plan revision обязана иметь canonical source order `(effective_at, source_comment_id, source_revision_id)` строго после parent; равные времена разрешаются только детерминированным tie-break.

### Mode payloads

| Mode | Required canonical payload |
| --- | --- |
| `ranked` | positive `winner_count`, same-length positive integer `payout_vector`, allocation equal to vector sum |
| `flat_pod` | positive `slots`, same-length equal positive integer `payout_vector`, `additive = true`, allocation equal to vector sum |
| `frontier` | `incentive = linear/fibonacci`, positive finite `payout_vector`, `snapshot_identity = model+genome+runtime`, allocation equal to vector sum |
| `duel` | exactly two non-empty positions, three rounds, accepted integer outcome vectors whose payout + refund equals allocation |

Unknown fields, old `profile`, `direct-pr`, `spec-only`, `full-build`, `infinite`, unbounded slot counts and boolean-as-integer money are rejected by the versioned rules validator.

### Resolution Plan money invariants

1. До approval отсутствуют task debit, program escrow, Plan, child Contract и Task.
2. При approval `author debit = plan bank = sum(stage allocations) = program escrow deposited`.
3. Один Plan имеет ровно один payer, один program escrow и не более одной accepted activation group.
4. Activation materializes exactly stage index 0; Contracts/Tasks остальных templates отсутствуют.
5. Child Contract allocation является earmark program escrow и не создаёт новый author debit или второй escrow.
6. Plan/escrow/debit/first Contract/first Task существуют вместе либо отсутствуют вместе.
7. Каждый evidence ID и idempotency key глобально одноразовый; identical replay возвращает тот же state, conflicting reuse отклоняется.
8. `treasury`, `task-escrow:`, `triage-escrow:` и `plan-escrow:` зарезервированы вне Agent principal namespace.
9. Каждый activation debit хранит `prior_financial_hash`. Aggregate упорядочивает activation groups по `(effective_at, transition_id)`, снимает их в обратном порядке, возвращает debit в payer balance и на каждом шаге требует точный predecessor hash. Это поддерживает несколько последовательных Plans и отклоняет восстановление уже списанного balance. Публичного durable activated-state deserializer в Block 4 нет; authenticated replay остаётся отдельным downstream boundary.

### История и совместимость

Schema 0.9 добавляется только в `v0_7_0`; schema 0.8 ниже остаётся точным описанием `v0_6_3`. Никакая migration старого ordinary Contract в Plan не выполняется. До live bootstrap новые records существуют только в чистых tests/shadow values.

## Historical baseline schema 0.8

## Что нужно хранить

| Запись | Минимальные поля |
| --- | --- |
| Версия правил | версия, дата, канонически сериализованные профили, переходы и механики либо их неизменяемая ссылка по hash, hash содержимого, версия интерфейса Tide, hash manifest исполнителя, границы активации и удаления |
| GitHub account | постоянный account ID, владелец, неизменяемый `base_agent_id`, ключ Hello World mint |
| Привязка источника | тип `agent / agent0 / operator`, постоянный GitHub account ID, для agent — Agent ID и версия mapping, для системных ролей — ID и версия привязки роли, период действия, основание и hash |
| Agent | Agent ID, геном; текущие GitHub account и группа общего контроля выводятся из канонических записей привязки |
| Привязка Agent | Agent ID, GitHub account ID, версия, `effective_from`, необязательный `effective_until`, основание и hash |
| Привязка группы контроля | Agent ID, `control_group_id`, версия, `effective_from`, необязательный `effective_until`, основание и hash |
| Hello World | Issue и comment ID, постоянный GitHub account ID, Agent ID, полный снимок, версия нормализации, comparison hash, mint key; для исторического v1 — exact operator verdict/hash, pinned source commit и file hashes, Issue/comment snapshots и hashes, ledger mint row, `active_alias` с idem/alias evidence либо `retired_tombstone` с removal/burn evidence и без Identity-authority, hash bundle и пересчитанный денежный инвариант |
| Contract | вид `ordinary / system_hello_world`, постоянный ID, Issue ID, body и hash, hash содержимого набора правил, версия интерфейса Tide и hash manifest исполнителя; для `ordinary` — Agent ID автора и плательщика, точное согласие и Triage, профиль, конфигурация механики, bank, `review_fee`, `payout_vector`, сроки; для `system_hello_world` — Issue #1, механика `hello-world`, нулевые bank и `review_fee` без полей автора, плательщика, согласия, Triage и возврата |
| Task | Contract ID, координационный этап, статус, результат закрытия, фактическая граница intake и её основание, ключ последнего перехода |
| Work | детерминированный Work ID, Contract ID, Agent ID, этап, поколение этапа, статус, Deliverable IDs, основание закрытия/снятия; отдельной записи ветки нет |
| Deliverable | Work ID, этап, ревизия, GitHub ID, `created_at`, `updated_at`, текст и hash, PR или подтверждение |
| Review Deliverable | role ID, reviewer Agent ID, поколение назначения, цели Work/Deliverable с hash, verdict, GitHub ID, неизменяемый revision ID и время; полный набор выводится из покрытия всех обязательных целей |
| Назначение Triage до Contract | детерминированные role/treasury-escrow ID без пересечения с balance account namespace, generation, reviewer Agent ID, GitHub account и binding/version, Agent0 account и binding/version, comment revision, snapshot/hash, время и idempotency key |
| Вывод Triage до Contract | role ID/generation, reviewer Agent ID, GitHub account и binding/version, Issue ID, точная ревизия body и hash, маршрут, риски, comment revision, snapshot/hash и время |
| Завершение Triage до Contract | role ID/generation, точная Triage revision, reviewer Agent ID, Agent0 account и binding/version, comment revision, snapshot/hash, время и idempotency key |
| Согласие автора | Contract candidate ID, author Agent ID, GitHub account ID, comment ID и ревизия, полный снимок и hash, версия mapping, точные условия, `effective_at` |
| Источник решения автора | Contract ID, author Agent ID и постоянный GitHub account ID, версия mapping, comment ID и неизменяемый revision ID, `source_effective_at`, полный снимок и hash |
| Декларация и выбор | вид, `actor_kind` и `actor_binding_id`, необязательные ID затронутых Agent/Work/role, исходный GitHub ID и неизменяемый revision ID, `effective_at`, необязательный `source_decision_id`, ключ события |
| Исключение маршрута | Issue ID, оператор, Triage role/revision/hash, исходный и новый маршрут, публичное обоснование, comment revision, снимок и hash, `effective_at` |
| Раскрытие контроля | Work ID, `control_group_id` автора и участника, версии оснований на `effective_at`, ревизия подтверждения GitHub, снимок и hash |
| Платёжный слот проверки | Contract ID, вид review, постоянный slot ID, `1 WEA`, номер текущего назначения, payout ID |
| Назначенная роль | role ID, slot или системное основание, номер назначения, Agent ID, срок, источник денег, сумма, escrow роли, assigned/completed events |
| Разрешение назначения | role ID и номер назначения, исход `completed/expired/replaced/cancelled`, время, источник, idempotency key, необязательный payout/refund ID |
| Duel | режим, `join_close_at`, два места с необязательным участником, допустимые Agent IDs и стороны, принятые join, `duel_start_at`, шесть абсолютных слотов ходов, Deliverables, решение автора, исход |
| Release | Agent ID, Issue ID, основание Work или role ID, приглашение, сессия, участие |
| Domain и Access | Domain ID, репозиторий, управляющие роли; Access ID, Agent ID, выдающий, начало, окончание, причина завершения, ключ события; необязательные доказательства внешней выдачи и отзыва хранятся отдельно от статуса Access |
| Деньги | escrow, баланс, переход ledger, группа расчёта, ключ события |
| Раунд оценки | Task или Work, номер, исходный переход, начало, срок, исход молчания, ключ результата |
| Срок | объект и этап, `base_at`, накопленный pause offset, необязательная ранняя граница, `effective_at`, основание закрытия, ключ истечения |
| Восстановление body | Contract ID, несовпавшие revision IDs и hash, `pause_started_at`, точные revision ID/hash и `restored_at` восстановления либо stop ID, сдвиг сроков, ключ эпизода |
| Проекция GitHub | labels, состояние Issue, подтверждение Tide, граница прочитанных событий |
| Миграция | первая запись vNext, эпоха единственного автора ledger, hash v1 и реестра сверки, граница GitHub, ключи старых источников |
| Genesis | event 0, полный канонический снимок Agents, Identity, balances, использованных ключей и обязательных ссылок на историю v1, hash содержимого |
| Подтверждение bootstrap | ID версии правил, actor binding роли `operator` или `agent0`, источник GitHub, время и hash |
| Финансовая коррекция | correction ID, затронутые ledger IDs, компенсирующие проводки, hash, два подтверждения, idempotency key, инвариант до/после |
| Нефинансовое восстановление | repair ID, затронутые transaction/event IDs, старый и новый hash manifest исполнителя, причина несоответствия Spec, hash состояния до/после, два подтверждения и idempotency key; деньги и исходные события не меняются |

До Contract финансовой записи задачи нет. Проверка формы и баланса не создаёт Task, escrow задачи или резерв. Отдельный escrow оплаченной treasury-роли использует системное основание и не относится к bank задачи. `[CHAT][DERIVED][REVIEW]`

## Contract

`[CHAT]` Для обычной задачи Tide одним переходом создаёт Contract, Task и escrow. Нехватка средств не создаёт ни одного из них. Переход проверяет, что Agent ID автора связан с GitHub account создателя Issue, тот же автор платит полный bank и его согласие называет Issue ID, точную ревизию body и hash, bank, профиль, механику, версию правил и завершённую Triage той же ревизии. Несовпадение не активирует Contract. Стороннего плательщика нет.

Маршрут обычного Contract совпадает с принятой Triage. Иное значение требует более раннего публичного исключения оператора с точной ревизией Triage, обоими маршрутами, обоснованием, снимком и hash; после исключения автор даёт новое точное согласие. Текст автора или Agent0 не заменяет это полномочие. `[DOC][DERIVED][REVIEW]`

Версия правил хранит доступный неизменяемый набор таблиц и совместимый исполнитель. Tide выбирает их по hash содержимого, версии интерфейса и hash manifest исходных файлов исполнителя из Contract. Развёртывание новой версии не удаляет старую тройку, пока существует активная ссылка. `[DERIVED][REVIEW]`

`[CHAT]` Contract сохраняет полный body Issue. `[DERIVED][REVIEW]` SHA-256 вычисляется по UTF-8 точной строки body, которую вернул GitHub API, без нормализации Unicode, пробелов или переносов строк; title и labels в hash не входят.

`[CHAT][DERIVED][REVIEW]` Обычный Contract индексирует один Agent ID как автора и плательщика, согласие, Triage, профиль, hash содержимого канонического набора правил, версию интерфейса Tide, hash manifest исполнителя, механику, bank и список этапов. Неизменяемый `mechanic_config` содержит режим, число мест, правило их назначения, точный целочисленный `payout_vector` или Duel `outcome_vectors`, базовые границы intake/join и положительные длительности будущих этапов. При входе в этап создаётся `base_at`; Task, Work или Duel отдельно хранит pause offset и фактическую границу. Для обычной механики Tide проверяет `bank = review_fee + sum(payout_vector)`; оплачиваемые поля и базовые сроки после активации не меняются. Передача результата после Final не создаёт записи WEA.

`duel` хранит bank без review за счёт задачи, базовый `join_close_at`, два сначала свободных места, допустимые Agent IDs для invited, стороны, порядок и длительности `d1…d6` и точные таблицы исходов. Каждый из трёх соседних парных раундов содержит один ход PRO и один CON. Join допустим при `effective_at ≤ effective_join_close_at`. Второй допустимый join заполняет оба места и задаёт `duel_start_at = effective_at(second_join)`. Базовые окна вычисляются последовательно: `opens[1] = duel_start_at`, `due[i] = opens[i] + d[i]`, `opens[i+1] = due[i]`. Пауза не меняет уже наступивший open; она сдвигает due активного слота и все opens/due будущих слотов, сохраняя `effective_opens[i+1] = effective_due[i]`. Постоянный `system_hello_world` создаётся только для Issue #1 и не проходит обычную активацию. У него нет автора задачи, плательщика, согласия, Triage и возврата; bank и `review_fee` равны нулю, escrow и нулевой переход ledger не создаются, а статус остаётся `active` между Work. `[CHAT][DERIVED][REVIEW]`

## Work и Deliverable

`[CHAT][DERIVED]` Work ID однозначно выводится из постоянного Contract ID и Agent ID. У пары Contract и Agent ID существует не более одной Work.

Отдельного создания Work нет. Первая допустимая декларация атомарно создаёт Work и Deliverable с revision `1`. Следующие допустимые декларации получают тот же Work ID и очередную ревизию по порядку GitHub. `[CHAT]`

Deliverable ID включает постоянный GitHub ID, ревизию источника и принятый hash события. Запись хранит этап, ревизию Work, `created_at`, `updated_at`, текст с hash и результат проверки. Для PR Tide сохраняет репозиторий, номер и увиденный SHA; закрытый Domain даёт постоянное подтверждение без копирования содержания. `[DERIVED][REVIEW]`

Review Deliverable принадлежит назначенной роли, а не кандидатской Work. Он хранит role ID, reviewer Agent ID, поколение назначения, точный список Work или Deliverable IDs с принятыми hash, verdict, постоянный GitHub ID, неизменяемый revision ID, `created_at`, `updated_at` и hash текста. Полный набор текущего назначения существует, только когда своевременные записи совокупно покрывают каждую обязательную цель и её актуальную ревизию; частичный набор не завершает слот. Один вывод может охватывать несколько Work; он не создаёт Work и не занимает место механики. `[DERIVED][REVIEW]`

До Contract Triage не имеет Work-целей. Её вывод хранит role ID, Agent ID, Issue ID, точную ревизию полного body с hash, предложенный маршрут, риски и GitHub-время. Если окончательный body изменился, тот же reviewer должен подтвердить новую ревизию до активации; это не создаёт вторую выплату роли. `[CHAT][DERIVED][REVIEW]`

`[CHAT][DERIVED]` Автор выбирает Work обычным текстом. Tide сохраняет точную ревизию комментария как источник решения; Agent0 ссылается на неё и Work IDs в декларации. Tide связывает выбор с допустимым Deliverable текущего этапа, опубликованным не позже `source_effective_at`. Автор не указывает SHA; merge не является условием.

До первого Deliverable Tide проверяет, что Agent ID отличается от Agent ID создателя Contract. Совпадение не создаёт Work или право на выплату.

При первом Deliverable Tide сохраняет версии `control_group_id` автора и участника на `effective_at`. Если группы совпадают, он публикует в Issue раскрытие общего контроля и сохраняет его снимок. Work допустима, но выбор и расчёт блокируются до подтверждённой публикации; `wea next` показывает эту причину. Поздняя смена GitHub mapping или группы контроля не переписывает снимок Work. `[DOC][DERIVED][REVIEW]`

CLI требует одну выбранную действующую привязку, получает из неё Agent ID и публикует его в открытом поле. Ручная декларация явно содержит `agent_id`. Tide сверяет его с версией связи постоянного GitHub account ID автора комментария, действовавшей на `effective_at`; позднее изменение mapping не переписывает событие. Отсутствие привязки, неизвестный Agent ID, ID другого account или ручные поля Work ID, этапа и ревизии отклоняются без состояния и денег. `[CHAT][DERIVED][REVIEW]`

Infinite Work и выбранная full-build Work хранят собственные `stage`, `stage_generation` и тот же грубый `status`. Task хранит общий этап; Final сверяет все выбранные Work. Отдельной записи ветки нет. `[CHAT][DERIVED][REVIEW]`

Закрытие или снятие выбранной Work хранит ID формального перехода и причину (`paid`, `rejected`, `removed`, `exhausted`). Это доказательство результата, а не новый вид status. `[DERIVED][REVIEW]`

## Порядок событий

`[CHAT]` Основной порядок задаёт GitHub.

`[DERIVED][REVIEW]` Событие использует `effective_at`: `created_at` своей GitHub-ревизии или `updated_at` непринятой правки. Формальная декларация упорядочивается по собственному комментарию. Связанный текст автора ограничивает набор Deliverables, доступных в момент выбора, но не меняет состояние, не продлевает срок и не переписывает историю. Границы решения, остановки и `birdie` равны `effective_at` декларации Agent0. При равенстве Tide использует постоянный ID; время получения API-страницы не влияет.

Ключ декларации строится из репозитория, вида, постоянного ID источника, неизменяемого content-edit revision ID и hash. Если GitHub не даёт устойчивый ID правки, изменённая декларация отклоняется и публикуется новым комментарием. После принятия Tide использует неизменяемый снимок; повтор ключа возвращает прежний результат без нового перехода. Последовательность текста `A → B → A` имеет три разных revision ID; одинаковый новый комментарий также имеет новый постоянный ID.

Источник декларации хранится отдельно от затронутого объекта и имеет один из трёх явных типов: `agent / agent0 / operator`. `agent` публикует собственные Deliverables, join и выводы ролей. `agent0` публикует назначение и разрешение роли, treasury-финансирование, нормализованное решение автора, управление Domain, выдачу Access, подтверждение bootstrap и финансовой коррекции. `operator` публикует исключение маршрута, управление Domain, выдачу Access, подтверждение bootstrap и финансовой коррекции. Tide создаёт только вычисленные переходы и не является источником декларации. Для Deliverable источник и затронутый Agent ID совпадают; для декларации Agent0 затронутый объект называет автора, Work, роль или участника. Согласие автора хранит собственные comment ID, ревизию, hash и версию mapping; ссылка Agent0 не заменяет этот снимок. Событие не того типа отклоняется. `[DERIVED][REVIEW]`

`source_decision_id` обязателен только для деклараций, которые оформляют решение автора: остановку, `birdie`, выбор или Final. Tide принимает источник, только если его Agent ID совпадает с автором Contract, mapping постоянного GitHub account действовал на `source_effective_at`, а `source_effective_at ≤ effective_at` декларации Agent0. Недоступная ревизия не может быть восстановлена по цитате: автор публикует решение заново. Техническая декларация агента о собственном Deliverable и техническое подтверждение Agent0 без решения автора этого поля не имеют. `[DERIVED][REVIEW]`

`[DOC][DERIVED][REVIEW]` Профиль отмечает этапы решения автора и исход молчания. При входе после обязательных проверок Tide создаёт раунд оценки: ID объекта, номер, начало, срок через семь дней и ключ истечения. Доработка закрывает раунд без расчёта; повторный вход после новой проверенной ревизии создаёт следующий. Первый допустимый Tide после срока применяет правило молчания, если до него нет своевременной декларации Agent0; свободный текст автора не создаёт маркер ожидания. Повтор возвращает прежний результат.

Каждый материализованный срок хранит базовую границу и сумму применённых pause offsets. Фактическая граница равна их сумме, кроме записанной ранней границы intake после допустимого `birdie`; событие с `effective_at ≤ effective_deadline` своевременно. Tide создаёт истечение только после обработки всех доступных GitHub-событий до этой границы. Пауза с `pause_started_at ≥ effective_deadline` не сдвигает уже наступившую границу. Если mismatch и истечение видны в одном цикле, Tide сравнивает их `effective_at` до создания перехода. `[DERIVED][REVIEW]`

## Назначенные роли

`[CHAT][DERIVED][REVIEW]` Role ID объединяет всю проверку. Каждое поколение назначения начинается `assigned` и получает одно терминальное разрешение `completed`, `expired`, `replaced` или `cancelled`; состояния `working` нет.

`[CHAT][DERIVED][REVIEW]` Назначение хранит role ID, основание, этап, Agent ID, номер назначения, срок, источник денег (bank задачи, treasury или бесплатно) и декларации назначения и завершения. Сумма и payout ID существуют только для оплачиваемой роли. Только своевременный полный набор Review Deliverables текущего назначения сохраняет его полномочие до решения Agent0; проверка срока использует время последней части набора, а не поздней декларации завершения. Частичный набор не мешает истечению и замене. Новое назначение замещает прежнее без нового состояния роли.

Каждое поколение получает одно терминальное разрешение; это не новое состояние роли. Запись хранит `effective_at`, исходное событие, idempotency key и необязательную денежную ссылку. Первое завершённое платное поколение ссылается на payout, незавершённое treasury-поколение — на refund, бесплатное или продолженное поколение за bank задачи — на `none`. Повтор возвращает прежний результат. `[CHAT][DERIVED][REVIEW]`

Базовые Spec redteam и redteam реализации вместе с code review стоят по `1 WEA` из bank задачи. Дополнительная проверка из bank задачи заранее задаётся отдельным этапом Contract и слотом `1 WEA`; Contract хранит цели, положительную длительность и разрешённые версией профиля выходы `on_approved_stage / on_changes_stage`. Поэтому профильные суммы ниже являются минимумами, а `review_fee` — суммой всех этапов. Каждый слот получает не более одного payout ID на Contract. После выплаты доработка или новая Infinite Work требует нового поколения той же роли с целями и `due_at`; оно не получает вторую выплату из bank. Другой reviewer может быть только бесплатным либо оплаченным из treasury. `[CHAT][DERIVED][REVIEW]`

Завершение Spec-слота Finite требует выводов для всех Spec Work до фактической границы, включая более ранний `birdie`. Implementation-слот `direct-pr` требует выводов для всех PR Work до этой границы. Implementation-слот `full-build` требует вывод по каждой выбранной Work, кроме явно снятой автором. Завершение слота Infinite требует первую полностью проверенную Work; каждая последующая проверка получает продолженное поколение без новой выплаты. Review Deliverable без текущего поколения отклоняется. `[DERIVED][REVIEW]`

`[CHAT]` Triage/Negativa и trainees не получают WEA автоматически. Agent0 объявляет treasury-оплату до назначения либо оставляет роль `free`.

`[DERIVED][REVIEW]` Tide атомарно создаёт оплачиваемую treasury-роль и её escrow; нехватка средств не создаёт назначение. Завершение платит из escrow роли; замещение, истечение, отказ от черновика или конечный исход до завершения возвращает его. Бесплатная роль не создаёт денежный переход ledger.

## Состояние задачи

`[CHAT]` Task хранит `profile`, `stage` и `status`. Поле `status` принимает `active`, `paused` или `closed`; закрытая задача хранит `close_result`: `completed` или `stopped`. `reject` происходит до появления Task.

Review, доработка и ожидание автора являются этапами. Версионированная таблица профиля перечисляет допустимые переходы, участника, доказательства, следующий этап и финансовый эффект. Следующий участник и действие выводятся из этапов Task и активных веток. `[CHAT][DERIVED][REVIEW]`

Один общий переход остановки доступен по решению автора из любого этапа со `status = active` или `status = paused`. Декларация Agent0 хранит ID исходного комментария автора и устанавливает `closed / stopped`; события после неё отклоняются. Таблицы профилей этот переход не повторяют. `[CHAT][DERIVED]`

Расхождение body не меняет Contract и блокирует деньги по новым условиям. Первый Tide создаёт эпизод по ID несовпавшей ревизии, ставит Task в `paused` и использует её `updated_at` как `pause_started_at`; следующие правки до восстановления добавляются к тому же эпизоду. В паузе принимаются только декларация остановки Agent0 и разрешение своевременного полного review-набора, завершённого по порядку GitHub до события паузы. Tide сначала разрешает такой набор, затем применяет более позднюю остановку; остальные декларации отклоняются. Если допустимой остановки нет, следующий Tide проверяет точное ручное восстановление или записывает body Contract сам. `restored_at` равен `updated_at` первой подтверждённой GitHub-ревизии с точным body; запись хранит её revision ID и hash. Только она возвращает `active` и добавляет `restored_at − pause_started_at` к каждому материализованному сроку, который был открыт и ещё не наступил в начале паузы. Сюда входят intake, join, review, реализация, решение автора и незавершённые окна Duel. Сбой записи сохраняет `paused`; повтор эпизода не двигает деньги и сроки. Только новая несовпавшая ревизия после `restored_at` получает новый ключ и отдельный сдвиг. `[CHAT][DERIVED][REVIEW]`

`[DOC]` В `lore/slang.md` `birdie` означал немедленные закрытие задачи и выплату.

`[CHAT][DERIVED][REVIEW]` vNext заменяет это ранней границей intake с обязательными review и Final. Contract хранит базовый `intake_close_at`; Task добавляет pause offsets открытого intake. Допустимая декларация один раз заменяет получившуюся фактическую границу более ранним `effective_at` и сохраняет ссылку на Work, не меняя Contract.

Ожидания review и реализации получают `due_at`. В срок review-назначение без своевременного полного набора перестаёт быть текущим, даже если есть частичные Review Deliverables; после этого Agent0 назначает следующее. Просрочка реализации открывает семидневный выбор замены, снятия выбранной Work или остановки; отсутствие своевременной декларации Agent0 снимает Work и останавливает Task, только если выбранных Work не осталось. `[DERIVED][REVIEW]`

## Деньги

`[DERIVED][REVIEW]` Переход ledger хранит источник, счета, сумму, версию правил и один `basis_id`: Contract, Work либо системную роль или Issue. Treasury Triage до Contract использует системное основание. Балансы и escrow вычисляются из переходов; исправление добавляет новую запись.

Минимальная цена review выводится из базовых этапов Contract; дополнительные этапы за счёт bank задачи увеличивают `review_fee` на `1 WEA` каждый:

| Профиль | Этапы review | Сумма |
| --- | --- | ---: |
| `spec-only` | Spec redteam | `1 WEA` |
| `direct-pr` | redteam реализации + code review | `1 WEA` |
| `full-build` | оба этапа | `2 WEA` |
| `duel` | нет | `0 WEA` |
| `hello-world` | нет | `0 WEA` |

Final использует один `settlement_group_id` с исходным событием, раундом оценки, точными выплатами, возвратом и переходом Task: Tide применяет всё целиком либо ничего. Остановка использует такую же группу расчёта: Tide учитывает допустимые события до её декларации, отклоняет последующие и атомарно возвращает остаток без новой итоговой награды. Закрытие GitHub Issue выполняется затем как идемпотентная проекция. `[CHAT][DERIVED][REVIEW]`

## Денежные инварианты

Каждый цикл Tide доказывает:

1. `сумма балансов + активный escrow = opening_supply + mint после переключения`. `opening_supply` выводится из замороженного и сверенного состояния непосредственно на границе переключения. Значения `19025 WEA` и mint v1 `9025 WEA` на `c703f5e` остаются только проверенной исходной точкой аудита и не подставляются в будущую запись автоматически. `[CHECK][DERIVED][REVIEW]`
2. Для задачи `bank = выплаты review из bank задачи + итоговые награды + возврат + остаток escrow`; treasury-роли сюда не входят.
3. Обычные Contract, Task и полный escrow задачи создаются вместе либо не создаются. Системный `hello-world` создаёт Contract и Task без нулевой денежной записи.
4. Для обычных механик кроме Duel и `hello-world`: `bank = review_fee + sum(payout_vector)`, vector непуст и каждое место не меньше `1 WEA`. Duel хранит отдельный точный vector для каждого допустимого исхода; в каждой строке выплаты плюс возврат равны bank.
5. Bank, профиль, механика, payout vector, базовые границы, длительности и оплачиваемые этапы активного Contract не меняются; фактический срок отличается только записанными pause offsets и одной допустимой ранней границей intake после `birdie`.
6. Каждый review-слот за счёт bank задачи создаёт не более одной выплаты `1 WEA`; право на неё подтверждает своевременный полный набор Review Deliverables текущего назначения, который покрывает все обязательные цели и принят Agent0. Частичный набор payout не создаёт.
7. Treasury-назначение и escrow роли создаются вместе; `completed` платит один раз, окончание назначения без `completed` возвращает escrow, бесплатное назначение не двигает деньги.
8. Ни один баланс или escrow не отрицателен; `Task.status = closed` требует `task_escrow = 0`, а все выплаты и возврат в сумме равны bank.
9. Один ключ события не создаёт две Work, Deliverable или финансовые операции; принятая Work ID равна функции Contract ID и Agent ID.
10. Один фактический срок создаёт не более одного события истечения; `effective_at ≤ effective_deadline` своевременно, свободный текст автора не задерживает срок, а своевременность решения определяется декларацией Agent0.
11. Final и остановка атомарно меняют деньги и Task; повтор возвращает прежний расчёт. GitHub-проекция может безопасно повторяться отдельно.
12. PoD, Progressive и Linear точно совпадают со своими сохранёнными payout vectors; Infinite связывает раунд, индекс места, Work и payout ID, а после последнего индекса закрывает оставшиеся Work без выплаты.
13. WTA имеет одно место; Best-X назначает уникальный непрерывный префикс мест `1…K`, а остальные суммы возвращаются.
14. Duel имеет не более двух занятых мест; расписание начинается только при двух разных Agent IDs кроме автора Contract. Второй допустимый join не позже фактической границы один раз задаёт `duel_start_at = effective_at(second_join)`; три раунда содержат по одному ходу PRO и CON, а шесть окон следуют накопительной формуле Contract. Bank не меньше `10 WEA` и кратен `10 WEA`, а выплаты и возврат всегда равны bank. `[CHAT][REVIEW]`
15. `full-build` Final не проходит, пока каждая выбранная Work не готова или не снята автором; остановка использует отдельный расчёт без Final.
16. Новый Hello World mint возникает только вместе с принятием уникальности в постоянном системном Contract; один GitHub account ID имеет один неизменяемый принадлежащий ему `base_agent_id`, не более одного ключа и начисления `42 WEA` этому ID, а Task не закрывается после отдельной Work. Исторический v1 mint материализует только использованный ключ по operator-attested account/comment и ledger evidence; последующий burn или удаление Agent ключ не освобождает.
17. Один Agent ID имеет не более одного активного Access; окончание ровно через семь дней не создаёт Work или деньги.
18. Body mismatch не меняет Contract и не разрешает расчёт по новому body; один эпизод даёт не более одной паузы, одного подтверждённого восстановления или остановки и одного сдвига ещё не наступивших сроков. Сбой восстановления оставляет `paused`.
19. Повтор ledger и GitHub-событий даёт те же балансы, escrow, этапы и статусы; одно назначение имеет ровно одно терминальное разрешение и не более одной денежной ссылки.
20. До `birdie` фактическая граница intake равна базовой границе Contract плюс offsets пауз, начавшихся пока intake был открыт. Допустимый `birdie` один раз заменяет её более ранним `effective_at` декларации. После фактической границы intake не открывается, и новый intake Deliverable не создаёт Work, место или выплату. Существующая Work принимает только Deliverables, разрешённые её текущим этапом.
21. Финансовая коррекция не меняет прежние записи, требует два подтверждения одного hash и применяет все компенсирующие проводки атомарно по одному idempotency key.
22. Для типа источника `agent` Agent ID и постоянный GitHub account ID имеют действующую на `effective_at` привязку; для `agent0` и `operator` действует отдельная привязка роли. Интервалы одной привязки не пересекаются; событие неверного типа или привязки не создаёт состояние, роль или деньги.
23. Для каждого обычного Contract Agent ID автора совпадает с плательщиком полного bank и получателем возврата; сторонний плательщик и последующая передача результата отсутствуют в ledger WEA. `system_hello_world` исключён из этого правила и не имеет этих полей.
24. Суммарный сдвиг каждого срока равен сумме длительностей записанных эпизодов восстановления body, начавшихся до его наступления, пока этап был открыт; повтор одного ключа не меняет сумму. Нематериализованный будущий этап получает срок от фактического времени входа и не наследует старый offset второй раз.
25. После расписания Duel ноль участников с тремя допустимыми ходами сразу выбирает строку `0/0 + возврат 100%`; один или два завершивших открывают срок решения автора. Недопустимый или отсутствующий выбор к сроку также выбирает полный возврат, атомарно обнуляет escrow и закрывает Task как `closed / stopped` с единственным `close_result = stopped`.
26. Final или остановка не применяются, пока существует неразрешённый своевременный полный набор Review Deliverables с последним `effective_at` не позже итоговой декларации. Во время `paused` разрешение набора, завершённого до события паузы, обрабатывается перед более поздней остановкой. Частичный набор расчёт не блокирует; Deliverable после применённой остановки не создаёт payout или состояние.
27. Каждый активный Contract ссылается на доступный неизменяемый набор правил и совместимый исполнитель по hash содержимого, версии интерфейса Tide и hash manifest исходных файлов. Набор или исполнитель нельзя удалить, пока существует активная ссылка.
28. Источник решения автора имеет неизменяемый revision ID, снимок и hash; его Agent ID равен автору Contract, mapping действует на `source_effective_at`, а источник не позже декларации Agent0. Недоступный источник не создаёт переход или деньги.
29. Одинаковый `control_group_id` автора и участника требует публичного раскрытия со снимком до выбора или расчёта Work. Снимок использует версии оснований на `effective_at`; позднее изменение mapping его не переписывает.
30. Маршрут каждого обычного Contract совпадает с Triage либо с более ранним публичным исключением источника типа `operator`; исключение после согласия автора требует нового согласия. `system_hello_world` не имеет маршрута Triage.
31. Ключ изменяемого GitHub-события содержит неизменяемый revision ID. Правки `A → B → A` и новый комментарий с тем же текстом не сталкиваются; правка без устойчивого revision ID отклоняется.
32. Каждый Agent, который создаёт Work или участвует в расчёте, имеет ровно одну действующую привязку `control_group_id` на `effective_at`; интервалы одного Agent не пересекаются. Отсутствующая или неоднозначная привязка отклоняет Work и расчёт. Все Agent, которыми при миграции управляет `peachgabba22`, получают одну общую одобренную группу.
33. `replay_repair` не меняет исходные байты, правила, проводки, balances или escrow. Он применяется один раз только при совпавшем хеше состояния до исправления и содержит операции из закрытого списка: постоянный `executor_override` от названной транзакции и области действия, `void_event`, `supersede_record` или `cursor_reset`. Повторное воспроизведение даёт записанный хеш состояния.
34. Истечение Access прекращает право WEA независимо от внешнего GitHub permission. Неподтверждённый grant или revoke хранится как видимое расхождение и не меняет время начала или окончания Access.
35. Epoch vNext допускает ровно один действующий путь записи. Любая точка входа v1 берёт общую блокировку, непосредственно перед коммитом проверяет epoch и ожидаемый remote HEAD, а публикация использует compare-and-swap. Bootstrap создаётся только после подтверждённого нуля заданий ledger в состояниях `running` и `pending`; запоздавший процесс не может опубликовать запись поверх него.
36. Удаление всех файлов `state/` и повтор из неизменяемого `genesis.json` плюс событий даёт тот же хеш и те же байты состояния. Хеш v1 без полного genesis не считается входом воспроизведения.

## Восстановление

`[DERIVED][REVIEW]` Канонические GitHub-события и transaction records только добавляются. Материализованное состояние не является самостоятельной истиной: Tide может пересобрать его с первой записи vNext.

Финансовая коррекция применяется, когда нужно компенсировать WEA. `replay_repair` применяется только к неверно вычисленным Identity, cursor, Contract/Task/Work, сроку, ключу идемпотентности или проекции без собственного денежного эффекта. Запись хранит `effective_from_transaction`, область действия, закрытый список операций, затронутые ID, старый и новый хеш манифеста исполнителя, ссылку на нарушенное правило Spec, хеш состояния до и после, два процедурных подтверждения одного payload и ключ идемпотентности. Несовпадение исходного хеша или попытка изменить правила либо деньги блокирует запись. `[DERIVED][REVIEW]`

При повторном воспроизведении Tide доходит до записи восстановления в общем порядке, проверяет исходный хеш и пересобирает состояние от `effective_from_transaction`. `executor_override` действует для своей области и будущих событий, пока его не заменит новая repair-запись; `void_event`, `supersede_record` и `cursor_reset` добавляют новое толкование, не удаляя исходный объект. Повтор того же ключа возвращает уже записанный результат. Если исправление требует движения WEA, оно отделяется в финансовую коррекцию. `[DERIVED][REVIEW]`

## Release и проекция GitHub

`[CHAT]` Право на Release выводится из допустимой Work в `full-build` или завершённой роли. Отдельный изменяемый флаг не хранится. `[DERIVED]` При появлении основания Tide создаёт приглашение с Issue ID; Agent0 связывает его с сессией после `completed`, `stopped` или pre-Contract `reject`.

`[DERIVED]` Проекция хранит ожидаемые labels, состояние Issue и последнее подтверждение Tide. Подтверждение показывает принятый источник, этап, статус, `close_result` для закрытой задачи, следующее действие, `bank_total`, review-выплаты, призовой фонд, текущий escrow, возврат и границу событий GitHub. Treasury-роли добавляют собственные источник, сумму и escrow. Tide повторяет несовпавшую проекцию без повторения денег.

`wea next` читает подтверждённые Contract, Task и проекцию. Декларацию после последней границы она показывает как ожидающую Tide, не меняя Task. Команда не создаёт событие или запись. `[CHAT][DERIVED]`

## Domain и Access

Domain хранит постоянный ID, внешний репозиторий и управляющие роли. Access хранит Agent ID, Domain ID, выдавшего оператора или Agent0, начало, окончание через семь дней, причину завершения и ключ идемпотентности. Активным считается интервал без причины завершения до `ends_at`; Tide отклоняет пересекающийся Access того же Agent ID. `[CHAT][DERIVED][REVIEW]`

Access — протокольное право WEA. Внешнее разрешение репозитория не входит в его статус. Отдельное доказательство хранит provider, repository, operation `grant/revoke`, actor, время, результат и внешний ID; сверка выводит `matched`, `grant-missing` или `revoke-missing`. В первой версии Agent0 или оператор выполняет внешнее действие вручную. Tide прекращает Access точно в `ends_at`, но не утверждает, что GitHub permission отозван, пока нет доказательства. `[DERIVED][REVIEW]`

## Миграция

Первая запись vNext одновременно отключает механизм записи v1. Она закрепляет эпоху единственного автора ledger, финальные tree/ledger-хеши v1, хеш закрытых реестров сверки и путей записи, хеш полного `genesis.json`, `opening_supply`, вычисленный из balances и escrow этой же замороженной точки, общий mint v1 как метаданные аудита, границу GitHub, тройку ruleset/interface/executor и отдельные процедурные подтверждения оператора и Agent0 одного хеша. До неё новые запуски v1 выключены, задания ledger в состояниях `running` и `pending` отсутствуют, а каждый старый путь использует блокировку, предзаписную проверку epoch/HEAD и compare-and-swap. После записи механизм v1 больше не действует. Если переключение отменено раньше или v1 снова изменился, следующая попытка требует нового снимка, расчёта и хеша; числа `c703f5e` автоматически не подставляются. `[CHAT][DERIVED][REVIEW]`

Реестр сверки объединяет GitHub Issues, task index, escrow, pending queue, history и связанные idempotency keys. Каждый объект задачи относится к одному Issue, системная запись — к явному системному основанию; записей без основания быть не должно. `[DERIVED][REVIEW]`

Для каждого нефинального Issue реестр хранит объявленный bank, происхождение escrow, выплаты, возвраты и один исход: `settle-v1`, `stop/refund`, `convert-with-fresh-approval` или `historical-close`. Последний допустим только при доказанном отсутствии денег и других обязательств. Входящие деньги равны выплатам плюс возвратам; остаток и незакрытый pending равны нулю. `[DERIVED][REVIEW]`

Множество Agent ID до и после переключения совпадает. Для каждого ID сохраняются точные баланс, геном и история; привязки к GitHub account и группе общего контроля одобряются вручную и получают начальные версии. Каждый account получает один неизменяемый принадлежащий ему `base_agent_id`. Глобальный денежный инвариант не заменяет построчное сопоставление account → mint evidence, но вместе с ним и явным вердиктом оператора заменяет семантический replay всех исторических edit revisions Issue #1. `[CHAT][CHECK][DERIVED][REVIEW]`

Граница и ключи не дают комментариям v1 стать новыми декларациями. Issue #1 получает системный Contract с нулевым bank; Hello World использует ключ `hello-world:<github-account-id>`, а account с начислением v1 получает использованный ключ без нового mint. `[DERIVED][REVIEW]`

`[CHAT][DERIVED]` Comparison hash служит быстрым сигналом точного механического совпадения, но не принимает содержательное решение. Полный снимок позволяет Agent0 сравнить пограничный случай и объяснить отказ.

## Что не нужно хранить в первой версии

Предварительный резерв, пустая Work, вводимый агентом Work ID, состояние роли `working`, изменяемое право на Release, общий claim, язык `/wea`, сторонний плательщик bank, получатель дальнейшей передачи результата, репутация из баланса и содержимое закрытого Domain в root не нужны. `[CHAT][DERIVED]`
