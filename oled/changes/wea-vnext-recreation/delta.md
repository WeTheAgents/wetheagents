# Текущая WEA → vNext

Статус: `delta 1.0` является текущей реализационной delta для Outcome/Spec `1.0`, design `1.1` и schema `1.1`. Delta `0.9`, ruleset `0.8` и executor `v0_8_0` остаются неизменным историческим результатом. `[CHAT][DERIVED]`

## Delta 1.0: external Domain and internal Access

| Decision | Current behavior | Implementation consequence |
| --- | --- | --- |
| ADD | Circle-1 is a real external public Domain | extract portable canon/scanners/tests to `WeTheAgents/circle-1`; retain WEA adapters, profiles, checkpoints, task-index, and ledger operations in WEA |
| ADD | immutable versioned Domain registry | validate canonical record and registry hashes in `src/wea_vnext/domain_access.py`; publish `domains/registry/v1.json` only from a verified public repository ID and commit |
| ADD | internal seven-day Access | add immutable grant, expiry, idempotency, and state values with global per-Agent overlap prevention |
| REJECT | GitHub permission as Access state or effect | expose no permission field, grant, revoke, check, or reconciliation operation |
| REJECT | early revoke, renewal, extension, suspension, or transfer | active interval is exactly `[starts_at, starts_at + 7 days)` |
| KEEP | 67-scenario Spec `0.9` runtime | do not edit ruleset `0.8`, executor `v0_8_0`, manifests, or runtime facades |
| DEFER | S-13C financial correction | start a separate OLED change and PR after Domain/Access merges |

### Executable surface

| Component | Action | Boundary |
| --- | --- | --- |
| external `WeTheAgents/circle-1` | ADD | public Domain owns portable Circle-1 history, package, docs, and tests |
| `src/wea_vnext/domain_access.py` | ADD | inactive offline control-plane library outside executor closures |
| `domains/registry/v1.json` | ADD | canonical immutable binding to repository ID `R_kgDOT4-F-Q` and public revision `36a71440840351aa462e61a8ad5955881f55ecb0` |
| `tests/vnext/test_domain_registry.py`, `test_access.py` | ADD | exact S-11A/S-11B evidence and negative-boundary evidence |
| `tests/vnext/scenarios.py` | MODIFY AFTER EXTERNAL GATE | promote only S-11A/S-11B; retain S-13C accepted-future |
| ledger, live Tide, CLI writers, GitHub permissions | NO CHANGE | no production write or activation |

The external Circle-1 revision and the focused control-plane code are verified.
The live manifest pins the exact public identity. S-11A and S-11B are current
control-plane scenarios; S-13C remains accepted-future.

## Historical delta 0.9: full Plan execution

| Decision | Current behavior | Implementation consequence |
| --- | --- | --- |
| KEEP | author-approved complete Plan bank, one program escrow, exact depth × mode matrix, no profiles or Infinite | preserve `v0_7_0`; copy into successor closure |
| ADD | approved per-stage durations and materialized absolute deadlines | add schedule schema and deadline projection |
| ADD | child-scoped Work and exact immutable cross-stage revision inputs | add lifecycle Work/revision records and selector reducer |
| ADD | atomic Flat PoD, Ranked, Frontier, and Duel settlement | add mode reducers and financial event groups |
| ADD | body, risk, and progression pauses with author-only continue/replan/stop | body pause/resume use exact latest Issue revisions. Risk warnings use an exact active Triage/review generation. Risk pause keeps submissions open but blocks stage decisions and settlement |
| ADD | frozen assigned-role targets, generations, timing, and `free/treasury` funding | add role lifecycle without hidden Plan fees |
| MODIFY | Release follows valid Implement/role outcomes; Triage Release waits for successful whole Plan | add terminal gate and negative Triage feedback |
| ADD | pure read-only `next_action` projection | expose through pre-live Resolution Plan facade |
| HISTORICAL | ruleset `0.7`, executor `v0_7_0`, and their activation-only behavior | verify hashes; never patch old bytes |

### Executable surface

| Component | Action | Boundary |
| --- | --- | --- |
| `rulesets/0.8.json`, `executors/v0_8_0/` | ADD | full immutable inactive closure with no semantic dependencies |
| `resolution_plan.py` | MODIFY | explicit facade pinned to `0.8.0` and lifecycle API |
| `tests/vnext/scenarios.py` | MODIFY | 67 current IDs plus three accepted-future IDs and a separate historical scope |
| `test_current_bdd_*.py` | ADD | exact evidence for 26 changed/added scenarios |
| old rulesets/executors and `intake.py` | KEEP | historical replay surface |
| live Tide, GitHub writer, ledger files, CLI command, bootstrap | NO CHANGE | unauthorized until a separate live adapter/migration gate |

## Delta 0.8: Resolution Plan

| Решение | Что происходит | Источник |
| --- | --- | --- |
| DELETE | `direct-pr`, `spec-only`, `full-build`, task-profile `duel` и Infinite как входные типы нового Contract | `[CHAT]` |
| MODIFY | Автор публикует problem и максимальный общий bank; обязательная Triage/Negativa предлагает ordered Resolution Plan, а автор утверждает точную ревизию, изменяет её, просит новый вариант либо отказывается | `[CHAT]` |
| MODIFY | Один author approval и один debit обеспечивают весь Plan; program escrow хранит полный bank, а Tide материализует только первый child Contract/Task | `[CHAT][DERIVED]` |
| MODIFY | Новый Contract задаётся строкой матрицы `depth × mode`: Explore допускает Ranked/Flat PoD/Frontier/Duel, Spec и Implement — Ranked/Frontier | `[CHAT]` |
| MODIFY | Ranked объединяет WTA (`K=1`) и X-Best (`K>1`); Flat PoD остаётся additive; Frontier использует конечный Linear/Fibonacci vector; Duel имеет две защищаемые позиции Explore | `[CHAT]` |
| MODIFY | Triage может рекомендовать отказ, но не имеет semantic veto в ruleset 0.7; hard reject ограничен формальными authority, declaration, identity, matrix, money и evidence-boundary ошибками | `[CHAT]` |
| MODIFY | Future stages хранят symbolic `selected_work_of` только для более раннего Ranked/Frontier/Duel; Flat PoD source отклоняется до approval; следующий Contract появляется автоматически после однозначного accepted Work, иначе Plan ставится на паузу | `[CHAT][DERIVED][REVIEW]` |
| MODIFY | Replan stores the next full Triage Plan revision and a later author approval of its exact ID and hash. It changes only unstarted templates. Future Contracts bind to that revision. | `[CHAT][DERIVED][REVIEW]` |
| MODIFY | Release зависит от завершённой Implement Work, а не от старого имени profile | `[CHAT]` |
| HISTORICAL | Ruleset `0.6`, executors `v0_6_0…v0_6_3` и их profile semantics сохраняются byte-for-byte только для replay | `[CHECK]` |

### Исполняемая поверхность Block 4

| Компонент | Действие | Граница |
| --- | --- | --- |
| `rulesets/0.7.json`, `executors/v0_7_0/` | ADD | immutable inactive closure; полный manifest, без semantic dependencies |
| `resolution_plan.py` | ADD | явный facade, закреплённый на executor `0.7.0` |
| старый `intake.py` facade | KEEP | остаётся закреплённым на `0.6.3` |
| live Tide, CLI, Issue/ledger writers | NO CHANGE | не входят в Block 4 и не получают authority на запись |
| Stage execution, settlement, Frontier verdict, selector progression, replan | DEFER | приняты S-60…S-68, но не реализуются текущим vertical slice |

## Historical delta 0.7 baseline

## Правила

| Решение | Что происходит | Источник |
| --- | --- | --- |
| KEEP | GitHub как интерфейс; escrow-first, idempotency и денежный инвариант | `[CHAT][DOC][CODE@c703f5e]` |
| KEEP | WEA как покупательная способность; отдельные балансы и геномы Agents | `[CHAT][DOC]` |
| KEEP | создатель задачи не подаёт Work; Tide требует ровно одну привязку `control_group_id`, а для другого Agent той же группы сохраняет публичное раскрытие, без которого выбор и расчёт заблокированы | `[DOC][CODE@c703f5e][DERIVED][REVIEW]` |
| KEEP | маршрут Triage обязателен; только оператор может заменить его до согласия автора с публичным обоснованием и неизменяемым снимком | `[DOC][DERIVED][REVIEW]` |
| MODIFY | документация становится главным реестром правил и `KEEP / MODIFY / DELETE / HISTORICAL` | `[CHAT]` |
| MODIFY | Agent0 ведёт развитие и обучение; Tide наблюдает GitHub и один пишет штатный ledger | `[CHAT]` |
| MODIFY | до Contract нет escrow задачи; Tide фиксирует Contract и помещает полный bank в escrow одним переходом | `[CHAT]` |
| MODIFY | Triage/Negativa бесплатен либо заранее оплачен Agent0 из treasury; источник оплаты не меняет обязательность маршрута | `[CHAT]` |
| MODIFY | Task хранит профиль, этап и статус `active / paused / closed`; результат закрытия хранится отдельно | `[CHAT]` |
| MODIFY | первый Deliverable создаёт детерминированную Work; дальнейшие Deliverables получают ту же Work и новые ревизии | `[CHAT]` |
| MODIFY | вывод reviewer хранится как Review Deliverable назначенной роли и не создаёт кандидатскую Work | `[DERIVED][REVIEW]` |
| MODIFY | `wea next` объясняет состояние без записи; `wea submit` подставляет Agent ID и вычисляет Work ID и ревизию; ручная декларация содержит `agent_id`, который Tide сверяет с GitHub account автора | `[CHAT][DERIVED][REVIEW]` |
| MODIFY | автор задачи всегда финансирует её полный bank и получает возврат; стороннего плательщика и учёта дальнейшей передачи результата в WEA нет | `[CHAT]` |
| MODIFY | Progressive и Linear работают как Infinite; PoD, WTA, Best-X и Duel как Finite; семидневные границы получают постоянные ключи | `[CHAT][DERIVED][REVIEW]` |
| MODIFY | `spec-only` и `direct-pr` допускают все обычные механики; активный Contract сохраняет выбранную матрицу и точный payout vector | `[CHAT][DERIVED][REVIEW]` |
| MODIFY | Contract хранит hash содержимого канонических правил, версию интерфейса Tide и hash manifest неизменяемого исполнителя; вся тройка сохраняется, пока на неё есть ссылка | `[DERIVED][REVIEW]` |
| MODIFY | `full-build` использует WTA или Best-X; автор победившей Spec сам продолжает реализацию | `[CHAT]` |
| MODIFY | Infinite и несколько выбранных Work Best-X хранят этап ветки; новых видов статуса не появляется | `[DERIVED][REVIEW]` |
| MODIFY | каждый review-этап имеет один платёжный слот `1 WEA`; базовые минимумы равны `1 / 1 / 2 / 0`, а дополнительная проверка из bank задачи заранее становится отдельным этапом Contract | `[CHAT][DERIVED][REVIEW]` |
| MODIFY | роль проходит только назначение и завершение; бесплатная роль не двигает деньги, treasury-роль получает отдельный escrow при назначении | `[CHAT][DERIVED][REVIEW]` |
| MODIFY | право на Release выводится из допустимой Work или завершённой роли; хранится приглашение и участие | `[CHAT]` |
| MODIFY | остановка сначала разрешает полный своевременный review, затем сохраняет выплаты, возвращает остаток и атомарно закрывает Task; частичный review расчёт не блокирует | `[CHAT][DERIVED][REVIEW]` |
| MODIFY | источник декларации имеет тип `agent / agent0 / operator`, версионированную привязку и закрытый список полномочий; Agent0 и оператор явно получают Domain, Access, bootstrap и correction-события, Tide не является источником команды | `[DERIVED][REVIEW]` |
| MODIFY | автор выбирает Work прозой; Agent0 нормализует выбор, Tide сам закрепляет техническую ревизию без merge/SHA от автора | `[CHAT][DERIVED]` |
| MODIFY | open Duel даёт выбор стороны; полный Duel платит 90/10 или 50/50; один завершивший три раунда может получить 90%, иначе незавершение возвращает escrow; Duel Work не даёт Release | `[CHAT]` |
| HISTORICAL | `lore/slang.md` определяет `birdie` как немедленные закрытие задачи и выплату | `[DOC]` |
| MODIFY | vNext меняет `birdie`: декларация Agent0 раньше закрывает intake, но обязательные review и Final остаются | `[CHAT][DERIVED][REVIEW]` |
| MODIFY | Duel хранит два места, шесть ходов и bank не меньше `10 WEA`, кратный `10 WEA` | `[CHAT][DERIVED][REVIEW]` |
| MODIFY | два разных участника Duel кроме автора принимают места; второй допустимый join запускает шесть абсолютных слотов ходов | `[CHAT][DERIVED][REVIEW]` |
| MODIFY | каждый эпизод расхождения body ставит Task на паузу до остановки или подтверждённого восстановления Contract; повтор эпизода не сдвигает сроки дважды | `[CHAT][DERIVED][REVIEW]` |
| MODIFY | Best-X возвращает неназначенные места автору задачи и после `birdie`; правило v1 о передаче незаполненных долей первому месту заменено | `[CODE@c703f5e][CHAT][DERIVED]` |
| MODIFY | Tour становится Access; новые Domain живут снаружи root; текущие Agents связываются с `peachgabba22` | `[CHAT]` |
| MODIFY | Hello World даёт `42 WEA` один раз неизменяемому `base_agent_id` GitHub account через системный Contract и постоянный ключ; Access длится семь дней и допускает один активный доступ | `[DOC][DERIVED][REVIEW]` |
| MODIFY | существующий Issue #1 переписывается под vNext; реестр хранит полный снимок, версию нормализации и comparison hash | `[CHAT][CHECK][DERIVED]` |
| MODIFY | Access — семидневное право WEA; внешний GitHub grant/revoke в первой версии выполняется вручную и сверяется отдельно, поэтому истечение не выдаётся за подтверждённый отзыв collaborator | `[CHAT][DERIVED][REVIEW]` |
| MODIFY | денежная ошибка исправляется добавочной коррекцией, а неверное вычисленное состояние без движения WEA — добавочной записью `replay_repair`; исходные события не переписываются | `[DERIVED][REVIEW]` |
| DELETE | общий claim/autoclaim/TTL, содержательная апелляция и доверенная проверка Work | `[CHAT]` |
| DELETE | `/wea`, команды Tide, SHA/merge от автора, отдельное создание Work, ввод Work ID или ревизии, автоматическая оплата trainees | `[CHAT][DERIVED]` |
| DELETE | предварительный reserve, `review_tax_cap`, нулевые денежные переходы и изменение bank задачи после Contract | `[CHAT][DERIVED]` |
| HISTORICAL | ledger, события и документы v1 сохраняются как прежняя эпоха | `[DOC][DERIVED]` |

## Исполняемые компоненты

| Компонент | Действие vNext | Причина |
| --- | --- | --- |
| Issue Form, CLI, `tide_parser.py` | REWRITE | общая схема деклараций, `wea next` и `wea submit` |
| `scripts/tide.py`, Tide workflow | REWRITE | статические переходы, подтверждение Tide, escrow, ledger и проекция GitHub |
| параллельные механизмы записи денег | DELETE FROM VNEXT | один штатный путь записи ledger |
| CLI `claim` | DELETE | claim остаётся только в Duel join |
| `src/wea_cli/gh.py`, `tide_ops.py` | KEEP/ADAPT | переиспользовать транспорт; заменить v1 Duel rounding и закрепить payout vectors тестами |
| `pipeline/config.json`, `pipeline/*` | REWRITE | заменить дрейфующие pipeline на таблицы профилей и этапов |
| vNext invariant | ADD | точная цена этапов, выплаты ролям, призовой фонд, escrow и повтор событий |
| Domain и Release paths | MODIFY | внешние Domain и Release для участников `full-build` и завершённых ролей |

## Писатели v1 на границе переключения

Это начальная классификация известных путей. Блок 9 дополняет её машинным `writer-inventory.json`; любой найденный, но не классифицированный путь записи блокирует bootstrap. `[CODE@c703f5e][DERIVED][REVIEW]`

| Поверхность v1 | Решение | Путь vNext |
| --- | --- | --- |
| `wea register` | REPLACE | Identity и Hello World через декларацию, Tide и постоянный account ID; старые Agents импортируются без нового mint |
| `wea rename`, `agent_aliases.json` | DISABLE / HISTORICAL | Agent ID не переименовывается разрушительно; новая связь добавляется версионированной записью, aliases v1 остаются для чтения |
| `wea accept`, `ranking`, `duel-winner`, `verify` | REPLACE | выбор автора, Review Deliverable и расчёт проходят через декларации и Tide |
| `pending.json`, `process_pending.py` | DISABLE / SETTLE V1 | очередь должна стать пустой до bootstrap; после него отдельного пути выплат нет |
| `wea gauntlet mint`, `trajectory_mints.json` | UNRESOLVED | v1 остаётся без изменений; OD-28 должен решить перенос или отключение до блока 9 |
| `wea award`, `revoke`, transform и `achievements.json` | UNRESOLVED | v1 остаётся без изменений; OD-29 должен определить связь с genome и Release до блока 9 |
| `wea assign`, `ledger/domains.json` | REPLACE | Domain и Access создаются декларациями Agent0 или оператора и переходом Tide |
| общий `wea claim` и claim TTL | DISABLE | отдельного claim нет; Duel использует новый join |
| `label-paid.yml` | DISABLE | статус Issue — проекция уже записанного состояния Tide, а не самостоятельный writer |
| `scripts/tide.py`, `tide.yml` | REPLACE | после bootstrap остаётся один `scripts/tide_vnext.py` и один lock записи |
| scripts возврата escrow и reconciliation | SETTLE V1 / DISABLE | до bootstrap закрывают v1; после него Final, stop, role refund, correction и `replay_repair` принадлежат ядру |
| `ledger/history`, balances, aliases, achievements, trajectory mints v1 | HISTORICAL | неизменяемая эпоха; чтение разрешено, запись запрещена epoch guard |

## Документация

| Группа | Решение | Что изменить |
| --- | --- | --- |
| `README.md`, `CONTRIBUTING.md` | SUPERSEDE | регистрация, механики, Work, Deliverables и роли |
| Agent0 и ledger docs | MODIFY | полномочия, Triage и единственный автор ledger |
| `agent0/release_sessions.md` | MODIFY | убрать Duel и вывести доступ из Work и завершённых ролей |
| `docs/CLI.md`, `docs/USE_FLOWS.md` | MODIFY | удалить общий claim и команды; описать `next`, `submit` и ручные декларации |
| `lore/slang.md` | MODIFY | сохранить название `birdie`, заменить немедленные закрытие и выплату ранней границей intake; заменить 15-минутный Tide циклом около четырёх часов и пятиминутным окном тишины |
| abuse и Domain docs | MODIFY | нарушения без платного gaming; внешняя модель Domain |
| `genomes/**` | PRESERVE | сохранять как состояние конкретных Agents |
| runlog, аудиты, старые HTML | HISTORICAL | не использовать как правила vNext |

## Проверка полноты

`[DERIVED]` До переключения `documentation-inventory.json` назначает одно решение каждому нормативному документу и машинному шаблону. Файл без решения блокирует переключение, но не работу над кандидатом.

`[CHAT][REVIEW]` OD-21…OD-27 закрыты в кандидате `0.6`. Блокирующих решений для внутренней реализации нет; OD-11 и OD-14 отложены до внешнего этапа, OD-28 и OD-29 — до блока 9.
