# Открытые решения

Статус кандидата `1.0`: прежние OD-24…OD-33 и развилки BD-01…BD-03 закрыты. Оператор принял внешний Circle-1 Domain, immutable registry, внутренний семидневный Access и отдельную поставку S-13C. Нормативная delta находится в `spec.md`. OD-11, OD-14, OD-28 и OD-29 остаются отложенными. `[CHAT][CHECK]`

### Закрыто в кандидате 0.8

- **OD-30.** Автор не выбирает профиль. Triage/Negativa предлагает один Resolution Plan из ordered `depth × mode` стадий и распределяет объявленный максимальный bank; автор сохраняет окончательный голос. `[CHAT]`
- **OD-31.** Approval точной Plan revision одним атомарным переходом списывает полный bank в program escrow и создаёт только первый child Contract/Task. Последующие child Contracts Tide создаёт автоматически, без нового author-authored Contract. `[CHAT][DERIVED]`
- **OD-32.** Future inputs сохраняются symbolic selectors. Неоднозначность ставит Plan на паузу; replan меняет только незапущенный suffix append-only ревизией с новым author approval. `[CHAT][DERIVED]`
- **OD-33.** Frontier сохраняет конечные Linear/Fibonacci incentives, exact snapshot identity и prior-art novelty. Нормализованный validator предпочтителен, иначе окончательный verdict принадлежит автору; автор также может закрыть оставшийся research budget. `[CHAT]`

### Закрыто в кандидате 0.6

- **OD-24.** CLI подставляет Agent ID сам. Ручная декларация содержит `agent_id`; Tide проверяет связь с GitHub account автора комментария. Work ID, этап и ревизию агент не вводит. `[CHAT][DERIVED][REVIEW]`
- **OD-25.** Автор задачи всегда платит её полный bank и одобряет точные body и hash, bank, профиль, механику, версию правил и Triage той же ревизии. Стороннего плательщика в WEA нет. Дальнейшая передача результата не относится к WEA. `[CHAT]`
- **OD-26.** Каждый эпизод расхождения body ставит Task на паузу до остановки Agent0 или подтверждённого восстановления body из Contract. Tide сдвигает незавершённые сроки на длительность эпизода, а повтор не сдвигает их дважды. Свободный текст автора сам не продлевает срок. `[CHAT][DERIVED][REVIEW]`
- **OD-27.** Два разных агента, не автор Contract, принимают места. Второй допустимый join задаёт `duel_start_at`; Contract хранит порядок и длительности, Duel — шесть абсолютных слотов ходов. `[CHAT][DERIVED][REVIEW]`

## Отложено

| ID | Вопрос | Когда вернуться | Источник |
| --- | --- | --- | --- |
| OD-11 | Сколько стоит дополнительный агент? | После внутреннего прогона; дополнительный агент не получает Hello World mint. | `[DOC][CHAT]` |
| OD-14 | Какие правила нужны для внешних вкладов? | До открытия внешних PR выбрать DCO или CLA и зафиксировать права. | `[DOC][REVIEW][CHAT]` |
| OD-28 | Сохраняется ли gauntlet mint как экономическая механика vNext? | До блока 9. v1 продолжает работать; без решения этот путь записи нельзя ни отключить, ни перенести в vNext. | `[CODE@c703f5e][REVIEW]` |
| OD-29 | Что делать с achievements, award/revoke и transform? | До блока 9 определить их место относительно genome и Release. До решения v1 остаётся без изменений. | `[CODE@c703f5e][REVIEW]` |

Сами OD-11, OD-14, OD-28 и OD-29 не мешают проверенному control plane Spec `1.0` или reference runtime Spec `0.9`. Для этой delta блокирующих решений нет. OD-28 и OD-29 блокируют только будущий live migration/bootstrap block; они не разрешают live writes или cutover. `[CHAT][DERIVED][CHECK]`
