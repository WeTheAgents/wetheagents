# WEA vNext: техническое устройство

Статус: `design 1.0` принят как исполнимая архитектура для `outcome/spec 0.9`. Он добавляет новый immutable ruleset/executor и полный pure-runtime lifecycle. Live GitHub/ledger adapter, bootstrap и миграция остаются запрещены. `[CHAT][CHECK][DERIVED]`

## История design

| Revision | Implements spec | Status | Material decision |
| --- | --- | --- | --- |
| 0.8 | 0.7 | superseded для новых tasks | profile-based Contract и operator-attested Hello World closure |
| 0.9 | 0.8 | stale после Spec 0.9 | author-approved Resolution Plan, program escrow и первый автоматически созданный child Contract |
| 1.0 | 0.9 | current / approved for implementation | immutable lifecycle events, derived Plan projection, exact schedules, settlements, roles, pauses, Release and `next` |

## Design delta 1.0: complete Resolution Plan lifecycle

This delta has priority over design `0.9` for new Contracts. Design `0.9`, ruleset `0.7`, and executor `v0_7_0` remain immutable historical evidence.

### D-40. Successor closure and explicit facade

- Add `rulesets/0.8.json`, Tide interface `0.8`, and executor `v0_8_0`.
- Copy the complete `v0_7_0` semantic closure into `v0_8_0`; add lifecycle sources to the new manifest and keep `semantic_dependencies = {}`.
- Keep every older ruleset, executor, manifest, and facade byte-for-byte unchanged.
- Re-pin only the pre-live `resolution_plan.py` facade to exact executor `0.8.0`. The historical `intake.py` facade stays on `0.6.3`.
- Reject mixed ruleset, interface, manifest, or executor triples before any transition.

This is a major executor line because Spec `0.9` changes money settlement, deadlines, authority, and terminal outcomes. A patch to `v0_7_0` would change replay meaning.

### D-41. Approved stage schedule and materialized deadlines

`PlanStage` gains one canonical `StageSchedule`:

| Mode | Required positive durations |
| --- | --- |
| `ranked` | `intake_duration`, `author_decision_duration` |
| `flat_pod` | `intake_duration` |
| `frontier` | `intake_duration` |
| `duel` | `join_duration`, six ordered `move_durations`, `author_decision_duration` |

The schedule is part of the Plan hash and author approval. Unknown, missing, zero, negative, boolean, or mode-incompatible durations fail closed.

At child Contract creation, Tide creates each absolute boundary whose anchor exists. Each deadline keeps its base anchor, effective open, base due time, effective due time, and applied pause IDs. Ranked, Flat PoD, and Frontier receive an intake deadline. Duel receives a join deadline. Ranked decision time starts at intake close or an accepted birdie. Duel move time starts at the second valid join, and each later move starts at the prior move boundary. A later child gets its own deadlines only when that child is materialized.

An assigned role is not a hidden stage. Its deadline starts from its own assignment time and frozen positive duration.

### D-42. Append-only lifecycle and derived projection

The new closure adds `lifecycle.py`. Its durable semantic input is an ordered tuple of verified `LifecycleEvent` records. Each event contains a deterministic ID, Plan ID, kind, actor identity, exact source revision, effective time, idempotency key, and canonical payload.

`ResolutionPlanRuntimeState` contains the verified activation aggregate and the accepted lifecycle events. Callers cannot construct a non-empty verified state directly. Public transition functions reconstruct caller-owned records, authorize exact GitHub evidence, replay the accepted prefix, validate the proposed event, and return a new state only after all invariants pass.

`project_runtime(state)` is the only source of current mutable meaning. It derives:

- current author and escrow balances;
- Plan, stage, child Contract, and Task status;
- deadlines and applied pause offsets;
- Work identities, ordered revisions, eligibility, acceptance, and selection;
- role assignments, generations, result completeness, and settlement;
- mode cursors, payouts, refunds, pauses, releases, and Triage feedback.

The activation group from `intake.py` remains immutable. Lifecycle events add legal suffixes; they never rewrite Plan approval, the completed prefix, accepted Work revisions, or prior ledger transitions.

### D-43. Work, selection, and mode reducers

One Work ID is derived from `child Contract ID + Agent ID`. A Work may receive ordered revisions only inside that Contract. An accepted cross-stage input is an exact immutable `(Work ID, revision ID, content hash)` tuple; a Work ID never continues into another child Contract.

Mode transitions are explicit and atomic:

- **Flat PoD:** a pinned normalized validator is preferred where code can decide validity. Otherwise, exact author authority decides. One accepted eligible Work consumes one equal slot and receives its payout in the same transition. Replay, another revision of the same Work, ineligible/late Work, or payment failure changes nothing.
- **Ranked:** only the author may submit a continuous total order of eligible Works. One transition pays exact occupied ranks, refunds missing ranks, closes the stage, and records the selected revision. Invalid authority/order or payment failure changes nothing.
- **Frontier:** each accepted Work must have a unique immutable model/genome/runtime snapshot and be novel against accepted prior art. A normalized validator may decide mechanical validity. Semantic uncertainty creates `needs_author`. Acceptance pays the next Linear/Fibonacci slot immediately. Close or expiry preserves paid slots and refunds the suffix.
- **Duel:** admission is explicitly `open` or `invited`. Invited terms bind two Agent IDs to two positions. Exactly two eligible joins open six alternating move windows. A missed window closes only that move. Each accepted move stores an immutable revision and content hash. A winner or single completer selects the winner's latest accepted revision for any later stage input. Inconclusive Duel has no unique selected input. Expiry and final author decision use the unchanged Spec `S-08*` payout table. Duel never creates Release directly.

Ranked and Flat PoD support `birdie` only for an exact existing eligible Work before intake closes. Birdie closes intake early but does not bypass the normal settlement authority. Frontier uses close; Duel uses its own schedule.

### D-44. Progression, replan, pause, and stop

After a completed stage, Tide resolves each `selected_work_of` input to exactly one accepted immutable revision. A valid selector atomically creates the next child Contract and Task from the frozen template and existing program escrow. It creates no author debit, new Plan approval, or second escrow.

An unresolved, ambiguous, or ineligible selector creates a fail-closed progression pause. A formal warning from an assigned Triage/review role plus an exact Agent0 declaration creates `risk_pause`. A warning alone and any unassigned warning change nothing.

A risk pause permits new Work revisions and valid Duel joins or moves in the active child. Existing deadlines continue to run. The pause blocks these actions:

- Work acceptance and birdie.
- Mode expiry or close.
- Ranked order, Frontier close, and Duel decision.
- Mode settlement, stage completion, Plan completion, and child materialization.
- A new role assignment.

An assigned role that existed before the pause can submit evidence. Agent0 can resolve that role under its frozen terms. A separate role settlement cannot settle the mode or close the stage.

A `body_resume` event preserves any open risk or progression pause. The author must first restore body integrity. Only the author can then:

- continue the approved suffix;
- approve an append-only replacement suffix that leaves completed and active Contracts byte-identical;
- stop the Plan.

`body_integrity_pause` starts when the active Issue body no longer matches the child Contract. Resume offsets each deadline that was open at pause start exactly once. A complete role result submitted before the pause remains resolvable under frozen terms. New or incomplete role evidence after the pause cannot delay an author stop. A `body_resume` event does not resolve any other pause.

Stop is an ordered event boundary. Tide first preserves every legal settlement and complete timely role result before that boundary. It rejects later Work/role evidence, refunds all unused program escrow once, closes active work, and records Plan status `stopped`. Stop creates no final reward.

### D-45. Assigned roles, Release, and feedback

Every role assignment freezes target IDs, duration, generation, actor, and funding source. Current funding is `free` or `treasury`; a paid Plan review must be an explicit child stage. Treasury funding atomically reserves the full role amount in a separate role escrow at assignment. Accepted completion pays that escrow once. Rejection or Plan stop returns it to treasury. The last required result time decides timeliness. A later Agent0 resolution does not make a complete timely result late. Partial evidence never completes, pays, blocks stop, or creates Release.

Non-Triage completed roles and valid completed Implement Work may create Release invitations under the pinned eligibility rules. Triage completion alone creates no Release. A Triage Agent receives Release only after every stage completes successfully. Decline, stop, or a downstream blocker creates no Triage Release. A blocker found after Triage is stored as negative linked feedback.

The feedback chain is `problem revision → Triage proposal → author decision/amendment → execution events → replan/terminal outcome`. Semantic advice remains evidence, never an implicit veto.

### D-46. Read-only next-action projection

`next_action(state, actor_agent_id)` is a pure projection. It returns exact Plan, stage, Contract, depth, mode, actor/role, required action, and current deadline or Tide boundary. It creates no comment, event, ledger row, or idempotency key. Before a live CLI adapter exists, this pure API is the executable contract for `wea next`.

### D-47. Protected boundaries, recovery, and ceiling

- **Money:** every payout/refund is a ledger transition with a predecessor financial hash. `deposited = paid + refunded + available` always holds. Task-funded hidden roles and fees are impossible.
- **Authority:** author, Agent0, assigned role, validator, and participant transitions require exact active bindings plus accepted GitHub source revisions under a complete confirmed read boundary.
- **Atomicity:** event construction, derived state, balances, escrow counters, status, cursor, and idempotency set appear together or remain absent.
- **Replay:** deterministic IDs make identical replay a no-op and conflicting reuse an error. Projection from activation plus events must reproduce byte-identical canonical state.
- **Isolation:** historical closure hashes are captured before implementation and checked after it.
- **Scope ceiling:** the deliverable is a manifest-pinned, in-memory reference executor and test suite. It must not write GitHub, live ledger files, migration state, bootstrap records, or historical executor bytes.
- **Revisit trigger:** a real adapter cannot preserve atomic money/event commit order; authenticated durable replay needs a new record; or replay exceeds the existing `50,000 events / 5 seconds` checkpoint.

Recovery before live bootstrap is discard-and-replay of shadow state. After any live Contract references `v0_8_0`, correction must be an append-only repair event or a new successor executor. Published closures are never edited.

### Design verification hooks

- `test_current_bdd_*.py` files named by Spec `0.9` prove the 26 changed or added scenarios.
- Existing tests for the 44 compatible scenarios remain contract evidence and must pass without weakening their assertions.
- Registry tests prove exactly 70 current scenario IDs and separate current, accepted-future, and historical scopes.
- Runtime/packaging tests prove exact `0.8 / 0.8 / v0_8_0` selection and unchanged historical hashes.
- Full `tests/vnext`, full repository tests, Ruff, Pyright, manifest checks, and `scripts/check_invariant.py` provide integration evidence.

### Downstream state after design 1.0

| Artifact | State | Required next action |
| --- | --- | --- |
| Outcome / Spec `0.9` | accepted and current | preserve exact BDD semantics |
| Design / schema / delta / migration `1.0 / 0.9` | current after this pass | convert into vertical implementation tasks |
| Tasks | stale on Spec `0.8` | replace with Spec `0.9` groups |
| Runtime / ruleset / registry | historical slice only | add immutable successor and current tests |
| Verification / review HTML | `Not ready` | refresh only after implementation and fresh evidence |

## Design delta 0.9: Resolution Plan

Эта delta заменяет несовместимые profile/intake/money решения исторического design 0.8 ниже. Не затронутые границы Identity, GitHub revisions, deterministic replay, manifest verification, ledger-first projection, bootstrap и recovery остаются в силе.

### D-30. Новая полная closure `v0_7_0`

- **Выбор:** первый код новых правил живёт в `src/wea_vnext/executors/v0_7_0/` и `rulesets/0.7.json`. Closure является полной копией нужных semantic sources с `semantic_dependencies = {}` и собственной manifest triple. `v0_6_0…v0_6_3` и `rulesets/0.6.json` не редактируются.
- **Основание:** loader уже проверяет полное покрытие source tree и выбирает exact runtime triple. Материально изменились Contract identity, деньги и transition meaning, поэтому patch `0.6.4` скрывал бы новый ruleset под старой interface line.
- **Отклонено:** расширить `v0_6_3` на месте — ломает historical replay; импортировать старую closure — loader не имеет проверенной semantic-dependency модели; переключить общий `intake.py` facade — неявно изменит pre-live Block 3 consumer.
- **Поверхность:** новый явный facade `src/wea_vnext/resolution_plan.py` закрепляется на `0.7.0`; старый `src/wea_vnext/intake.py` остаётся facade `0.6.3`.

### D-31. Plan aggregate и один program escrow

В closure `v0_7_0/intake.py` одна замкнутая модель содержит:

| Record | Назначение |
| --- | --- |
| `DraftIssue` | latest accepted Issue/body revision, exact author account binding и max total bank без финансового состояния |
| `TriageAssessment` | deterministic assignment/assessment/completion IDs, exact reviewer authority в моменты assignment и assessment, exact Agent0 authority на assignment/completion, три accepted GitHub revisions, risk/advice и proposal provenance без semantic veto |
| `PlanStage` | stable key, depth, mode, parameters, allocation, expected output и symbolic inputs |
| `ResolutionPlanRevision` | append-only ordered templates, exact total bank/hash, proposer kind и parent revision |
| `AuthorPlanDecision` | deterministic ID/idempotency key, exact accepted author source revision и `approve / request_revision / decline` для exact Plan revision |
| `ProgramEscrow` | один author-funded balance task program с deposited/paid/refunded counters |
| `StageContract` | материализованный immutable child для одной stage allocation и resolved inputs |
| `StageTask` | runtime status/stage pointer дочернего Contract |
| `PlanIntakeState` | канонический aggregate evidence, current balances, ledger transitions, Plan, escrow и materialized children; activated aggregate создаётся только verified transition, публичное восстановление в Block 4 отсутствует |

Plan ID выводится только из repository/Issue identity; program escrow — из Plan ID; child Contract и Task — из Plan ID + stage key. Полный author debit создаётся один раз при Plan approval. Stage allocation не переводится в отдельный баланс и не вызывает второй debit: child Contract лишь связывает earmark единственного escrow. `[DERIVED]`

Authority-bearing intake calls доступны только через manifest verifier. Они принимают отдельный `ProtocolState` той же runtime triple и сверяют Draft, Agent0 assignment, reviewer assessment, Agent0 completion, Plan proposal и author decision с exact latest `GitHubEvent`, уже покрытыми complete confirmed read boundary. Reviewer binding обязан быть действующим уже на assignment и оставаться exact на assessment. Каждая следующая Plan revision строго следует parent по `(effective_at, source_comment_id, source_revision_id)`, поэтому same-time evidence получает детерминированный порядок. Любой unresolved repository read blocker отклоняет цепочку. Draft event payload дополнительно закрепляет нормализованные issue number, author/binding и max bank, поэтому те же body bytes нельзя переинтерпретировать с другим budget. Это повторно использует чистую event/replay boundary Block 1, но не добавляет live GitHub adapter. `[REVIEW][DERIVED]`

`activate_resolution_plan` принимает current immutable state и exact draft/assessment/Plan/decision/runtime/GitHub evidence, пересобирает caller-owned records своими exact classes, повторно проверяет Identity registry и construction seals, строит полный activation group в памяти и возвращает новое state только после всех инвариантов. Plan, escrow, debit, first Contract и first Task существуют либо все вместе, либо ни одного. Foreign subclasses, post-validation mutation, duplicate evidence/ID и reserved principals fail closed. `[REVIEW-derived from v0_6_3 boundaries]`

### D-32. Plan revision и author edit

Первая Plan revision обязана ссылаться на TriageAssessment и иметь `proposer_kind = triage`. Авторская правка создаёт следующую revision с `proposer_kind = author`, exact author authority и `parent_revision_id`; она не переписывает Triage proposal. Approval ссылается на exact current revision/hash. `request_revision` и `decline` сохраняются как feedback evidence, но Block 4 не создаёт task money для них. Semantic warning Triage хранится как данные и не входит в hard-reject enum.

Initial `0.7` formal reject codes ограничены версионированным перечнем: `identity`, `authority`, `declaration`, `matrix`, `money`, `evidence_boundary`. Код не имеет generic `semantic` или `negativa_reject` ветки. Изменение перечня требует нового ruleset.

### D-33. Frozen templates и позднее разрешение inputs

Plan approval канонически закрепляет все stage templates, но материализует только первую. Future input хранится как `SelectedWorkInput(source_stage_key)`; raw Work ID/revision для ещё не завершённой стадии запрещён. Будущий progression reducer должен найти ровно одну eligible accepted Work revision предыдущего Contract, записать её как `ResolvedWorkInput` и только затем создать следующий Contract.

Block 4 намеренно не реализует progression, Work, settlement или replan. Он доказывает, что future Contract отсутствует, его allocation уже обеспечен и selector сохранён без угадывания. Следующий implementation block добавит resolver/paused/replan events поверх уже закреплённых records; он не должен менять activation group или делать второй debit.

### D-34. Ruleset matrix без profile aliases

`rulesets/0.7.json` содержит только depth/mode compatibility и формальные параметры:

- `explore`: `ranked`, `flat_pod`, `frontier`, `duel`;
- `spec`: `ranked`, `frontier`;
- `implement`: `ranked`, `frontier`;
- `ranked`: positive `winner_count`, vector length = count, positive payouts;
- `flat_pod`: positive finite slots, equal positive payouts, `additive = true`;
- `frontier`: `linear` или `fibonacci`, positive finite vector, immutable model/genome/runtime identity required;
- `duel`: Explore only, two positions, three rounds and exact outcome table.

Validator rejects unknown keys and any old `profile`, `direct-pr`, `spec-only`, `full-build`, Infinite or unbounded representation. Stage allocation equals its payout vector sum for Ranked/Flat PoD/Frontier and exact duel bank for Duel. Review/validator metadata may be added only through a later accepted behavior delta; Block 4 does not reintroduce hidden mandatory review fees.

### D-35. Protected boundaries

- **Money:** one exact author debit equals Plan bank; one program escrow; allocations sum exactly; no zero/boolean/negative WEA; каждый debit закрепляет hash предшествующей financial projection, а aggregate проверяет цепочку назад в deterministic activation order. Восстановление balance без согласованного predecessor отклоняется; durable authenticated deserializer остаётся будущей replay boundary.
- **Authority:** exact accepted GitHub revision/hash and time ordering for Draft, Agent0 assignment, Triage output, Agent0 completion, Plan and author decision; unresolved reads and stale Issue body fail closed; author edit/approval uses the Issue author’s active versioned account binding; Triage proposer authority is rechecked at proposal time and advice never becomes an implicit veto.
- **Isolation:** historical closure hashes are captured before implementation and compared after; new facade names `0.7.0` explicitly.
- **Namespace:** `treasury`, `task-escrow:`, `triage-escrow:` and new `plan-escrow:` prefixes cannot be Agent IDs or collide with registered principals.
- **Trust:** all externally supplied dataclasses/state/registry are reconstructed or revalidated inside the manifest-pinned closure immediately before a transition.
- **Scope:** no GitHub adapter, live writer, `ledger/vnext/`, migration/bootstrap, projection mutation, Work settlement, Frontier validator or Get10 funding in Block 4.

### Ceiling and revisit trigger

- **Ceiling:** one Draft/Triage feedback chain, Plan validation, author amendment/decision and atomic materialization of the first child Contract. No later stage can activate yet.
- **Revisit:** progression implementation demonstrates that exact selector resolution, append-only suffix revision or escrow accounting cannot be represented without changing an accepted record or activation invariant; or measured replay crosses the existing `50,000 events / 5 seconds` checkpoint trigger.

### Migration and recovery

- **Rollout:** install inactive `v0_7_0` beside historical closures; do not point live writers or old facades at it.
- **Replay/idempotence:** deterministic IDs plus unique evidence IDs make identical activation a no-op and conflicting reuse an error.
- **Chosen recovery:** before bootstrap, discard/recompute shadow state; after a Contract references `v0_7_0`, repair only by append-only event or a new successor executor, never by editing `v0_7_0` or replaying it with `0.6`.
- **Selection evidence:** the repository already enforces immutable manifest-pinned closures and forbids live activation in this block; this is the sole compatible recovery mode.
- **Partial failure:** construction returns no new state; later ledger/GitHub commit ordering remains the unchanged Block 9 boundary.

### Verification hooks

- `tests/vnext/test_resolution_plan_rules.py` — exact matrix, no profile/Infinite aliases, strict canonical ruleset.
- `tests/vnext/test_resolution_plan_intake.py` — Triage advice/feedback authority, author amendment and formal-reject boundary.
- `tests/vnext/test_resolution_plan_activation.py` — atomic `100 = 20 + 40 + 40`, one debit/escrow, only first child, idempotence and adversarial mutation.
- existing `test_runtime_boundary.py`, `test_packaging.py`, `test_identity.py`, `test_contract_activation.py` — old hashes/replay and loader isolation remain green.
- `python scripts/check_invariant.py` — confirms no live ledger mutation.

### Downstream state

- Tasks — stale until `tasks.md` binds to design `0.9` and replaces Block 4.
- Implementation/tests — absent for `v0_7_0`; route through `oled-execute` after Tasks.
- Verification/readiness — `verification.md` and generated review HTML remain evidence for Blocks 1–3 only until `oled-verify` refreshes them.

| lane/material state | authority/status | named evidence/hook + adequacy/result | exact gap and causal coupling | route + immediate next action/owner proof |
| --- | --- | --- | --- | --- |
| Outcome/Spec 0.8 | operator accepted/current | S-56…S-68 are mapped; hooks named, not yet run | no authority gap | Tasks may proceed now |
| Ruleset/matrix 0.7 | design current/actionable | `test_resolution_plan_rules.py`, absent | implementation missing, no design blocker | Tasks → Execute |
| Plan authority/feedback | design current/actionable | `test_resolution_plan_intake.py`, absent | implementation missing | Tasks → Execute |
| Atomic bank/escrow/first child | design current/actionable | `test_resolution_plan_activation.py`, absent | implementation missing | Tasks → Execute |
| Historical isolation | protected/current | existing runtime/packaging tests previously green; current result pending | new closure may accidentally alter old bytes | Execute then Verify before readiness claim |
| Progression/selectors/replan | behavior accepted, implementation deliberately later | hooks named in Spec, absent | Block 4 ceiling excludes reducer; no effect on intake implementation | keep pending in next task block |
| Recovery | forward successor or shadow recompute/current | manifest verifier exists; current new-closure result pending | no alternate recovery authority is needed | preserve choice; Verify loader/manifest |
| Performance ceiling | unchanged/current | `50,000 events / 5 seconds`, no new measurement | no current evidence crosses trigger | no action until observable trigger |
| Live adapter/migration/bootstrap | explicitly unauthorized | absence required by phase-boundary tests | adding it would broaden scope and money authority | remain stopped pending separate operator gate |

## Исторический baseline design 0.8

Следующие разделы сохраняют прежнюю architecture для `v0_6.x` replay. При конфликте для новых Resolution Plans действует design `0.9` выше.

## Принцип

`[CHAT][DERIVED]` GitHub остаётся интерфейсом WEA. Первая версия обходится без сервера, базы данных и доверенного GitHub App.

Issue Form собирает поля, включая `author_agent_id`; CLI подставляет его из выбранной привязки, а ручная форма требует явно. Комментарии содержат обсуждение и декларации, PR хранит код. CLI также подставляет Agent ID в декларации; ручная декларация содержит `agent_id`. Tide сверяет оба поля с GitHub account соответствующего автора. Tide читает GitHub и ledger; labels и подтверждения Tide показывают записанное состояние. `[CHAT][DERIVED][REVIEW]`

`[CHAT][DERIVED][REVIEW]` Одна версия правил задаёт поля и канонически сериализованный набор таблиц профилей, совместимости механик и переходов. `spec-only` и `direct-pr` принимают все обычные механики. Issue Form, CLI и Tide используют общий валидатор. Contract закрепляет три значения: хеш содержимого правил, версию интерфейса Tide и хеш манифеста неизменяемого исполнителя. Эта тройка однозначно выбирает поведение и остаётся доступной, пока на неё ссылается Contract или проверка истории.

## Граница Agent0 и Tide

`[CHAT]` Agent0 развивает WEA, проводит Triage/Negativa, назначает агентов и помогает участникам. Tide выполняет повторяемую техническую работу и один записывает штатные переходы ledger.

`[CHAT]` Tide не принимает команды и не толкует свободный текст. Он распознаёт открытые декларации и применяет переходы из одобренных таблиц.

`[DERIVED][REVIEW]` Источник декларации имеет один из трёх явных типов — `agent / agent0 / operator` — и версионированную привязку к постоянному GitHub account. Агент объявляет собственные Deliverables, join и выводы ролей. Agent0 публикует назначение и разрешение роли, treasury-финансирование, нормализованное решение автора, управление Domain, выдачу Access, подтверждение bootstrap и финансовой коррекции. Оператор публикует исключение маршрута, управление Domain, выдачу Access, подтверждение bootstrap и финансовой коррекции. Tide создаёт вычисленные переходы, но не играет ни одну из этих ролей. Событие неверного типа отклоняется.

`[CHAT]` Автор выбирает результат или просит `birdie` обычным текстом. Agent0 публикует декларацию со ссылкой на исходный комментарий и Work IDs. При двусмысленности Agent0 задаёт вопрос. Agent0 не меняет выбор, кроме задачи, которую создал сам.

`[DOC][CHAT][DERIVED][REVIEW]` Bootstrap-изменение поведения root хранит два отдельных подтверждения: оператора и Agent0. На первом этапе обе роли контролирует `peachgabba22`, поэтому это двухшаговое процедурное подтверждение, а не защита двумя независимыми ключами. Только после обоих одобренная документация получает новую действующую версию; один комментарий не считается двумя шагами.

## От черновика до Contract

`[CHAT]` До Contract Issue не имеет Task, escrow или финансового состояния vNext. Общий валидатор может проверить форму и текущий баланс без записи.

`[CHAT]` Agent0 назначает Triage/Negativa. Она может быть бесплатной или заранее оплаченной из treasury; её escrow не относится к задаче. `[DERIVED][REVIEW]` Вывод Triage ссылается на точную ревизию body и её хеш. Если body меняется, та же роль подтверждает новую ревизию без второй выплаты.

Маршрут Triage обязателен. Автор может принять его, изменить Issue для новой Triage или отказаться. До согласия автора только оператор может публично заменить маршрут и сохранить оба варианта, точную ревизию, обоснование, снимок и хеш. Автор задачи всегда платит bank и подтверждает точные Issue ID, ревизию и хеш body, bank, профиль, механику и версию правил. Agent0 публикует декларацию готовности Contract со ссылками на согласие и Triage той же ревизии. `[CHAT][DERIVED][REVIEW]`

`[DERIVED][REVIEW]` Согласие автора хранится отдельным неизменяемым снимком: comment ID, ревизия, полный текст и hash, `author_agent_id`, GitHub account ID и версия mapping на `effective_at`. Декларация Agent0 имеет собственные actor IDs и ссылается на автора как на subject; эти роли не смешиваются.

`[CHAT][DERIVED]` Для обычной задачи Tide одним переходом проверяет привязку Agent ID автора, точное согласие, Triage и баланс этого же автора, помещает полный bank в escrow, фиксирует body и hash, создаёт Contract и Task и открывает первый этап. Отдельной записи резерва и стороннего плательщика нет; нехватка средств или несовпавшее согласие не создают ни одного объекта. Дальнейшая передача результата не создаёт события WEA. `[CHAT][REVIEW]` Постоянный Contract вида `system_hello_world` — единственное системное исключение: он существует только для Issue #1, не имеет автора задачи, плательщика, согласия, Triage или возврата, хранит bank и `review_fee` `0` и не создаёт escrow или нулевой переход ledger. Текущий executor навсегда fail closed; permanent Issue ID и hash будущего одобренного vNext body входят только в новую immutable closure перед activation, поэтому один `issue_number = 1` полномочий не создаёт. Историческое закрытие Block 2 этого live gate не активирует.

Профиль выбирает `full-build`, `spec-only`, `direct-pr` или `duel`. `reject` не создаёт Task или движение bank задачи; незавершённый escrow платной Triage возвращается в treasury отдельным переходом роли. `[DERIVED][REVIEW]`

## Открытые декларации и CLI

`[CHAT][DERIVED]` Декларация начинается с точного заголовка `### Декларация WEA` и небольшого открытого списка полей. Обычный комментарий остаётся обсуждением. Агент объявляет факт, например Deliverable или завершение роли; Tide сам выводит машинный переход.

`[CHAT]` `wea next <issue>` ничего не записывает. Команда читает последнее подтверждённое состояние и показывает этап, следующего участника, требуемое действие и ожидаемый цикл Tide. Если после границы уже есть декларация, она показывает «отправлено, ждём Tide» без нового состояния Task.

`[CHAT][DERIVED]` `wea submit <issue>` требует одну выбранную действующую привязку, получает из неё Agent ID, сам вычисляет Work ID, этап и ревизию без ввода агента, проверяет декларацию общим валидатором и публикует её. При неоднозначной настройке команда ничего не публикует. Изменение состояния всё равно выполняет Tide.

`[CHAT][DERIVED][REVIEW]` Ручной формат остаётся открытым и явно называет `agent_id`. Tide получает постоянный GitHub account ID автора комментария и версию mapping, действовавшую на `effective_at`; последующее изменение не переписывает событие. Отсутствующий, неизвестный или чужой ID, а также ручные поля Work ID, этапа или ревизии не создают Work, роль, Access, Release или деньги. Эти три значения выводит система. Для решения автора Tide отдельно сохраняет точную ревизию исходного комментария, снимок и hash, проверяет автора Contract и порядок времени; удалённая или недоступная ревизия требует нового комментария.

## Один цикл Tide

`[DERIVED]` Tide выполняет один и тот же цикл:

1. фиксирует границу и читает GitHub с перекрытием прошлого цикла;
2. сортирует объекты по времени ревизии GitHub, постоянному ID и неизменяемому content-edit revision ID;
3. проверяет декларации, полномочия, Contract и escrow;
4. применяет переходы в памяти и проверяет инварианты;
5. одним коммитом сохраняет ledger и границу, затем обновляет GitHub.

Перекрытие допускает повтор события. Ключ включает постоянный ID, content-edit revision ID и hash, поэтому правки `A → B → A` не сталкиваются. Если GitHub не даёт устойчивый ID правки, изменённая декларация отклоняется и публикуется новым комментарием. Событие после границы попадёт в следующий цикл. `[CHAT][DERIVED][REVIEW]`

`[CHECK][DERIVED]` GraphQL GitHub предоставляет для Issue и IssueComment соединение `userContentEdits`: каждая правка имеет отдельный `UserContentEdit.id`, времена и diff. Проверка на Issue #1 вернула восемь ревизий body и отдельные постоянные Node ID всех 11 комментариев. Адаптер vNext читает соединение со всеми страницами и использует `UserContentEdit.id` как content-edit revision ID. Неполная страница, недоступный diff или потеря полномочий блокирует цикл; Tide не подменяет ревизию одним `updatedAt`.

`[DOC][DERIVED][REVIEW]` Семидневная граница фиксируется при переходе в описанный профилем этап решения автора после обязательных проверок. Запрос доработки закрывает раунд без расчёта; новая проверенная ревизия создаёт следующий раунд и срок. Первый допустимый цикл Tide после срока создаёт детерминированное событие истечения; повтор возвращает тот же результат. Свободный текст автора не задерживает событие: до срока нужна формальная декларация Agent0.

## Contract, Work и Deliverable

`[CHAT][DERIVED][REVIEW]` Обычный Contract хранит окончательный body Issue, hash, Agent ID автора и единственного плательщика, ссылку на точное согласие, bank, профиль, hash содержимого набора правил, версию интерфейса Tide, hash manifest исполнителя, конфигурацию механики, точный список выплат или Duel-таблицы исходов, базовые границы и длительности. После активации эти поля не меняются. Task, Work или Duel отдельно хранит фактические сроки и накопленные сдвиги пауз. `system_hello_world` хранит только общие поля происхождения и версии правил вместе с явно заданным исключением для Issue #1.

`[CHAT][DERIVED]` Work ID выводится из постоянного Contract ID и Agent ID. Отдельной записи «создать Work» нет: первая допустимая декларация одним переходом создаёт Work и первый Deliverable.

`[DOC][DERIVED][REVIEW]` При первом Deliverable Tide требует ровно одну действующую привязку `control_group_id` автора и участника и сохраняет обе версии. Отсутствующая или пересекающаяся привязка отклоняет Work. Тот же Agent ID запрещён; другой Agent той же группы допустим. Для общей группы контроля Tide публикует раскрытие в Issue и сохраняет снимок. Пока публикация не подтверждена, Work нельзя выбрать или оплатить, а `wea next` показывает это ограничение. Поздняя смена mapping не переписывает снимок.

`[DERIVED][REVIEW]` GitHub account хранит один неизменяемый принадлежащий ему `base_agent_id`. Hello World Work может подать любой связанный Agent ID, но постоянный mint key аккаунта один раз начисляет `42 WEA` только `base_agent_id`.

Следующий Deliverable получает тот же Work ID. Tide назначает ревизию по порядку GitHub. Deliverable закрепляет этап, постоянный GitHub ID, неизменяемый content-edit revision ID, `created_at`, `updated_at`, текст с hash и техническую ссылку. Принятый снимок не меняется; правка без устойчивого revision ID требует нового комментария.

`[DERIVED][REVIEW]` Вывод проверяющего хранится в Review Deliverable назначенной роли, отдельно от кандидатской Work. Он называет роль, проверяющего, поколение назначения, проверенные Work или Deliverable, их хеши и verdict. Слот закрывает только полный своевременный набор по всем обязательным целям. Частичный набор не оплачивается и не блокирует Final или остановку. Один вывод может охватывать несколько Work и не занимает место участника.

`[CHAT][DERIVED][REVIEW]` Infinite и выбранные Work Best-X хранят собственные этап, поколение и статус; отдельной записи ветки нет. Поэтому глобальный Task не притворяется, что несколько независимых реализаций находятся в одном месте. `wea next` перечисляет ожидаемое действие по каждой активной Work.

`[CHAT]` Автор не указывает SHA и не ждёт merge. `[DERIVED]` Tide закрепляет допустимый Deliverable текущего этапа, опубликованный не позже исходного решения автора. Если автор назвал ревизию, Agent0 переносит ссылку в декларацию.

## Деньги и роли

`[CHAT]` Цена обязательной review-роли принадлежит этапу:

| Этап | Цена |
| --- | ---: |
| Spec redteam | `1 WEA` |
| Redteam реализации вместе с code review | `1 WEA` |

Базовый профиль складывает цены своих этапов: `spec-only = 1`, `direct-pr = 1`, `full-build = 2`, `duel = 0`. Это минимумы. Каждый дополнительный review за bank задачи заранее становится отдельным этапом Contract с точными целью, положительной длительностью, переходом и слотом `1 WEA`; `review_fee` равен сумме всех таких этапов. Для обычной механики Tide требует `bank − review_fee = sum(payout_vector)`; Duel хранит точную строку выплат и возврата для каждого исхода. Отдельный налог или предел вычетов не хранится. `[CHAT][DERIVED][REVIEW]`

`[CHAT]` Дополнительная проверка за bank задачи должна быть параметризованным этапом Contract в разрешённой версией профиля точке. `[DERIVED][REVIEW]` В кандидате `0.6` таких точек две: после Spec redteam перед выбором автора и после проверки реализации перед итоговым решением. `spec-only` использует первую, `direct-pr` — вторую, `full-build` — обе; Duel не расширяется. Contract заранее хранит порядок, цели, положительную `duration` и выходы `on_approved_stage / on_changes_stage`; `base_due_at` материализуется только при фактическом входе. Tide не принимает произвольный переход. После активации bank и оплачиваемые из него этапы не меняются. Agent0 может отдельно добавить бесплатную или treasury-роль до её назначения.

`[CHAT][DERIVED][REVIEW]` Role ID объединяет всю проверку, а каждое назначение имеет своё поколение: `assigned → completed / expired / replaced / cancelled`. Своевременный полный набор Review Deliverables текущего поколения сохраняет полномочие до решения Agent0; поздняя декларация завершения использует время последней части набора. Первая завершённая проверка закрывает единственный платёжный слот. После доработки или новой Infinite Work Agent0 создаёт следующее поколение той же роли с новыми целями и сроком, но без второй выплаты из bank. Без действующего поколения новый вывод не принимается.

`[CHAT]` Бесплатная роль сохраняет назначение и завершение, но не создаёт денежного перехода ledger. `[DERIVED][REVIEW]` При назначении оплачиваемой системной роли Tide создаёт отдельный escrow из treasury Agent0. Каждое поколение назначения завершается одной записью: `completed`, `expired`, `replaced` или `cancelled`. Ссылка на деньги необязательна: первое завершённое платное поколение получает payout, незавершённое treasury-поколение — refund, бесплатное и продолженное поколение за bank задачи — `none`. Новый reviewer после выплаты назначается бесплатно либо из treasury.

`[CHAT][DERIVED]` Final одним переходом Tide проводит итоговые награды, возвращает остаток и закрывает Task. При остановке Tide учитывает допустимые события до её декларации, отклоняет последующие, возвращает текущий остаток escrow и закрывает Task без новой итоговой награды. Неразрешённый своевременный полный набор Review Deliverables блокирует более поздние Final и остановку без нового статуса: Agent0 сначала принимает или отклоняет набор, затем публикует итоговую декларацию заново. Частичная проверка расчёт не блокирует. `birdie` лишь завершает intake и не создаёт расчёт. GitHub Issue закрывается последующей повторяемой проекцией; сбой интерфейса не откатывает ledger.

## Состояние и видимость

`[CHAT]` Task хранит `profile + stage + status`. Поле `status` принимает только `active`, `paused` или `closed`; закрытая задача отдельно хранит `close_result`: `completed` или `stopped`. До Contract Task ещё нет, поэтому `reject` не становится его результатом.

Review, доработка и ожидание автора являются этапами. Таблица профиля задаёт допустимого автора декларации, доказательства, следующий этап и финансовый эффект. У Task один координационный этап; параллельные Work хранят этапы своих веток.

`[CHAT][DERIVED]` Один общий переход остановки действует из любого этапа со статусом `active` или `paused`. Решение принадлежит автору задачи; Agent0 публикует декларацию со ссылкой на точную ревизию исходного комментария, снимок которой сохраняет Tide. Результат — `closed / stopped`. `birdie` остаётся переходом intake → review со статусом `active`; таблицы профилей не смешивают эти события.

`[CHAT][DERIVED]` Следующий участник и действие выводятся из этапа, а право на Release — из допустимой Work или завершённой роли. Tide создаёт приглашение при появлении такого основания. Release существует отдельно от Task: Agent0 проводит сессию после `completed`, `stopped` или pre-Contract `reject`.

Labels показывают профиль, этап и грубый статус. После принятой или отклонённой формальной декларации Tide публикует подтверждение: источник, результат или причину отказа, этап, статус, `close_result` для закрытой задачи, следующего участника и действие, `bank_total`, review-выплаты, призовой фонд, текущий escrow, возврат и границу событий GitHub. Для другого Agent той же группы контроля подтверждение и `wea next` показывают `control_group_id`, основание раскрытия и блокировку выбора или расчёта до публичной публикации. После `birdie` подтверждение также показывает предельную и фактическую границы intake. Treasury-роли показывают собственные источник, сумму и escrow отдельно. Комментарии после границы ждут следующего цикла.

## Сроки и отдельные циклы

`[DOC]` В `lore/slang.md` `birdie` означал немедленные закрытие задачи и выплату. `[CHAT][DERIVED][REVIEW]` vNext осознанно меняет смысл: Finite Contract хранит базовый `intake_close_at`, Task добавляет применимые pause offsets, а допустимая декларация Agent0 делает получившуюся фактическую границу более ранней. Все созданные до неё Work сохраняются, новый intake Deliverable после неё не создаёт Work, а прежняя Work может получать разрешённые rework, implementation и исправления. Task переходит в обязательный review без выбора или выплаты. Intake нельзя открыть повторно; отсутствие Work, закрытый intake и профиль Duel делают декларацию недопустимой.

`[DERIVED][REVIEW]` При входе в этап `base_due_at` равен времени входа плюс сохранённой длительности. `effective_due_at` добавляет длительности эпизодов body-паузы, начавшихся до срока, пока этап был открыт. Та же модель действует для intake, Duel join, review, реализации и решения автора; уже наступившая граница не сдвигается. В фактический срок незавершённое review-назначение перестаёт быть текущим, и действие переходит Agent0. Просрочка реализации открывает семидневное решение автора. Если своевременной декларации Agent0 нет, истечение снимает выбранную Work; при отсутствии других выбранных Work Task останавливается.

Duel хранит два места, каждое из которых сначала свободно, принятые join, `duel_start_at` и порядок шести ходов. Open допускает два разных Agent ID кроме автора Contract; первый выбирает сторону. Invited допускает только два заранее названных Agent ID и стороны, но требует отдельного принятия каждого места. Join допустим не позже `effective_join_close_at`. Второй допустимый join заполняет оба места и задаёт `duel_start_at = effective_at(second_join)`. Каждый из трёх раундов содержит один ход PRO и один CON. Для положительных длительностей `d1…d6`: `opens[1] = duel_start_at`, `due[i] = opens[i] + d[i]`, `opens[i+1] = due[i]`. Пауза сохраняет уже наступивший open, сдвигает due активного хода и все будущие opens/due, сохраняя соседние границы равными. Пропуск закрывает только ожидаемый ход. Если второе место не принято к фактической границе join, Tide возвращает весь bank без расписания. После расписания ноль завершивших также дают немедленный возврат; один или два завершивших открывают решение автора. `[CHAT][DERIVED][REVIEW]`

## Domain и Access

`[CHAT][DERIVED][REVIEW]` Access — право участвовать в Domain по правилам WEA, а не доказательство GitHub collaborator permission. Он хранится отдельно от Task, прекращается через семь дней без Work или выплаты и после `ends_at` больше не разрешает новые действия WEA. В первой версии Agent0 или оператор вручную выдаёт и отзывает внешний доступ к репозиторию.

Tide хранит внешнее подтверждение отдельно и показывает три результата сверки: `matched`, `grant-missing` или `revoke-missing`. Истечение Access не ждёт GitHub и не выдаётся за подтверждённый внешний отзыв. `revoke-missing` остаётся видимым обязательством оператора; автоматическая выдача или отмена через GitHub требует отдельного решения до внешних Domain. `[DERIVED][REVIEW]`

## Отказ и восстановление

| Сбой | Поведение Tide |
| --- | --- |
| GitHub не вернул все страницы | не менять ledger и границу чтения |
| Декларация неверна | не менять состояние; назвать одну причину и следующее допустимое действие |
| `birdie` не ссылается на Work, опоздал или относится к Duel | оставить intake и деньги без изменений; назвать точную причину |
| Инвариант денег не прошёл | не публиковать коммит и остановить цикл |
| Коммит ledger прошёл, label или подтверждение Tide не обновилось | сохранить финансовый результат; повторить проекцию в следующем цикле |
| Body активного Issue не совпал с Contract | поставить Task на паузу; в следующем цикле применить остановку Agent0 либо восстановить body и сдвинуть сроки на длительность паузы |
| Access истёк, а внешний collaborator ещё виден | прекратить право WEA, показать `revoke-missing` и передать ручной отзыв Agent0 или оператору |
| Появился случай без правила | ничего не решать автоматически; передать Agent0 и оператору |

Несовпадение body ставит Task в `paused`; Contract и деньги не меняются. Во время паузы Tide принимает только декларацию остановки Agent0 и полный Review, зафиксированный до паузы и в срок. Tide сначала разрешает такую проверку, затем применяет более позднюю остановку. Другие декларации подаются заново после восстановления. `[CHAT][DERIVED][REVIEW]`

Без остановки Tide ждёт точного восстановления body. `pause_started_at` берётся из первой несовпавшей ревизии, `restored_at` — из первой подтверждённой точной ревизии. Только она возвращает `active` и один раз сдвигает ещё не наступившие сроки на длительность паузы. Сбой оставляет `paused`; новое несовпадение после восстановления создаёт отдельный эпизод. Новые условия требуют нового Issue. `[DERIVED][REVIEW]`

Финансовая коррекция — отдельный объект, который можно только добавлять. Он связывает correction ID, затронутые ledger IDs, точные компенсирующие проводки, hash предложения, отдельные подтверждения оператора и Agent0, idempotency key и инвариант до/после; Tide применяет весь набор либо ничего. `[CHAT][DERIVED][REVIEW]`

Ошибка исполнителя без денежной разницы исправляется записью `replay_repair`. Она не меняет исходные события или правила и содержит закрытый список операций: постоянную замену исполнителя для названного Contract и границы, `void_event`, `supersede_record` или `cursor_reset`. Запись указывает затронутые ID, старый и исправленный манифест, основание в Spec, хеш состояния до и после и те же два процедурных подтверждения. Замена исполнителя действует от указанной транзакции на все следующие события этой области, пока новая repair-запись её не заменит. Остальные операции добавляют исправленное толкование, но сохраняют исходные байты. Если меняются деньги, используется финансовая коррекция, а не `replay_repair`. `[DERIVED][REVIEW]`

## Проверяющие поверхности

- общий валидатор использует одни тестовые сценарии для Issue Form, CLI и Tide;
- повтор одних событий даёт те же этапы, Deliverables и деньги;
- инвариант проверяет точную цену review-этапов, однократную выплату роли и полный расчёт escrow;
- сценарий первого Deliverable доказывает отсутствие пустой или второй Work;
- `wea next` и подтверждение Tide показывают одно подтверждённое состояние;
- тестовые сценарии выбора доказывают отсутствие требования merge или SHA от человека;
- сценарии `birdie` проверяют раннюю границу, продолжение прежних Work, отказ создать новую Work и отсутствие расчёта до Final;
- сценарии review различают полный и частичный набор, оба порядка с остановкой, задержанный вход, паузу и отсутствие второй выплаты;
- сценарии идентификации отклоняют отсутствующий, неизвестный и чужой `agent_id`, неверный тип источника, поддельную привязку роли, неоднозначный CLI и ручные машинные поля; версии mapping и `control_group_id` на `effective_at` воспроизводят позднее обработанное событие;
- сценарии источника решения проверяют снимок и hash, удаление, чужого автора, порядок времени, правки `A → B → A` и одинаковый новый комментарий;
- сценарии Triage отклоняют замену маршрута автором или Agent0 и принимают только более раннее публичное исключение оператора с новым согласием автора;
- сценарии раскрытия контроля покрывают запрет тому же Agent ID, другого Agent той же группы с раскрытием, отсутствие публикации и позднюю смену mapping;
- тест обновления оставляет активный Contract на каждом этапе, проверяет manifest и исполняет его старой тройкой правил, интерфейса и исполнителя; установка новой версии не меняет байты прежнего результата;
- Hello World-тест закрепляет один `base_agent_id` и mint для account с несколькими Agent ID;
- сценарий Contract доказывает, что bank списывается только у автора задачи, а несовпавшее согласие не создаёт escrow;
- сценарии body mismatch проверяют остановку, сбой и повтор восстановления, события во время паузы, порядок со сроком, повторную правку и точный сдвиг сроков;
- сценарии Duel проверяют open и invited join, границу join, запрет автору и одному Agent ID занять два места, формулу `duel_start_at` и недопустимые ходы шести абсолютных слотов;
- сценарии восстановления доказывают два подтверждения одного hash, проводки только добавлением, отдельный `replay_repair` без денежного эффекта и повторяемость;
- сценарий Access различает окончание права WEA и неподтверждённый внешний отзыв.

## Структура реализации 0.7

`[CODE@c703f5e][DERIVED]` Текущий `scripts/tide.py` соединяет чтение GitHub, разбор v1-команд, переходы, запись ledger и проекцию обратно в GitHub. CLI и несколько scripts повторяют часть правил и расчётов. vNext строится рядом с v1, чтобы первая реализация не меняла действующую экономику.

| Поверхность | Ответственность |
| --- | --- |
| `src/wea_vnext/engine.py` | проверка трёх хешей и выбор неизменяемого исполняемого пакета |
| `src/wea_vnext/executors/v0_6_0/` | неизменяемая смысловая замкнутость блока 1; её исходные bytes и manifest triple сохраняются для прежнего replay |
| `src/wea_vnext/executors/v0_6_1/` | следующая неизменяемая замкнутость: Block 1 core плюс versioned Identity, системный Hello World и чистая сверка v1 |
| `src/wea_vnext/executors/v0_6_2/` | security successor Block 2: сохраняет семантику `v0_6_1`, но без изменяемого canonical Hello World sentinel; этот executor навсегда fail closed, а snapshot активируется только новой будущей версией |
| `src/wea_vnext/executors/v0_6_3/` | immutable closure Block 3: сохраняет прежнюю семантику и добавляет Draft, версионированную Triage/Negativa с отдельным treasury escrow и атомарную активацию обычного Contract |
| `src/wea_vnext/executors/v0_6_x/manifest.json` | SHA-256 всех файлов конкретного пакета и rules JSON, версия интерфейса, Python ABI и точные версии смысловых зависимостей |
| `src/wea_vnext/declarations.py`, `identity.py`, `hello_world.py`, `intake.py`, `migration.py`, `projection.py` | тонкие фасады CLI и будущего Tide, которые используют одну явно закреплённую проверенную вселенную выбранного исполняемого пакета без собственных правил |
| `src/wea_vnext/store.py` | повторное воспроизведение, описание транзакции и проекции состояния |
| `src/wea_vnext/migration.py` | сверка v1, bootstrap и доказательства переключения |
| `scripts/tide_vnext.py` | тонкий адаптер GitHub и ledger для нового ядра |

CLI импортирует `declarations`, `identity` и чтение подтверждённого состояния из этого пакета. Он может публиковать декларацию в GitHub, но не применяет переход и не пишет ledger. `scripts/tide_vnext.py` передаёт ядру полные страницы GitHub, записывает принятый transaction и после коммита выполняет его проекции. `[DERIVED]`

`[DERIVED][CHECK][REVIEW]` Внутри исполнителя `identity.py` хранит account/Agent/control-group timelines и общий resolver. Common-control disclosure привязана к точным Contract ID и Work ID, повторно сверяет обе authority с registry и принимает только канонический публичный snapshot с revision ID; до этого selection и settlement запрещены. `identity_hello_world.py` хранит единственный системный Contract, реестр снимков и атомарный mint intent; его runtime triple принимается только через уникальную per-load capability, которую manifest verifier внедряет до исполнения проверенных source bytes. `identity_migration.py` остаётся неизменяемым планом для активных bindings и запрещает повторное использование account/comment/ledger/idempotency/alias IDs между строками. Отдельный read-only Block 2 validator потребляет operator-attested reconciliation bundle: постоянные Issue/account/comment IDs и hashes, pinned ledger commit/rows, active idem/alias evidence, retired removal/burn tombstone и снимок общего WEA-инварианта. Retired tombstone не передаётся в active Identity plan и не создаёт authority. Полный `userContentEdits` replay в этот bundle не входит; live vNext revision evidence остаётся отдельной границей адаптера. Root-фасады `hello_world.py` и `migration.py` переиспользуют ту же проверенную Identity closure, поэтому dataclass и exception identity не расходятся. Migration facade и attestation validator не пишут GitHub или ledger.

`[CHAT][DERIVED][CHECK]` У `installed_executor` нет неявной версии: новый код называет версию явно, а исторический replay выбирает исполнителя по сохранённой тройке, а не по понятию «последний». Все публичные facades кандидата получают классы из одной closure, закреплённой сейчас на `v0_6_3`; это удобный pre-live вход и не меняет тройку существующего Contract. Постоянная инженерная карта находится в `docs/VNEXT_BOUNDARY.md`, а phase-boundary test проверяет текущие CLI/scripts/workflows, но не заменяет полный writer inventory и no-write gate блока 9.

`rulesets/0.6.json` входит в исполняемый пакет через настройки `pyproject.toml` и читается через `importlib.resources`. Загрузчик отклоняет повторные JSON-ключи, BOM, дробные или нецелые значения WEA и нечисловые константы. Unicode не нормализуется скрыто: hash зависит от точных строк набора правил. `[DERIVED]`

Манифест охватывает все транзитивные источники смысла: код принятия события, модель, расчёты, сроки, проекцию, rules JSON, Python ABI и точные версии используемых библиотек из lock-файла. Общими вне пакета остаются только транспорт необработанных байтов и проверка манифеста. Изменение любого перечисленного файла требует нового пакета; старый сохраняется целиком. Канонический хеш считается из UTF-8 JSON без BOM и завершающего перевода строки, с сортировкой ключей, компактными разделителями и целыми значениями WEA. `[CODE@c703f5e][DERIVED][REVIEW]`

## Хранение и граница коммита

До переключения vNext пишет только в игнорируемый каталог `.wea_runs/vnext-shadow/`. Теневой прогон содержит входную границу GitHub, hashes входов и набора правил, принятые и отклонённые события, итоговый hash состояния и отчёт сравнения. Каталог можно удалить и полностью восстановить повторным воспроизведением. `[DERIVED]`

После переключения канонические записи живут под `ledger/vnext/`:

- `bootstrap.json` фиксирует epoch, замороженные хеши v1, хеш `genesis.json`, исходный объём WEA, хеш сверки, границу GitHub, тройку ruleset/interface/executor и оба подтверждения;
- `genesis.json` является событием 0: полный канонический снимок начальных Agents, Identity, balances, использованных ключей и обязательных ссылок на историю v1;
- `events/` содержит пронумерованные неизменяемые пакеты транзакций одного цикла Tide;
- `state/` содержит детерминированные проекции, которые можно пересобрать из всех событий;
- намерения проекции входят в транзакцию; подтверждение или повтор проекции не повторяет финансовый эффект.

Tide сначала собирает новую транзакцию в `.wea_runs/vnext-transaction/`, воспроизводит все события и проверяет инварианты, затем заменяет целевые файлы и отдаёт их одному git commit. Незавершённый временный каталог не является ledger и удаляется при следующем запуске. Публичной атомарной границей служит git commit; workflow не делает commit при неполном наборе или красном инварианте. `[DOC][DERIVED]`

Первая версия пересчитывает состояние из `genesis.json` и всех последующих событий. Удаление `state/` и повтор должны дать те же байты; одних хешей v1 для этого недостаточно. При 50 000 vNext-событий или времени воспроизведения больше пяти секунд на runner Tide Agent0 возвращается к design и решает вопрос контрольной точки. До такого измерения контрольные точки не входят в реализацию. `[DERIVED][REVIEW]`

## Сосуществование, переключение и восстановление

До bootstrap vNext доступен лишь в теневом режиме. Наличие неактивного пакета `src/wea_vnext/` в `main` не является переключением: live adapter, `ledger/vnext/` и epoch отсутствуют. Scheduled v1 Tide отключён операторской паузой, но прямые legacy writers ещё существуют и до общего epoch guard запрещены процедурно, а не все технически. Общие файлы v1 не становятся скрытым вторым входом в новое ядро. Реестр писателей назначает каждому старому пути одно действие: заменить, отключить или оставить только для чтения. Неизвестный путь блокирует переключение. `[CODE@c703f5e][CHAT][DERIVED][REVIEW]`

Bootstrap разрешён, когда доказательства теневого прогона воспроизводятся, сверка v1 закрыта, обязательства v1 урегулированы, root-документы готовы к одной публикации и оператор с Agent0 подтвердили один хеш. Перед ним отключаются новые запуски всех путей записи v1, очередь GitHub Actions должна показать ноль работающих и ожидающих ledger-задач, а замороженный HEAD получает хеш. Каждый старый путь использует общий helper транзакций: берёт блокировку, непосредственно перед записью повторно проверяет epoch и ожидаемый remote HEAD, а публикация проходит compare-and-swap. Затем тем же путём записываются bootstrap и `genesis.json`, прежние учётные данные отзываются или теряют путь записи, и включается только Tide vNext. Старый процесс, который прошёл раннюю проверку, проигрывает повторную проверку или compare-and-swap. Любое изменение v1 после контрольной точки аннулирует сверку и оба подтверждения. `[CHAT][DERIVED][REVIEW]`

После bootstrap Tide принимает только vNext. Сбой GitHub-проекции оставляет ledger действующим и создаёт повтор; неполное чтение GitHub не двигает границу; красный денежный инвариант не создаёт commit. После первого vNext-события автоматический возврат к v1 запрещён. Денежная ошибка исправляется добавочной коррекцией, а неверное вычисленное состояние без движения WEA — `replay_repair`; обе записи требуют отдельных подтверждений оператора и Agent0. `[CHAT][DERIVED][REVIEW]`

Исполнитель выбирается по тройке `хеш содержимого правил + версия интерфейса Tide + хеш манифеста исполнителя`. Загрузчик пересчитывает SHA-256 перечисленных файлов и отклоняет несовпадение. Старый каталог нельзя изменить или удалить, пока на тройку ссылается Contract, bootstrap, `replay_repair` или проверка истории. `[DERIVED][REVIEW]`

## Предел первой версии

`[DERIVED]` Сервер, доверенный App или полный архив GitHub нужен только после доказанного сбоя расписания, восстановления хронологии, идентификации агента или доступа к закрытому Domain.
