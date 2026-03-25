# Session 6 Handoff — NBM Integration via Herbie

## Цель сессии

Подключить NBM (National Blend of Models) как второй источник day-specific
sigma.  NBM объединяет ~10 моделей (200+ ensemble members), уже откалиброван
NOAA, обновляется каждый час.  Это самый мощный бесплатный источник
неопределённости для температурных прогнозов.

## Почему NBM лучше текущего GEFS-only

| Параметр | GEFS (текущий) | NBM (цель) |
|----------|---------------|------------|
| Кол-во моделей | 1 (GFS) | ~10 (GFS, NAM, ECMWF, HRRR...) |
| Ensemble members | 30 | 200+ суммарно |
| Калибровка | нет (raw spread) | уже откалибровано NOAA |
| Обновление | 4x/день | ежечасно |
| Перцентили | нет (считаем сами) | P1-P99 готовые |
| Sigma формула | std(members) | (P90-P10)/2.56 — честные перцентили |

## Техническое решение: Herbie + GRIB2

### Библиотека

`herbie-data` (PyPI) — Python-клиент для доступа к NOAA моделям через AWS S3
и NOMADS.  Умеет скачивать GRIB2-файлы (или подмножества), парсить в xarray.

### Установка

```bash
uv add herbie-data
# или
pip install herbie-data
```

Зависимости: `xarray`, `cfgrib`, `eccodes`.  На Windows `eccodes` ставится
через pip (бинарники включены).  Если не заработает — conda fallback:
`conda install -c conda-forge eccodes`.

### NBM продукт: QMD (Quantile Matching Distribution)

QMD-файлы содержат перцентили температуры.  Доступны для циклов 00Z/06Z/12Z/18Z.

```
blend.t{cycle}z.qmd.f{fxx}.co.grib2
```

GRIB2 search strings для температурных перцентилей:
```
:TMP:2 m above ground:.*P10    # 10-й перцентиль
:TMP:2 m above ground:.*P25    # 25-й
:TMP:2 m above ground:.*P50    # 50-й (медиана)
:TMP:2 m above ground:.*P75    # 75-й
:TMP:2 m above ground:.*P90    # 90-й
```

**ВАЖНО:** Точные search strings нужно проверить через `H.inventory()` —
NOAA меняет именование между версиями.  Начинать сессию с инвентаризации.

### Извлечение точечных данных

```python
from herbie import Herbie
import pandas as pd

H = Herbie("2026-03-25 12:00", model="nbm", product="co", fxx=24)

# Проверить что есть
inv = H.inventory(":TMP:2 m")
print(inv[['search_this']])

# Загрузить перцентили
ds = H.xarray(":TMP:2 m above ground:")

# Извлечь для станции
point = pd.DataFrame({
    "latitude": [40.7772],
    "longitude": [-73.8726],
    "station": ["KLGA"]
})
data = ds.herbie.pick_points(point, method="weighted", k=4)
```

## Что создавать

### 1. `src/nbm_client.py` — клиент NBM данных

```python
@dataclass
class NBMForecast:
    target_date: date
    station: str
    cycle: str              # "00", "06", "12", "18"
    percentiles: dict[int, float]  # {10: 52.0, 25: 54.0, 50: 56.0, ...}
    sigma: float            # (P90-P10)/2.56
    median: float           # P50

def fetch_nbm_percentiles(
    station_icao: str,
    lat: float, lon: float,
    target_date: date,
    cycle: str = "12",
    fxx: int = 24,
) -> NBMForecast:
    """Fetch NBM MaxT percentiles для одной станции."""

def fetch_nbm_batch(
    stations: list[str],
    target_date: date,
) -> list[NBMForecast]:
    """Fetch NBM для всех станций за один запрос (один GRIB2-файл)."""
```

Ключевая оптимизация: GRIB2-файл покрывает весь CONUS.  Скачать один раз,
извлечь все три станции — не делать 3 отдельных запроса.

### 2. `NBMForecaster` в `src/forecaster.py`

```python
class NBMForecaster(Forecaster):
    name = "NBM"

    def predict_day(self, forecast_temp, station, month, forecast_date, context):
        if context and "nbm_percentiles" in context:
            pctls = context["nbm_percentiles"]
            sigma = (pctls[90] - pctls[10]) / 2.56
            mu = pctls[50]
            return CalibratedForecast(
                mu=mu, sigma=max(sigma, MIN_SIGMA),
                method=self.name,
                distribution="empirical",
                percentiles=pctls,
            )
        # fallback
        return self.predict(forecast_temp, station, month)
```

NBM уже даёт перцентили — можно использовать `distribution="empirical"` и
передавать их в bracket_builder напрямую, без параметрического допущения.

### 3. Обновить `scripts/run_live_edge.py`

Добавить NBM как источник данных рядом с Open-Meteo ensemble.  Приоритет:
1. NBM percentiles (если доступны)
2. Open-Meteo ensemble spread (fallback)
3. Historical sigma (last resort)

### 4. Обновить scheduled task

Добавить NBM snapshot в ежедневную задачу `accumulate-ensemble`.

## Архив и бэктестинг

- **NOMADS**: rolling 1-2 дня (только свежие файлы)
- **AWS S3**: `s3://noaa-nbm-grib2-pds/` — расширенный архив
- **Глубина**: GRIB2-файлы с ~2020, но полноценные QMD — проверить
- Для 22-летнего бэктеста NBM не годится — только для live и recent validation

## Возможные проблемы

1. **eccodes на Windows** — если pip-версия не работает, нужен conda или
   ручная установка бинарников
2. **GRIB2 searchString** — именование переменных может отличаться от
   документации; начинать с `H.inventory()` для реального файла
3. **Размер файлов** — полный CONUS GRIB2 ~50-200MB; использовать
   `searchString` для subset (скачивает только нужные переменные ~1-5MB)
4. **Forecast hour mapping** — MaxT привязан к определённым fxx;
   нужно найти правильный fxx для "завтрашнего high" из цикла 12Z

## Проверка результата

1. NBM sigma для KLGA/KORD/KMIA на ближайшие дни
2. Сравнение NBM sigma vs GEFS ensemble spread vs historical sigma
3. Bracket probs из empirical CDF (NBM percentiles) vs Gaussian (ensemble)
4. Edge analysis: NBM-based model vs Polymarket prices
