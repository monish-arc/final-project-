# Historical / Previous-Year Kerala Rainfall Data

This directory is the **drop-point for verified, source-documented CSVs** used by
the historical-data subsystem. It intentionally contains **no sample/fabricated
file** — a dataset is imported only when an operator provides one.

## Status: HISTORICAL DATA SOURCE NOT CONFIGURED

Until a CSV is dropped here and imported (see below), every historical endpoint
answers `status: "NOT CONFIGURED"` and the frontend shows the banner
`HISTORICAL DATA SOURCE NOT CONFIGURED`. The system never invents data.

## Expected CSV format

UTF-8 (BOM tolerated), header row required:

| column           | required | example                  | notes                                                            |
| ---------------- | -------- | ------------------------ | ---------------------------------------------------------------- |
| `district`       | yes      | `Wayanad` or `567`       | Kerala LGD code or name; validated against the single source      |
| `observation_date` | yes    | `2025-06-15`             | real YYYY-MM-DD; must fall inside `data_year`                    |
| `rainfall_mm`    | yes      | `183.5`                  | finite, `0 .. 1500`                                               |
| `source`         | yes      | `IMD Gridded`            | short provenance label                                            |
| `source_reference` | yes    | `https://.../station`    | URL/ID used for idempotent dedupe (unique per district+date+year) |
| `data_year`      | yes      | `2025`                   | integer; defines the dataset year                                 |
| `hazard_type`    | no       | `rainfall`               | default `rainfall`; one of rainfall, flood, landslide, extreme rainfall, cyclone, other |

One row per district per day. Missing dates are reported, never interpolated.

## How to import

From the backend directory:

```bash
python scripts/import_historical_data.py --dataset app/data/historical/kerala_2025.csv --year 2025
python scripts/import_historical_data.py --dataset app/data/historical/kerala_2025.csv --year 2025 --dry-run
```

Re-runs are idempotent: rows already present (same district + date + year +
source_reference) are skipped. The process exits non-zero if any row is
rejected, and rejects are never committed.

## Official, documented sources (must be cited in `source_reference`)

- **India-WRIS** — Rainfall API / water resource data for Kerala districts.
  https://indiawris.gov.in/wris/#/rainfall
- **IMD Gridded Rainfall data** (0.25° × 0.25°, `fn` files) and district-wise
  city rainfall.
  https://imdpune.gov.in/ (Rainfall / Gridded data pages)
- **KSDMA** — Kerala State Disaster Management Authority, district-wise
  rainfall & alerts.
  https://sdma.kerala.gov.in/

Any dataset imported must carry a real `source_reference` to one of the above
(or an equally documented equivalent). Personal/unverifiable data must not be
imported.