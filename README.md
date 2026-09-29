<div align="center">
<img width="1200" height="475" alt="GHBanner" src="https://ai.google.dev/static/site-assets/images/share-ais-513315318.png" />
</div>

# Run and deploy your AI Studio app

This contains everything you need to run your app locally.

View your app in AI Studio: https://ai.studio/apps/f487301b-d4b8-4c1b-a470-6fc811c24d2d

## Run Locally

**Prerequisites:**  Node.js


1. Install dependencies:
   `npm install`
2. Set the `GEMINI_API_KEY` in [.env.local](.env.local) to your Gemini API key
3. Run the app:
   `npm run dev`

## Historical (Previous-Year) Rainfall — Kerala

The platform ships a provenance-only historical rainfall module for Kerala. No data is
fabricated at runtime: every surface reports `HISTORICAL DATA SOURCE NOT CONFIGURED` until a
verified previous-year CSV is imported.

**Dataset format** (columns): `district, observation_date (YYYY-MM-DD, year must match
data_year), rainfall_mm (0..1500), source, source_reference, data_year`, optional
`hazard_type ∈ {rainfall, flood, landslide, extreme rainfall, cyclone, other}`.

Suggested official sources: India-WRIS, IMD gridded rainfall, KSDMA records. A template with
full field rules lives in `backend/app/data/historical/README.md`.

**Import** (from `nammasafe-ai/backend`, venv python):

```bash
python scripts/import_historical_data.py --dataset path/to/rainfall.csv --year 2025 --dry-run
python scripts/import_historical_data.py --dataset path/to/rainfall.csv --year 2025
```

**API** (all public reads, tagged `HISTORICAL` / `NOT CONFIGURED`):

- `GET /api/historical/availability`
- `GET /api/historical/kerala`
- `GET /api/historical/kerala/{district}`
- `GET /api/historical/kerala/{district}/baseline`
- `GET /api/historical/kerala/{district}/compare?rainfall_mm=..&observation_date=..`

Percentile baselines (P50/P90/P95, minimum 30 observations) drive severity ratios:
`≥1.2 Elevated`, `≥1.5 High`, `≥2.0 Extreme` versus the previous-year average. Frontend
surfaces: dashboard card, GIS overlay panel, and Data Source Status `Historical Rainfall` layer.
