# Real data ingestion

The platform never fabricates data. Every real dataset is listed in
`app/data_catalog.py` (served at `GET /api/data-catalog`), and ingestion of the
operator-provided official files is done by the idempotent scripts below.

Run everything from `backend/`:

| Dataset                | Directory to fill                | Importer                              |
|------------------------|----------------------------------|---------------------------------------|
| Admin boundaries       | `app/data/admin_boundaries/*.json` | `python scripts/import_admin_boundaries.py` |
| Census 2011 villages   | `app/data/census_2011/*.csv`       | `python scripts/import_census_2011.py` |
| Historical rainfall    | `app/data/historical/*.csv`        | `python scripts/import_historical_data.py` |
| ERA5 historical weather| any CSV path                      | `python scripts/import_historical_weather.py --dataset .../era5_*.csv` |
| Past disaster events   | (curated seed, no file needed)    | `python scripts/seed_disaster_events.py` |
| GPM IMERG tiles        | `GPM_DATA_DIR`                     | `python scripts/fetch_gpm_data.py --recent` |
| GloFAS forecasts       | (needs CDS key)                   | `python scripts/fetch_glofas_data.py` |

All importers are idempotent (duplicate rows are skipped, never double-written),
support `--dry-run`, and **reject** malformed rows instead of guessing values.
Always run once with `--dry-run` first.

## Official sources

* Admin boundaries / LGD codes — Survey of India, NIC LGD directory: https://lgdirectory.gov.in/
* Census 2011 Primary Census Abstract — Census of India: https://censusindia.gov.in/
* Historical Kerala rainfall — India-WRIS / IMD / KSDMA (see `historical/README.md`)
* ERA5 reanalysis — Copernicus ECMWF (C3S licence), or the Open-Meteo Archive API that NammaSafe already queries live:
  https://archive-api.open-meteo.com/v1/archive
* NASA GPM IMERG — NASA GES DISC: https://gpm1.gesdisc.eosdis.nasa.gov/
* ECMWF GloFAS — Copernicus Climate Data Store: https://cds.climate.copernicus.eu/

## Shape/column contracts

* **admin_boundaries**: GeoJSON `FeatureCollection`; each feature's `properties`
  has `name`, `level` (4=state, 5=district, 6=block), `state`, optional
  `district`, `code`, plus `geometry` and an optional `centroid
  {latitude, longitude}`.
* **census_2011**: CSV with `village_code, village_name, district, state,
  total_population, total_households, male_population, female_population,
  child_population, area_km2, latitude, longitude`.
* **historical weather**: CSV with `latitude, longitude, year, month, variable,
  aggregation, value, [data_source, dataset, provider]`. `variable` uses ERA5
  keys (`temperature_2m`, `precipitation`, `thunderstorm_days`, ...);
  `aggregation` labels the summarisation (`monthly_total`, `monthly_mean`,
  `monthly_mean_of_daily_max`, `days`, ...).