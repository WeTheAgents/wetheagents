# Sub-agent plan: Retrosheet CSV → starter logs → entering-game pitcher features

Цель: автономно собрать **честные entering-game** фичи стартовых питчеров из Retrosheet CSV-архивов, **без play-by-play**.

Входные данные уже скачаны локально:
- `D:\GitHub\mlb-betting\retrosheets\YYYYcsvs.zip` для 2010–2025
- (есть также `gl*.zip` и `2010seve.zip`, но они не обязательны)

Формат архива (проверено на 2019):
- `YYYYpitching.csv` — per-pitcher per-game stat line (ключевые поля ниже)
- `YYYYgameinfo.csv` — per-game metadata (`gid`, date, home/away teams, doubleheader number)
- `YYYYallplayers.csv` — throws/bats + имена (опционально)
- `YYYYplays.csv` — play-by-play (НЕ использовать в этом процессе)

---

## Что нужно получить (артефакты)

### A) `starter_game_logs` (основная таблица)
2 строки на игру: стартер гостей и стартер хозяев.

**Колонки минимум:**
- `gid` (строка)
- `season` (int)
- `date` (date)
- `game_num` (int) — из `gameinfo.number` (0/1/2)
- `home_team`, `away_team` (Retrosheet team codes)
- `team` (за кого бросал питчер)
- `is_home` (bool)
- `opponent` (строка)
- `pitcher_id` (Retrosheet player id: например `beckj002`)

**Pitching line (минимум для WHIP/KBB/K9/BB9/HR9):**
- `outs` = `p_ipouts` (int)
- `ip` = `outs / 3.0` (float)
- `h` = `p_h`
- `bb` = `p_w`
- `so` = `p_k`
- `er` = `p_er`
- `hr` = `p_hr`
- + полезно: `bfp` = `p_bfp`, `hbp` = `p_hbp`

### B) `starter_entering_features` (ENTERING game)
Одна строка на **стартер-игру** (та же гранулярность, что и `starter_game_logs`), но метрики считаются **строго по играм < текущей**.

**МVP набор метрик (в двух окнах short=5, long=15):**
- `whip_short/long`
- `kbb_short/long`
- `k9_short/long`, `bb9_short/long`, `hr9_short/long`
- `ip_prior`, `starts_prior` (expanding до игры)
- `ip_short/long`, `starts_short/long` (как мера надёжности окна)

**Опционально: season-to-date аналоги** (если хотим “форма сезона” отдельно от карьеры).

### C) `game_id_bridge` (для стыковки с нашим датасетом игр)
Одна строка на игру:
- `gid`, `season`, `date`, `home_team`, `away_team`, `game_num`
- `home_starter_id`, `away_starter_id`

### D) (опционально) `player_dim`
Если используем `YYYYallplayers.csv`:
- `pitcher_id`, `first`, `last`, `throw`, `bat`, `first_g`, `last_g`

---

## Извлечение данных (без распаковки zip на диск)

### 1) Итерация по годам
Для каждого `YYYYcsvs.zip`:
1. Прочитать `YYYYgameinfo.csv` в DataFrame `games`.
2. Прочитать `YYYYpitching.csv` в DataFrame `pitching`.
3. Оставить только стартеров: `pitching[p_seq == 1]`.
   - `stattype` в 2019 всегда `value`, но лучше не зависеть: если есть колонка, можно `stattype == 'value'` (безопасно).
4. Join `starters` ↔ `games` по `gid`.
5. Добавить derived:
   - `date` = parse `gameinfo.date` (YYYYMMDD)
   - `game_num` = int(`gameinfo.number`)
   - `home_team = hometeam`, `away_team = visteam`
   - `is_home = (team == hometeam)`; `opponent = visteam if is_home else hometeam`
   - `outs = p_ipouts`, `ip = outs/3`
6. Валидация по году:
   - для каждого `gid` должно быть ровно 2 стартера (по `team` = home и away)
   - для каждого (`gid`, `team`) должен быть ровно 1 стартер.
7. Аппенд в общий `starter_game_logs`.

### 2) Порядок игр для rolling
Сортировка **строго**:
`pitcher_id`, затем `date`, затем `game_num`.

Почему важно: doubleheaders — второй матч дня должен видеть статистику первого при построении entering-game фич.

---

## Построение entering-game фич (anti-leak обязательно)

Принцип: для строки i берём агрегаты по рядам `< i` внутри группы.

Реализация (псевдо):
- сгруппировать по `pitcher_id` (и опционально по `season` для season-to-date)
- для кумулятивных сумм использовать `shift(1)` перед `cumsum()`
- для окон last-N использовать `shift(1).rolling(N).sum()`

Суммы, которые нужны:
- `H_sum`, `BB_sum`, `SO_sum`, `HR_sum`, `ER_sum`, `outs_sum`

Метрики:
- `ip = outs_sum/3`
- `whip = (H_sum + BB_sum) / max(ip, eps)`
- `kbb = SO_sum / max(BB_sum, 1)` (или NaN при 0 — договориться)
- `k9 = 9*SO_sum / max(ip, eps)` и аналогично `bb9`, `hr9`

Edge cases:
- дебют питчера / мало истории: оставить NaN, но обязательно сохранить `starts_prior`/`ip_prior` (модель сама научится).

---

## Выходные форматы и хранение

Рекомендуемый минимум (файлы рядом с проектом):
- `D:\GitHub\mlb-betting\data\processed\pitchers\starter_game_logs.parquet`
- `D:\GitHub\mlb-betting\data\processed\pitchers\starter_entering_features.parquet`
- `D:\GitHub\mlb-betting\data\processed\pitchers\game_id_bridge.parquet`
- `D:\GitHub\mlb-betting\data\processed\pitchers\build_report.md` (coverage/валидации/проблемы)

Опционально: поднять “one-page SQL” как **DuckDB файл** (без сервера):
- `D:\GitHub\mlb-betting\data\processed\pitchers\retrosheet_pitchers.duckdb`
Плюсы: удобно проверять join’ы и coverage SQL-запросами.

---

## Acceptance criteria (что считать успехом)

1) **Coverage**
- Для каждого года 2010–2025: доля игр с 2 стартерами ≥ 99% (если меньше — отчёт, почему).

2) **Consistency**
- Нет дубликатов стартера на (`gid`, `team`)
- Нет игр, где стартер = NULL

3) **Anti-leak**
- entering-game агрегации не используют текущую игру (проверить на 2–3 примерах вручную).

4) **Performance**
- Процесс должен проходить на обычном ноутбуке без распаковки огромных файлов и без `plays.csv`.

---

## Комментарии по “нужно ли SQL”

Рекомендация: **DuckDB да**, но как опциональный слой.
- Если всё делаем в Pandas/Polars и сохраняем Parquet — этого достаточно.
- DuckDB полезен для быстрых проверок “покрытие/дубликаты/джойны” и для будущих экспериментов.

