# WEA vNext: принятые решения и Block 9 BDD

**Версия пакета:** `2026-08-17.1`

**Статус:** все шесть решений приняты. S13C готов и слит. Block 9 Outcome и
BDD 1.0 приняты без изменений 2026-08-17. Разрешён только Design. WEA vNext не
включён.

## Принятые решения

1. `SDD-01`: отсутствие исходного RED-лога принято как честно указанное
   ограничение. Проект не утверждает, что этот лог существует.
2. `SDD-02`: документальная сверка принята. Она не меняет финансовую логику и
   не включает vNext.
3. `OD-28`: первый cutover не переносит gauntlet mint. Старые записи остаются
   читаемой историей и не создают новые WEA.
4. `OD-29`: achievements, award, revoke и transform остаются читаемой историей
   без активного эффекта vNext.
5. `NEXT-01`: разрешено подготовить Outcome, BDD и направление Design для
   Block 9. Точный BDD, Design и live cutover имеют отдельные gates.
6. `BLOCK9-ACCEPT-01`: точный Block 9 Outcome/Spec 1.0 принят без изменений.
   S-71…S-79 обязательны для Design; implementation и live cutover не
   разрешены.

Будущий механизм achievements или похожая механика для ikigai и поиска
идентичности важны. Эта работа получит отдельные Outcome и Spec. Она не входит
в первый cutover.

## Что обязан доказать Block 9

- `S-71`: независимо собранный writer universe обнаруживает пропуск, поздний
  writer и обход epoch guard.
- `S-72`: v1 escrow закрывается до cutover. Conversion intent не создаёт
  двойной escrow, а после cutover один атомарный переход создаёт debit,
  program escrow, Plan, Task и первый дочерний Contract. Прямой Contract
  запрещён. Intent фиксирует точный Issue, автора-плательщика (один Agent ID),
  полный Plan, bank/runtime, настоящее действие через привязанный аккаунт,
  срок и одноразовый ключ. Нехватка денег отменяет его без возможности
  автоматического возобновления.
- `S-73`: genesis воспроизводит одинаковое каноническое состояние и хранит
  conversion intents без активных Contracts.
- `S-74`: shadow replay не делает рабочих записей и повторяется одинаково.
- `S-75`: авторитетные epoch и ledger effects атомарны. Один approval bundle
  фиксирует точные bootstrap bytes, epoch, predecessor, результат, единственный
  writer — точно `agent0@system` — и его действующий credential binding.
  Проекции отделены.
- `S-76`: gauntlet mint остаётся историей и не создаёт WEA.
- `S-77`: achievements остаются историей. Genesis сохраняет отдельно сверенный
  genome snapshot и не меняет его replay истории.
- `S-78`: durable correction и replay repair с crash/restart evidence являются
  обязательными до cutover. Durable correction сохраняет или усиливает все
  финансовые и tamper-гарантии S13C 1.1. Текущий inactive S13C недостаточен.
- `S-79`: ошибка внешней проекции видна как degraded status. Idempotent retry
  сводит все поверхности без повторения денег.

Точный frozen snapshot находится в `../wea-vnext-block9-cutover/spec.md`, а
его SHA-256 acceptance binding — в `WEA_vNext_BLOCK9_ACCEPTANCE.txt`. Внутри
snapshot сохранены preparation-time метки `proposed/pending` и overlay 1.1;
binding и текущий parent overlay 1.2 фиксируют более позднее принятие без
перезаписи принятых bytes.

## Что разрешено сейчас

- Подготовить Block 9 Design: writer inventory,
  reconciliation, genesis, shadow replay, atomic cutover, epoch guard,
  recovery и exact approval bundle.
- Написать план реализации только после принятия Design.

## Что не разрешено

- Не включать vNext.
- Не менять ledger.
- Не запускать writers.
- Не создавать genesis или bootstrap.
- Не менять credentials и permissions.
- Не подключать S13C к live-системе.

## Неблокирующие решения

- `OD-11`: цена дополнительного агента. Вернуться после внутреннего прогона.
- `OD-14`: DCO или CLA. Решить до открытия внешних вкладов.
- `IKIGAI-01`: отдельно проработать achievements или похожий механизм поиска
  идентичности.
