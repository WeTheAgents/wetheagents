# Каталог 67 фич (текущий пайплайн) — для ручной валидации

Этот файл описывает **ровно те 67 фич**, которые реально добавляются функцией
`build_all_features(games, include_pitcher=True)` из [`src/features.py`](d:\GitHub\mlb-betting\src\features.py)
и мерджем питчер-фич из [`src/pitcher_features.py`](d:\GitHub\mlb-betting\src\pitcher_features.py).

Важно: рыночные колонки (например `home_implied_prob`, `home_decimal_odds`, `close_ou`) **не входят** в эти 67 фич.
Их можно добавлять в модель отдельным экспериментом, но в этом каталоге мы фиксируем “чистый” feature set пайплайна.

---

## Как фича влияет на обучение модели (простыми словами)

Когда мы **включаем фичу** в обучение, мы разрешаем модели использовать её как дополнительный сигнал, чтобы отличать
ситуации “команда A с высокой вероятностью выиграет” от “команда A с низкой вероятностью выиграет”.
Если фича действительно несёт информацию (и эта информация доступна **до матча**), модель может улучшить качество прогнозов:
уменьшить ошибку вероятностей (LogLoss/Brier), поднять AUC и — самое главное — дать больше случаев, где модель видит edge.

Когда мы **выключаем фичу**, мы уменьшаем объём информации и свободу модели. Это может **ухудшить** качество,
если фича была полезной. Но иногда выключение **помогает**, если фича:
- шумная (сильно “прыгает” и не повторяется на будущем),
- дублирует другие признаки (сильная корреляция, мало добавочной информации),
- или ведёт к переобучению (модель “подгоняет” редкие паттерны под TRAIN, а на TEST они не работают).

Критически важно: **если фича содержит утечку (leakage)** — т.е. использует информацию “из будущего” относительно матча
(например итоговый счёт, иннинги, любые outcome-данные), модель покажет “фантастические” результаты на обучении,
но это будет невалидно. Поэтому ручная валидация фич = в первую очередь проверка, что каждая фича считается
только из матчей, сыгранных **до** текущей даты.

---

## Правила ручной валидации (чек-лист)

1. **Нет утечки**: фича для игры на дату `date` должна зависеть только от игр команды/питчера с датой `< date`.
2. **Ожидаемые диапазоны**:
   - вероятности/доли: 0..1 (`wp_*`, `*_wr_*`)
   - RPI/SOS: около 0.35..0.65 (приблизительно)
   - `streak_*`: целые, обычно в разумных пределах (±10..±15)
   - RA (runs allowed) прокси: обычно 0..10 (иногда больше)
3. **NaN там, где ожидаем**:
   - командные rolling-фичи могут быть “сыроваты” в начале сезона (первые 10–20 игр),
   - питчер-фичи **NaN до 3 предыдущих стартов** (см. `min_sample=3` в `pitcher_features.py`).
4. **Согласованность диффов**:
   - `*_diff = home - away` (по определению, знак должен совпадать).
5. **Сезонность**: фичи не должны “перетекать” между сезонами (rolling считается внутри `team, season` / `pitcher, team`).

---

## 35 Team features (из `src/features.py`)

Источник: `build_team_game_log()` → rolling WP, streak, runs, rolling RPI → merge на `home_team/date` и `away_team/date`,
после чего считаются синтетические diff/min/max.

### A) Home team (13)
- `wp_home`: общий win% хозяев, **входя в матч**.
- `wp_home_at_home`: win% этой команды **в домашних** играх, входя в матч.
- `wp_home_on_road`: win% этой команды **в гостях**, входя в матч.
- `wp_last10_home`: win% за последние 10 игр, входя в матч.
- `wp_last20_home`: win% за последние 20 игр, входя в матч.
- `games_played_home`: сколько игр команда уже сыграла в сезоне, входя в матч.
- `streak_home`: signed streak (например +3 = W3, -2 = L2), входя в матч.
- `rpg_home`: runs scored per game (rolling), входя в матч.
- `rapg_home`: runs allowed per game (rolling), входя в матч.
- `rpg_last10_home`: runs scored per game за последние 10 игр, входя в матч.
- `rapg_last10_home`: runs allowed per game за последние 10 игр, входя в матч.
- `rpi_home`: rolling RPI, входя в матч.
- `sos_home`: компонент strength-of-schedule (в коде это `owp_component`), входя в матч.

### B) Away team (13)
Аналогично home-блоку, но для гостей:
- `wp_away`
- `wp_away_at_home`
- `wp_away_on_road`
- `wp_last10_away`
- `wp_last20_away`
- `games_played_away`
- `streak_away`
- `rpg_away`
- `rapg_away`
- `rpg_last10_away`
- `rapg_last10_away`
- `rpi_away`
- `sos_away`

### C) Synthetic / diffs (9)
Определения строго в `build_all_features()`:
- `rpi_diff = rpi_home - rpi_away`
- `wp_diff = wp_home - wp_away`
- `wp_last10_diff = wp_last10_home - wp_last10_away`
- `streak_diff = streak_home - streak_away`
- `rpg_diff = rpg_home - rpg_away`
- `rapg_diff = rapg_home - rapg_away`
- `rpi_min = min(rpi_home, rpi_away)`
- `rpi_max = max(rpi_home, rpi_away)`
- `games_played_min = min(games_played_home, games_played_away)`

---

## 32 Pitcher features (из `src/pitcher_features.py`)

Подход: прокси-метрики питчера из наших же матчей (без WHIP/K/BB/IP).
Ключевой момент: rolling делается по группам **(pitcher, team)**, чтобы не ломаться на трейдах/коллизиях кодов.
Окна по умолчанию: short=5 стартов, long=15 стартов. Минимум истории: **3 старта** до текущего (иначе NaN).

### D) Home SP (11)
- `home_sp_wr_short`: win rate команды со стартером (последние ~5 стартов), входя в матч.
- `home_sp_wr_long`: win rate (последние ~15 стартов), входя в матч.
- `home_sp_wr_momentum`: `wr_short - wr_long` (осциллятор), входя в матч.
- `home_sp_ra_short`: runs allowed (оппонент набрал за матч) среднее по short, входя в матч.
- `home_sp_ra_long`: runs allowed среднее по long, входя в матч.
- `home_sp_ra_momentum`: `ra_short - ra_long`, входя в матч.
- `home_sp_fi_ra_short`: first-inning runs allowed (противник в 1-м) среднее по short, входя в матч.
- `home_sp_fi_ra_long`: first-inning runs allowed среднее по long, входя в матч.
- `home_sp_fi_momentum`: `fi_short - fi_long`, входя в матч.
- `home_sp_hand`: рука из кода `-R/-L` или `None`.
- `home_sp_starts`: число стартов питчера в группе (pitcher, team) **до** матча.

### E) Away SP (11)
Аналогично home:
- `away_sp_wr_short`
- `away_sp_wr_long`
- `away_sp_wr_momentum`
- `away_sp_ra_short`
- `away_sp_ra_long`
- `away_sp_ra_momentum`
- `away_sp_fi_ra_short`
- `away_sp_fi_ra_long`
- `away_sp_fi_momentum`
- `away_sp_hand`
- `away_sp_starts`

### F) Composite / diffs (10)
Определения строго в `merge_pitcher_features_to_games()`:
- `sp_wr_short_diff = home_sp_wr_short - away_sp_wr_short`
- `sp_wr_long_diff = home_sp_wr_long - away_sp_wr_long`
- `sp_wr_momentum_diff = home_sp_wr_momentum - away_sp_wr_momentum`
- `sp_ra_short_diff = home_sp_ra_short - away_sp_ra_short`
- `sp_ra_long_diff = home_sp_ra_long - away_sp_ra_long`
- `sp_ra_momentum_diff = home_sp_ra_momentum - away_sp_ra_momentum`
- `sp_fi_ra_combined = (home_sp_fi_ra_long + away_sp_fi_ra_long) / 2`
- `sp_fi_momentum_diff = home_sp_fi_momentum - away_sp_fi_momentum`
- `sp_starts_diff = home_sp_starts - away_sp_starts`
- `sp_quality_floor = max(home_sp_ra_long, away_sp_ra_long)` (хуже из двух; меньше = лучше качество пары)

---

## Примечания специально для Series dogon

- В `src/series.py` фаворит серии выбирается по implied probability в G1 (`select_series_favorite(..., method="game1_odds")`).
- Для dogon важнее всего **качество входа в серию** (какие серии вообще брать), потому что математика ставок сильно зависит от odds.
- Поэтому при ручной валидации особенно полезно проверять, что “силовые” фичи (RPI/WP и питчер WR) не имеют утечки и выглядят разумно на ранних датах.

---

## Что НЕ должно попадать в модель (проверка на leakage)

Эти колонки должны быть исключены из feature matrix для ML (они outcome/идентификаторы):
- Итоги матча и иннинги: `home_final`, `away_final`, `total_runs`, `home_inn_*`, `away_inn_*`, `home_margin`, `home_rl_cover` и т.п.
- Идентичности: `home_team`, `away_team`, `home_pitcher`, `away_pitcher`, `matchup_key` (как категорию лучше не давать на старте).
- Дата как timestamp (`date`) — лучше использовать только сезон/месяц/кол-во игр (если вообще нужно).

