# Station Configs

`stations_canonical.json` is the single source of truth for city station identity,
forecast coordinates, resolution source metadata, and US station registry fields.
Do not hand-edit the generated legacy files.

To update station metadata:

```bash
python -m scripts.gen_station_configs
python -m pytest tests/test_station_configs.py -q
```

The generator rewrites:

- `data/static/icao_map.json`
- `data/static/polymarket_cities.json`
- `data/static/stations.json`

`tests/test_station_configs.py` guards drift by regenerating those files in
memory and comparing them byte-for-byte with the committed versions.

## 2026-07-06 Audit Corrections

Station corrections:

- `houston`: `KIAH` -> `KHOU`
- `london`: `EGLL` -> `EGLC`
- `dallas`: `KDFW` -> `KDAL`
- `denver`: `KDEN` -> `KBKF`
- `moscow`: `UUEE` -> `UUWW`
- `jakarta`: `WIII` -> `WIHH`

Resolution source corrections:

- `moscow`: Weather Underground -> NOAA weather.gov timeseries
- `istanbul`: Weather Underground -> NOAA weather.gov timeseries
- `tel-aviv`: NOAA weather.gov timeseries -> Weather Underground
- `taipei`: CWA station `46692`, not Weather Underground or weather.gov
