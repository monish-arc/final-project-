# SafeMove AI (NammaSafe AI) — Technical Soul / Master Audit

> Read-only technical audit of the repository exactly as it exists on disk.
> Generated from direct source inspection (`src/`, `nammasafe-ai/backend/app/`, root configs, `git` state,
> running services on ports 8000/3000/4173). No source files were modified; this document is the only artifact created.
>
> **Provenance vocabulary used throughout** (matches the code's own labels):
> **LIVE** = real external/data computation happening now · **HISTORICAL** = real past record (reanalysis/imported) ·
> **CALCULATED** = derived from real inputs by local rules · **CONFIGURED** = env was set correctly · **NOT CONFIGURED** =
> no credentials/dataset/env supplied (honest "unavailable") · **MOCK/DEMO/SIMULATED** = fabricated seed or demo data ·
> **CURATED** = real curated pilot records · **STATIC** = bundled reference data.
>
> **Security rule honoured here:** secrets (JWT secret value, passwords, NASA/Bhuvan tokens, DB passwords) are reported
> only as `[SECRET PRESENT — VALUE NOT SHOWN]` or by *pattern*, never as values.

---

## 1. What this project is

**SafeMove AI / NammaSafe AI** is a disaster decision-support platform prototyped for the **Chamoli district,
Uttarakhand** pilot: it maps habitations/villages, models terrain, weather, historical rainfall, flood and landslide
hazard, risk-scoring of villages, relocation-site planning, and risk-aware evacuation routing.

Two personalities share one codebase:
- **NammaSafe AI** — the original decision-support portal (relocation planning, habitations, evacuation, admin/RBAC).
- **SAFE_MOVE_AI live-intelligence layer** — a newer read-only layer of real-provider integrations (NASA SRTM terrain,
  ERA5 historical weather, Open-Meteo/ECMWF live weather (off by default), GloFAS flood, GPM rainfall, OpenStreetMap
  nearby places/geocode, Bhuvan/ISRO, rule-based risk engine).

The whole system is built on the **honesty principle**: whenever a live provider is not reachable or not configured the
backend returns a clearly-labelled `UNAVAILABLE` / `NOT_CONFIGURED` payload and the UI renders that label; no value is
ever fabricated to paper over a missing provider.

---

## 2. Repository structure

```
SAFE_MOVE_AI-main/
├─ src/                        Frontend (React 19 + Vite 6 + TypeScript)
│  ├─ App.tsx                  Shell: persona auth, state-tab routing, page switch
│  ├─ main.tsx                 Entry (StrictMode + ErrorBoundary)
│  ├─ services/api.ts          ALL backend calls, timeout contract, JWT handling, caches
│  ├─ types/index.ts           All TS contracts mirroring backend payloads
│  ├─ pages/                   12 pages (Dashboard … Docs) + Admin
│  ├─ components/              Navbar, Sidebar, LeafletMap, MapLayerPanel, modals, badges
│  ├─ components/commandcenter Risk Intelligence panels (10 files)
│  ├─ components/weathermap/   Weather & Hazard map UI (WeatherMap, wind canvas, panels)
│  ├─ components/weather/      WeatherForecastMap.tsx — LEGACY, unused
│  ├─ lib/                     terrainPopup state machine, weatherLayers, regionViewport,
│  │                           historicalDates, liveProviders, weatherBounds
│  └─ data/                    mockData.ts (demo users), regions/hierarchy.ts (state→district→
│                              sub-district tree), regions/villages/{36}.ts (VILLAGES_BY_SUBDISTRICT
│                              code+name only), regions/villages/villageLoaders.ts (code-split map)
├─ nammasafe-ai/backend/       FastAPI backend
│  ├─ app/main.py              Core app: all NammaSafe routes, seed data store, auth
│  ├─ app/integration_routes.py  SAFE_MOVE_AI live-intelligence router (mounted under /api)
│  ├─ app/                     ~40 provider/service/config modules (see §7)
│  ├─ alembic/                 7 migrations (real schema; demo data stays in-memory seed)
│  ├─ scripts/                 Data ingest/import/fetch tools (see §7)
│  ├─ tests/                   25 test files (see §7)
│  ├─ requirements.txt         Pinned backend deps
│  └─ nammasafe.db             Real SQLite DB (~2.6 MB) — cache/real-data tables
├─ docs/                       Spec/documents
├─ scripts/                    Node tooling: build-regions.mjs (generates village chunks),
│                              .cache/lgd/** (1,605 committed raw HTTP-cache files),
│                              .cache/mirror/4-village.csv (Git-LFS pointer, payload absent)
├─ docker-compose.yml          Postgres/PostGIS + backend + frontend stack
├─ Dockerfile.frontend         Frontend image
├─ Node: package.json, vite.config.ts, tsconfig.json, index.html,
│        bun.lock + package-lock.json (dual lockfiles present)
├─ .env.example                ~57 documented variable names (values blank)
├─ .gitignore / .gitattributes (LFS rule for 4-village.csv)
├─ apikeynasa.env.env          NASA Earthdata JWT — gitignored, never to be committed
├─ metadata.json, run_all.py, plan1.md, plan2.md, ARCHITECTURE.md
├─ README.md                   NOTE: contains unresolved merge-conflict markers
└─ .nammasafe-runtime/         PID files/logs for manually-run services (processes.json committed)
```

---

## 3. Architecture

```
┌────────────────────────────── Browser (Vite, port 3000 / preview 4173) ──────────────────────────────┐
│ React 19 SPA · Leaflet 1.9 · Tailwind v4 · no router — App.tsx state-tab switching                    │
│ Navbar persona switcher → loginToBackend() builds credentials → JWT in localStorage                  │
│ services/api.ts → fetchWithTimeout(/api/*)  · authGet/authFetch attach `Authorization: Bearer`        │
└──────────────────────────────────────┬───────────────────────────────────────────────────────────────┘
                                       │ /api (dev proxy or preview proxy → 127.0.0.1:8000; VITE_API_BASE_URL)
┌──────────────────────────────────────▼──── FastAPI (uvicorn :8000) ──────────────────────────────────┐
│ main.py (NammaSafe core, in-memory SEED store DATA)            integration_routes.py (router /api)   │
│  · auth (JWT HS256) / access_control (RBAC)                    · weather/grid, weather/{lat}/{lng}    │
│  · geography, risk-alerts, accommodations, assignments         · weather/{lat}/{lng}/historical       │
│  · habitations, relocation-sites, recommendations              · rainfall, terrain, elevation         │
│  · field-reports, calculate-priority, simulate-relocation      · flood-risk grid/point, nearby       │
│  · evacuation planning (local A*)                              · habitations/dynamic, geocode          │
│  · flood-forecast, data-status, historical/kerala/*            · bhuvan/* (geocode, hosp, lulc, geoid) │
│  · dashboard-summary, map-layers                               · routes/safe, disaster-events         │
│                                                                · data-catalog, risk-assessment,      │
│                       service modules: weather_service, weather_platform, historical_weather,        │
│                       terrain_service, nasa_elevation_client, rainfall_service, flood_service,        │
│                       flood_forecast, flood_risk_overlay, risk_assessment_service, risk_engine,      │
│                       routing_service, route_planner, road_network, safe_location_service,           │
│                       nearby_places, geocode_service, bhuvan_service, disaster_events, data_catalog, │
│                       cache (TTLCache), http_client (httpx)                                          │
├────────────────────────────── Database ─────────────────────────────────────────────────────────────┤
│ SQLite default (nammasafe-ai/backend/nammasafe.db)  OR  Postgres/PostGIS via DATABASE_URL (compose)  │
│  · users, habitations, hazard_events, red_zones, relocation_sites, relocation_recommendations,        │
│    field_reports (ORM models exist but core demo data is served from in-memory SEED, not these tables)│
│  · historical_hazard_observations (Kerala, imported) · disaster_events (curated)                      │
│  · terrain_samples (SRTM cache) · historical_weather_samples (ERA5 cache) · census_villages · admin_boundaries │
└──────────────────────────────────────┬───────────────────────────────────────────────────────────────┘
    External providers (all server-side, python3 venv):
    NASA LP DAAC Earthdata (SRTMGL1.003 zips + JWT) │ Open-Meteo /archive (ERA5) │ Open-Meteo + ECMWF-IFS0.25 (live, off by default)
    IMD Mausam (opt-in, off) │ Copernicus CDS / GloFAS (needs creds + NetCDF) │ NASA GPM/GES-DISC (needs tiles) │
    Overpass OSM │ Nominatim │ Bhuvan ISRO (token/key) │ OSRM (opt-in; default local curated A*)
```

---

## 4. Technologies & frameworks

**Frontend** — React 19.0.1, TypeScript 5.8, Vite 6.2.3 (`@vitejs/plugin-react`, `@tailwindcss/vite` v4.1.14),
Leaflet 1.9.4, lucide-react 0.546, vitest 4.1 (11 test files). Dev server host `0.0.0.0:3000`, `DISABLE_HMR` flag
disables file-watching (agent-edit friendly). `npm run lint` is `tsc --noEmit`; **no ESLint**.

**Backend** — Python venv in `nammasafe-ai/backend/.venv`. FastAPI 0.115.6, uvicorn 0.34, SQLAlchemy 2.0.36,
Pydantic ≥2.12, PyJWT 2.10.1, passlib[bcrypt], httpx, h5py, alembic 1.14, pytest 8.3.

**No ML framework installed** (no sklearn/torch/tf/onnx in `requirements.txt`). Risk prediction is **rule-based**
(`ASSESSMENT_MODE=rule_based`); an optional `ML_MODEL_PATH` (onnx/joblib) is stubbed via `ml_model.py` (raises
`NotImplementedError` on an unsupported backend).

**Dead/duplicated frontend deps** (in `package.json`, unused in `src/`): `recharts`, `motion`, `@google/genai`,
`express`, `dotenv`, `esbuild`, `autoprefixer`. Legacy dead component: `components/weather/WeatherForecastMap.tsx`
(~40 KB, imported by nobody). Dual lockfiles: `bun.lock` and `package-lock.json` both present and both fairly recent.

---

## 5. Roles & RBAC

8 roles (`src/types/index.ts` and `backend/app/access_control.py` ROLE_PERMISSIONS):

| Role | Permissions (backend) | Iconic purpose |
|---|---|---|
| `normal_citizen` | `map.read_public`, `alert.read`, `accommodation.read`, `evacuation.read`, `weather.history.read` | Public GIS/weather read-only |
| `field_officer` | + `alert.raise` | Raise alerts, file field reports |
| `local_office` | + `accommodation.manage`, `evacuation.plan` | Manage shelters, plan evacuations |
| `sub_district_officer` | + `assignment.read`, `assignment.manage`, `evacuation.confirm` | Assignment + confirmations |
| `district_officer` | (same as sub-district) | District view |
| `state_officer` | (same) | State view |
| `gis_analysis_officer` | + `hazard-history.read`, `analytics.read` | GIS analytics |
| `admin` | everything + `role.manage`, `session-log.read`, `system-health.read`, `technical-data.repair` | Super-user |

Additional backend-only gates: `access_control.can_manage_role()` (officer grade hierarchy for role management),
`scope_contains()` (jurisdiction containment — admin can skip scope, others must select
state/district/sub-district/area within their assignment before login), and voter-based gating:
`calculate-priority` requires `local_office`+; `field-reports` POST requires `field_officer`+; `admin/upload-hazard-data`
is admin-only; login requires non-admin full scope (422/403 otherwise).

**Enforcement gap (frontend-only gating):** `Sidebar.tsx` `NAV_ITEMS[].roles` decides which tabs a persona sees, and
`App.tsx` snaps an invalid active tab away — this is cosmetic. The real authority is the backend JWT+permission checks.
Because the persona switcher can pick any of the 8 demo identities before login, any tab can be reached by another role
while the backend still transmits only the data that role may read. On the map/risk pages every role calls the same
read endpoints, so the practical risk is low, but the UI gating must not be presented as a security boundary.

**Auth mechanics:** login at `/api/auth/login` issues an HS256 JWT (24 h expiry) with role claim + selected scope.
Frontend stores token in `localStorage` key `nammasafe_access_token`, auto-refreshes a stored token only if it parses
and is unexpired (`isAccessTokenExpired`), and otherwise silently re-logins as the current persona. **Demo credentials
are published in source:** `seed_data.py` creates one user per role (`admin`, `officer`, `field`, `citizen`, `local`,
`subdistrict`, `state`, `gis`); the stored `hashed_password` is the literal pattern `pbkdf2:sha256:<username>123`, and
`main.py` verifies with `split(":")[-1]` (plaintext suffix). On a failed persona login the API client falls back to a
shared `officer` identity with the same predictable pattern. **These are demo accounts only — not safe for any real
deployment.**

---

## 6. Frontend pages & features

State-tab routing (`App.tsx` `activeTab`, no react-router). 13 tabs; the sidebar also hosts a **Region Quick-Select**
(state → district → sub-district → village dropdowns) backed by the static LGD hierarchy + code-split village chunks.

| Tab | Page | Featured endpoints | Role gate (UI) |
|---|---|---|---|
| Executive Dashboard | `DashboardPage` | `/api/dashboard-summary` | officer/admin (+ admin) |
| Interactive GIS Map | `GisMapPage` | `/api/map-layers`, `/api/habitations`, `/api/terrain`, `/api/elevation` | all roles |
| Weather Map | `WeatherForecastMapPage` | `/api/weather/grid`, `/api/historical/weather/years`, `/api/weather/{lat}/{lng}/historical` | all roles |
| Risk Alerts | `RiskAlertsPage` | `/api/risk-alerts`, `/api/dashboard-summary` | all roles |
| Risk Intelligence | `RiskIntelligencePage` (838 L) | `/api/risk-assessment`, `/api/risk-zones`, `/api/safe-locations`, `/api/risks-grid`, `/api/disaster-events` | all roles |
| Habitations & Risk | `HabitationsPage` | `/api/habitations`, `/api/habitations/{id}/risk-analysis`, `/api/habitations/dynamic`, `/api/geocode` | officer-grade |
| Relocation Matrix | `PriorityPage` | `/api/calculate-priority`, `/api/habitations` | officer-grade |
| Relocation Simulator | `SimulatorPage` | `/api/simulate-relocation`, `/api/relocation-sites` | officer-grade/admin |
| Evacuation Routes | `EvacuationPlanPage` | `/api/evacuation/*` (candidates/plan/confirm/road-conditions), `/api/routes/safe`, `/api/flood-forecast` | local_office+ |
| Field Hazard Reports | `FieldReportsPage` | `/api/field-reports` (GET/POST) | field_officer+ |
| Directive Brief | `ReportsPage` (nav id `directive`) | docs-style brief | officer-grade |
| Control & Personas | `AdminPage` | `/api/assignments`, `/api/admin/sessions`, `/api/admin/system-health`, `/api/analytics/hazards` | admin |
| Specs & Formulas | `DocsPage` | (static spec prose) | officer-grade |

**Key features / components:**
- **LeafletMap** (1,287 L) — basemap switcher, red zones/habitations/sites markers, terrain & flood overlays, click
  popups. Terrain popup uses `lib/terrainPopup.ts` state machine (LOADING/RETRYING/SUCCESS/NO_DATA/PERMANENT_ERROR/CANCELLED)
  with cached-elevation-during-loading and a regression guard against a premature “unavailable” flip.
- **Weather & Hazard map** (`components/weathermap/WeatherMap.tsx`) — grid layers (temperature, precipitation, wind,
  cloud, storm) via `/api/weather/grid`, live-vs-ERA5-toggle, month timeline, provider/source panel that honestly shows
  `API NOT ADDED` when live weather is disabled, ERA5 archival chips, `viewOutsideIndia` coverage badges.
- **commandcenter/ panels** — Risk intelligence (AIExplanationPanel renders the rule-engine’s factor breakdown, no real
  model; ActiveAlertsPanel, HabitationRiskTable, RiskSummaryRow, RiskFactorBars, SafeLocationsCards, RouteIntelligence,
  EmergencyServicesRow, DataSourcesPanel).
- **Navbar** — persona switcher visible **only in dev** (hidden for production and never shown to citizens);
  profile dropdown (previously clipping — fixed in an earlier change).
- **API client (services/api.ts, 2,249 L)** — 25s request timeout (`ApiTimeoutError`), terrain-specific longer ceiling
  + single retry + in-flight dedupe + bounded backoff, cache-first for grids/terrain, endpoint-safe error mapping.
  **Every read method ends in a fallback path using local derived/mock data** when the backend is unreachable (see §13).

---

## 7. Backend services & API endpoint inventory

### 7.1 Services (backend/app)

| Module | Status | What it does |
|---|---|---|
| `main.py` | LIVE (core) | App + all NammaSafe routes over in-memory `DATA = get_processed_seed_data()` |
| `auth.py` | CONFIGURED | JWT create/decode, `require_roles`, `require_permissions`, `get_current_user` |
| `access_control.py` | CONFIGURED | Permission matrix, scope containment, role-management authority |
| `config.py` | CONFIGURED | Every env key with defaults (see §12) |
| `seed_data.py` | MOCK/DEMO | 8 demo users + curated pilot habitations/sites/alerts/events/road graph |
| `integration_routes.py` | CONFIGURED | Live-intelligence router; `weather_access` = `weather.history.read` (all roles) |
| `weather_service.py` | LIVE (Open-Meteo → ECMWF backup), IMD opt-in | Live weather provider chain; honest `UNAVAILABLE`; India-bounded grid |
| `weather_platform.py` | CONFIGURED | Provider registry; `live_weather_enabled()` gate (`WEATHER_LIVE_ENABLED`) |
| `historical_weather.py` | LIVE (real ERA5 archive) | Completed-month-only ERA5 reanalysis; grid/point; DB + in-proc caches |
| `historical_data.py` / `historical_baseline.py` | LIVE (imported rows only) | Kerala CSV-derived observations + percentiles/quality |
| `historical_importer.py` | CONFIGURED | Idempotent import/upsert validation |
| `kerala_districts.py` | STATIC | Official 14-district Kerala code/name/centroid table |
| `terrain_service.py` | LIVE (NASA SRTM primary; Open-Meteo fallback off by default) | SRTM elevation/slope, DB cache (terrain_samples), grid w/ 45 s deadline |
| `nasa_elevation_client.py` | LIVE | SRTMGL1 tile download/parse, bilinear elevation, Horn’s-method slope |
| `http_client.py` | CONFIGURED | httpx GET w/ retry, redirect-safe token stripping |
| `rainfall_service.py` | NOT CONFIGURED (GPM_MODE off) | IMERG HDF5 tile extraction (needs staged tile) |
| `flood_service.py` | NOT CONFIGURED (no GloFAS dataset) | NetCDF point extraction; contains a bare `pass` placeholder |
| `flood_forecast.py` | NOT CONFIGURED | GloFAS forecast adapter; `FORECAST` only when configured+in-region |
| `flood_risk_overlay.py` | LIVE (CALCULATED) | Rule-based flood susceptibility from weather+terrain |
| `disaster_events.py` | LIVE (curated, DB-backed) | Real documented events list/near, labelled HISTORICAL |
| `risk_engine.py` | LIVE (deterministic) | hazard/vulnerability/priority/suitability/carrying-capacity/simulate functions |
| `risk_assessment_service.py` | LIVE (rule-based) | Weighted factor scoring, renormalisation, risk bands, disaster-type inference |
| `ml_model.py` | NOT CONFIGURED | `NotImplementedError` abstract loader (future ML) |
| `routing_service.py` | LIVE (OSRM)/CONFIGURED | Provider chain with `local` A* default; `osrm` optional |
| `route_planner.py` | LIVE | Evacuation planning (hazard-weighted A*, corridor closures, persistence) |
| `road_network.py` | CURATED DEMO | Pilot curated road graph (NH-07 + feeders), labelled `curated_demo` |
| `safe_location_service.py` | LIVE engine / CURATED candidates | Ranks safe sites, excludes risk bands, `REAL`/`ESTIMATE` grading, `UNKNOWN` risk honesty |
| `nearby_places.py` | LIVE (Overpass) | Nearby hospitals/shelters/etc; supports `villages` for dynamic habitations |
| `geocode_service.py` | LIVE (Nominatim) | Forward/reverse geocode; census resolution delegates to Bhuvan |
| `bhuvan_service.py` | CONFIGURED-BUT-DISABLED unless token/key set | Village geocode, reverse geocode, hospitals, LULC 50k/250k, shortest path, CartoDEM geoid |
| `data_catalog.py` | LIVE | Runtime manifest of real datasets + configured/missing status |
| `cache.py` | CONFIGURED | Thread-safe TTL cache used by every live provider |
| `geo.py` | LIVE | Haversine / point-in-polygon / bbox helpers |
| `database.py` | CONFIGURED | SQLAlchemy engine/session (SQLite or Postgres) |
| `models.py` | CONFIGURED | ORM tables (see §8) |
| `schemas.py` | CONFIGURED | Pydantic models for all payloads |

### 7.2 API endpoints (complete inventory)

**Core app (`main.py`)**

| Method+Path | Auth gate | Status class |
|---|---|---|
| `GET /health` · `GET /` | public | LIVE (healthchecks) |
| `POST /api/auth/login` | public | LIVE (demo creds) |
| `GET /api/geography/states` / `districts` / `sub-districts` / `areas` | public | DEMO (seed hierarchy) |
| `GET /api/risk-alerts` | public (published only) | DEMO |
| `POST /api/risk-alerts` | `alert.raise` | DEMO storage |
| `POST /api/risk-alerts/{id}/publish` | `accommodation.manage` | DEMO storage |
| `POST /api/accommodations` | `accommodation.manage` | DEMO |
| `GET/POST /api/assignments` | `assignment.read` / `assignment.manage` | DEMO |
| `GET /api/analytics/hazards` | `analytics.read` | DEMO (seed events) |
| `GET /api/admin/sessions` · `GET /api/admin/system-health` | `session-log.read` / `system-health.read` | DEMO |
| `GET /api/dashboard-summary` | public | DEMO + CURATED Chamoli |
| `GET /api/map-layers` | public | DEMO (SIMULATED labels) |
| `GET /api/habitations` · `/{id}` · `/{id}/risk-analysis` | public | DEMO (curated seeds) |
| `GET /api/relocation-sites` · `/{id}` | public | DEMO |
| `GET /api/relocation-recommendations` | public | DEMO |
| `GET/POST /api/field-reports` | GET public; POST `field_officer`+ | DEMO (fallback image URL) |
| `POST /api/calculate-priority` | `local_office`+ | LIVE (formulas) |
| `POST /api/simulate-relocation` | public | LIVE (engine) |
| `POST /api/admin/upload-hazard-data` | `admin` | MOCK (simulated response) |
| `GET /api/evacuation/candidates` · `POST /api/evacuation/plan` | `evacuation.plan` | LIVE (local A*) |
| `GET /api/evacuation/routes/{id}` | `evacuation.read` | LIVE |
| `POST /api/evacuation/routes/{id}/confirm` | `evacuation.confirm` | LIVE (+“dest became unsafe” guard) |
| `GET /api/evacuation/road-conditions` | `evacuation.read` | CURATED DEMO |
| `GET /api/flood-forecast` | `evacuation.read` | NOT CONFIGURED (no GloFAS) |
| `GET /api/data-status` | `map.read_public` | LIVE (status report) |
| `GET /api/historical/availability` | public | HISTORICAL / NOT CONFIGURED |
| `GET /api/historical/kerala` · `/{district}` · `/{district}/baseline` · `/{district}/compare` | public | HISTORICAL (if imported) / NOT CONFIGURED |

**SAFE_MOVE_AI router (`integration_routes.py`, prefix `/api`; all `map.read_public` unless noted)**

| Method+Path | Data class |
|---|---|
| `GET /api/weather/grid` | LIVE (weather) or HISTORICAL (ERA5) |
| `GET /api/weather/forecast` · `GET /api/weather/{lat}/{lng}` | LIVE if `WEATHER_LIVE_ENABLED`, else `API_NOT_ADDED` |
| `GET /api/weather/{lat}/{lng}/historical` | HISTORICAL (ERA5, completed months) |
| `GET /api/historical/weather/years` | HISTORICAL status report |
| `GET /api/rainfall/{lat}/{lng}` · `GET /api/rainfall-grid` | NOT CONFIGURED (GPM off) |
| `GET /api/terrain-grid` | LIVE (SRTM) |
| `GET /api/terrain/{lat}/{lng}` · `GET /api/elevation` | LIVE (SRTM) |
| `GET /api/flood-risk-grid` · `GET /api/flood-risk/{lat}/{lng}` | CALCULATED rule overlay (ERA5/SRTM inputs) |
| `GET /api/nearby/{kind}` | LIVE (Overpass) |
| `GET /api/habitations/dynamic` | LIVE (OSM-derived, no fabricated scores) |
| `GET /api/geocode` | LIVE (Nominatim) |
| `GET /api/bhuvan/village/geocode` · `reverse-geocode` · `hospitals` · `lulc` · `lulc/aoi` · `lulc/50k` · `lulc/50k/aoi` · `geoid` | AVAILABLE if token/key set else UNAVAILABLE |
| `POST /api/bhuvan/shortest-path` | `evacuation.read`; AVAILABLE if token set |
| `GET /api/routes/safe` | `evacuation.read`; LIVE (local graph) |
| `GET /api/disaster-events` · `near` | HISTORICAL (curated DB rows) |
| `GET /api/data-catalog` | LIVE status |
| `GET /api/risk-assessment` · `POST /api/risk-assessment/recalculate` | CALCULATED rule-based |
| `GET /api/risk-zones` | CALCULATED |
| `GET /api/safe-locations` | CALCULATED / CURATED |

---

## 8. Database

- **Default:** SQLite at `nammasafe-ai/backend/nammasafe.db` (2,555,904 B). **Production switch:** `DATABASE_URL` →
  Postgres/PostGIS (`postgis/postgis:15-3.3` in docker-compose; ORM models and migrations are PostGIS-compatible).
- **Key architectural fact:** the **core NammaSafe business data is NOT in the database** — it is loaded once into
  process memory from `seed_data.get_processed_seed_data()` (users, habitations, red zones, relocation sites,
  recommendations, alerts, hazard events, field reports, road graph). The ORM tables for these entities exist and
  migrate, but the live app serves seeds; writes mutate the in-memory dict and are lost on restart. This is the
  project’s single biggest production gap (§14, §19).
- **Tables actually used by the DB:** `terrain_samples` (SRTM cache, unique per grid cell+source), `historical_weather_samples`
  (ERA5 cache, unique per cell/year/month/day/variable/aggregation), `historical_hazard_observations` (Kerala imports,
  unique per district/date/year/source), `disaster_events` (curated), `census_villages` (2011, idempotent per
  village_code+year), `admin_boundaries` (imported shapefiles), plus the model-only group above.
- `Base.metadata.create_all()` runs at startup (SQLite path); Alembic has 7 migrations (001 initial → 007
  historical-weather per-day) for the production/Postgres path.
- Indexes exist on key columns; `terrain_samples(latitude, longitude)` and source; `historical_weather_samples`
  (lat/lng/year/month/day) and (year, month).
- **Row contents on this machine are runtime-visible** via `GET /api/data-catalog` (live counts); the DB caches only
  fill when the corresponding live provider is actually used (terrain/ERA5).
- Root-level `nammasafe.db` (0 bytes) is a **stray file** (likely from an early CWD-dependent launch); the backend
  config was made CWD-immune to prevent recurrence.

---

## 9. Terrain / Elevation (NASA SRTM)

- **Primary provider (LIVE on this box):** NASA LP DAAC Earthdata Cloud **SRTMGL1.003** (1 arc-second ~30 m DEM).
  Token resolved in order: `NASA_EARTHDATA_TOKEN` env → `EARTHDATA_TOKEN` → local `apikeynasa.env*` file; the local
  `apikeynasa.env.env` holds a NASA JWT (gitignored, value not disclosed here). Server-side only; the token is stripped
  on cross-origin redirects (`http_client._get_follow_redirects`).
- Elevation = bilinear interpolation on the real HGT grid (`_parse_hgt`, signed 16-bit big-endian, void=-32768).
  Slope = Horn’s method over a real ≤3-arc-second (~90 m) DEM window; slope categories
  `NEARLY_LEVEL ≤3% < GENTLY_SLOPING ≤8% < MODERATELY_SLOPING ≤15% < STEEP ≤30% < VERY_STEEP`.
- Two API surfaces: `/api/elevation` (fast single value, no slope window) and `/api/terrain` (full slope/drainage).
  Grid endpoint `/api/terrain-grid` samples the India box (clamped 6–37.4 N, 68–98.5 E), parallel workers
  (`TERRAIN_GRID_WORKERS=8`), overall 45 s deadline, per-cell honest `UNAVAILABLE` beyond deadline; `pool.shutdown(wait=False)`.
- Caching: in-process TTL + DB table `terrain_samples` (only validated LIVE NASA payloads are stored; grid cells ≈55 m).
- **Fallback:** Open-Meteo elevation is `NASA_TERRAIN_FALLBACK_OPENMETEO=off` by default — off = NASA failure is
  honestly `UNAVAILABLE`/`NOT_CONFIGURED`, never substituted. Falls back only when explicitly `on` (payloads labelled `fallback`).
- Tile zips are ~26 MB each, cached up to `NASA_SRTM_MAX_TILES` (16 by default). A real tile download can take 15–30 s,
  which the frontend accommodates with a longer terrain request ceiling + retry.

---

## 10. Weather system

**Provider registry** (`weather_platform.py`, config-driven):

| Provider | Kind | Key? | Enabled by default |
|---|---|---|---|
| Open-Meteo (ECMWF HRES/GFS) | live | none | **off** (`WEATHER_LIVE_ENABLED` default `off`) |
| ECMWF via Open-Meteo IFS 0.25° | live backup | none | **off** (same gate) |
| IMD Mausam Current Weather | live legacy | token | off (only when base URL + token both set) |
| Open-Meteo ERA5 Archive (ECMWF reanalysis) | historical | none | **on** — this is what the map actually serves |

- **Live weather is DISABLED by default.** `weather_api_status()` returns `API_NOT_ADDED` until the operator flips
  `WEATHER_LIVE_ENABLED=on`. The UI ribbon + source panel display this honestly; nothing is fabricated. `.env.example`
  does not even list `WEATHER_LIVE_ENABLED` (it is a `config.py` env var) — worth documenting for operators.
- **Historical weather is enabled by default and needs no key** — completed months of real ERA5 daily reanalysis via
  `archive-api.open-meteo.com`. `available_periods()` returns year 2022–2026 (config `HISTORICAL_YEAR_MIN/MAX`);
  only completed months are ever served (current month honestly `UNAVAILABLE`). Cache in `historical_weather_samples`
  DB table; per-day supports `day=1..N`.
- Grid source panel shows `prefer=ecmwf` option (weather & hazard map requests ECMWF first). Grid variables include
  temperature_2m, precipitation, precipitation_probability, wind_speed_10m, gusts, cloud_cover, pressure, humidity,
  wind direction/U/V, apparent temp, visibility, `storm_indicator`. Max grid points 600, batch 200 per upstream call,
  max 2 concurrent, provider cooldown 30 s honoring `Retry-After`.
- Timeouts/TTLs: success cache 600 s (grid), failure cache 30 s, point forecast 1–7 days (`WEATHER_FORECAST_DAYS`).

---

## 11. Maps, GIS, evacuation, hazards, risk, villages/census, accommodation

- **Basemaps:** Leaflet with free tiles; optional Google Maps basemap via `VITE_GOOGLE_MAPS_API_KEY` (blank by
  default → Esri/OSM tiles). No key present in the bundle. `MapLayerPanel` toggles red-zone/habitation/site layers +
  hazard sub-toggles; flood & rainfall toggles.
- **Evacuation/routing:** default provider **`local`** = curated pilot road graph (NH-07 + feedeers) with risk-aware A*
  (weights in `config.RISK_WEIGHTS`, e.g. landslide 5.0, flood 6.0, bridge 1.5); OSRM available via `ROUTING_PROVIDER`.
  `route_planner` enforces origin scope, ranks ≤5 candidate sites, writes audit trail; confirm refuses when the
  destination entered a critical red zone. `road-conditions` endpoint labels segments `OPEN/RESTRICTED/CLOSED`,
  `data_class: curated_demo`, `is_synthetic: true` (honest).
- **Risk engine:** transparent rule-based weights (`RISK_ASSESSMENT_WEIGHTS`), bands LOW ≤30 / MEDIUM ≤60 / HIGH ≤80 /
  CRITICAL ≤100; renormalises over present factors so missing signals never deflate; `UNKNOWN` when inputs insufficient.
  `risk-zones` runs assessment per habitation/grid and labels zones “AI-Assessed” from the rule engine (mode
  `rule_based`). Bhuvan LULC/geoid factors only when `BHUVAN_RISK_FACTOR=on`.
- **Villages/census:** two very different datasets —
  1. **Static frontend LGD reference:** `src/data/regions/villages/*.ts` — 36 code-split chunks, **6,871 villages as
     `[code, name]` pairs only** (no coordinates/population). Generated by `scripts/build-regions.mjs` from the
     committed `scripts/.cache/lgd` HTTP cache. Used for the sidebar state→district→sub-district→village drill-down
     and a hardcoded 36-state centroid table in `lib/regionViewport.ts`.
  2. **Real Census 2011:** importable into `census_villages` from official CSVs — **not imported here** (the only CSV on
     disk is `scripts/.cache/mirror/4-village.csv`, a 133-byte Git-LFS pointer for a ~62 MB payload that is **absent**,
     so census import cannot run locally).
- **Habitations:** pilot “curated” seed set (Chamoli) served from memory and genuinely used; for any other India
  location `/api/habitations/dynamic` returns OSM-derived villages with **no curated scores** (0s + explicit
  `is_dynamic_osm` labels) — honest empty for non-pilot regions (tested by `test_multi_state.py`).
- **Relocation/accommodation:** relocation sites with carrying-capacity factors (land/water/school/health/road →
  `final_capacity`), suitability scoring, `simulate_safeshift` capacity-check with bottleneck factor + alternative-site
  logic. `POST /api/accommodations` creates sites (default 80 scores), all in-memory.
- **Field hazards:** reports typed by hazard (crack, landslide, flash flood…), verification auto-set by role rank;
  fallback Unsplash image URL if none supplied.

---

## 12. Environment variables (names only — values intentionally omitted)

Backend (`config.py`, `backend/.env`, `nammasafe-ai/.env` …): grouping for clarity.

- **DB/token:** `DATABASE_URL`, `JWT_SECRET` *(hardcoded default committed in `config.py` and docker-compose —
  [SECRET PRESENT — VALUE NOT SHOWN])*, `JWT_ALGORITHM`, `JWT_EXPIRATION_MINUTES`
- **Pilot:** `PILOT_DISTRICT`, `PILOT_STATE`, and hardcoded `PILOT_CENTER_LAT/LNG` (30.40, 79.33)
- **Historical (previous-year):** `HISTORICAL_DATA_YEAR`, `HISTORICAL_MAX_RAINFALL_MM`, `HISTORICAL_MIN_PERCENTILE_OBS`
- **Routing/evacuation:** `ROUTING_PROVIDER`, `ROUTE_MAX_SEARCH_KM`, `ROUTE_SNAP_M`, `ROUTE_SNAP_FALLBACK_M`,
  `EVACUATION_CACHE_TTL_MIN`, `EVACUATION_WALK_SPEED_KMH`, `MAX_CANDIDATE_ROUTES`
- **Maps:** `GOOGLE_MAPS_API_KEY` (backend), `VITE_GOOGLE_MAPS_API_KEY` (frontend; blank → free tiles)
- **Live weather:** `OPEN_METEO_BASE_URL`, `ECMWF_BASE_URL`, `WEATHER_LIVE_ENABLED`, `WEATHER_CACHE_TTL_SEC`,
  `WEATHER_TIMEOUT_SEC`, `WEATHER_FORECAST_DAYS`, `WEATHER_GRID_MAX_POINTS`, `WEATHER_GRID_STEP`,
  `WEATHER_GRID_CACHE_TTL_SEC`, `WEATHER_PREFERRED_PROVIDER`, `WEATHER_BATCH_SIZE`, `WEATHER_PROVIDER_COOLDOWN_SEC`,
  `WEATHER_MAX_CONCURRENT`, `WEATHER_FAILURE_CACHE_TTL_SEC`
- **Historical weather:** `HISTORICAL_WEATHER_BASE_URL`, `HISTORICAL_WEATHER_TIMEOUT_SEC`, `HISTORICAL_YEAR_MIN`,
  `HISTORICAL_YEAR_MAX`, `HISTORICAL_WEATHER_CACHE_TTL_SEC`, `HISTORICAL_WEATHER_BATCH`,
  `HISTORICAL_WEATHER_COOLDOWN_SEC`, `HISTORICAL_WEATHER_MAX_CONCURRENT`, `HISTORICAL_WEATHER_DB_CACHE`
- **IMD legacy:** `IMD_MAUSAM_BASE_URL`, `IMD_MAUSAM_TOKEN`, `IMD_MAUSAM_TIMEOUT_SEC`
- **Terrain:** `TERRAIN_CACHE_TTL_SEC`, `TERRAIN_GRID_SAMPLES`, `TERRAIN_SAMPLE_KM`, `TERRAIN_GRID_WORKERS`,
  `TERRAIN_GRID_TIMEOUT_SEC`, `NASA_TERRAIN_SAMPLE_ARCSEC`, `TERRAIN_DB_CACHE`, `NASA_TERRAIN_FALLBACK_OPENMETEO`
- **NASA Earthdata:** `NASA_EARTHDATA_TOKEN`, `EARTHDATA_TOKEN`, `EARTHDATA_USERNAME`,
  `NASA_SRTM_LPDAAC_URL_TEMPLATE`, `NASA_SRTM_TIMEOUT_SEC`, `NASA_SRTM_MAX_TILES`
- **Flood/GloFAS:** `CDS_API_URL`, `CDS_API_KEY`, `CDS_API_SECRET`, `GLOFAS_DATASET_PATH`, `GLOPAS_DATA_DIR`,
  `GLOPAS_DATASET`, `FLOOD_CACHE_TTL_SEC`
- **GPM rainfall:** `GPM_MODE`, `GPM_DATA_DIR`, `RAINFALL_CACHE_TTL_SEC`
- **Bhuvan/ISRO:** `BHUVAN_API_BASE_URL`, `BHUVAN_API_TOKEN`, `BHUVAN_API_KEY`, `BHUVAN_TIMEOUT_SEC`,
  `BHUVAN_CACHE_TTL_SEC`, `BHUVAN_GEOCODE_TTL_SEC`, `BHUVAN_RISK_FACTOR`
- **OSM:** `OVERPASS_API_URL`, `OVERPASS_MIN_INTERVAL_SEC`, `NEARBY_RADIUS_KM_DEFAULT`, `NEARBY_CACHE_TTL_SEC`,
  `NOMINATIM_BASE_URL`, `GEOCODE_CACHE_TTL_SEC`, `GEOCODE_MIN_INTERVAL_SEC`, `OSM_USER_AGENT`
- **Routing upstream:** `OSRM_BASE_URL`, `ROUTER_CACHE_TTL_SEC`
- **Risk engine:** `RISK_ASSESSMENT_WEIGHTS`, `ASSESSMENT_MODE`, `ML_MODEL_PATH`, `HISTORICAL_EVENT_RADIUS_KM`,
  `FIELD_REPORT_RADIUS_KM`
- **Frontend:** `VITE_API_BASE_URL`, `DISABLE_HMR` (dev only). There are **no `import.meta.env.VITE_*` reads in `src/`**;
  the .env.example Gemini/APP_URL keys are AI-Studio template leftovers (unused).

---

## 13. Feature status matrix (LIVE / PARTIAL / BROKEN / MOCKED / NOT CONFIGURED)

| Feature | Status | Evidence |
|---|---|---|
| Core NammaSafe portal (dashboard, habitations, sites, alerts, reports, simulate) | **LIVE but DEMO data** | in-memory seed; writes lost on restart |
| Auth / RBAC JWT login | **MOCK (demo credentials published)** | `seed_data` + plaintext-suffix passwords; OK for demo |
| Terrain elevation + slope (NASA SRTM) | **LIVE** | real tile fetch; verified by E2E probe (11/11 incl. regression guards) |
| Historical weather (ERA5) | **LIVE** | completed-month only; enabled by default |
| Live weather (Open-Meteo → ECMWF) | **NOT CONFIGURED (off)** | `WEATHER_LIVE_ENABLED=off` → `API_NOT_ADDED` |
| IMD Mausam | NOT CONFIGURED | needs URL+token |
| Rainfall (NASA GPM IMERG) | **NOT CONFIGURED** | `GPM_MODE=off`, no tiles |
| Flood forecast (GloFAS / CDS) | **NOT CONFIGURED** | no creds/dataset; returns honest NOT_CONFIGURED |
| Flood-risk overlay (rule-based) | **LIVE (CALCULATED)** | from ERA5 + SRTM real inputs |
| Discrete flood/gauges | NOT CONFIGURED | same GloFAS gap |
| Nearby places / dynamic habitations (Overpass) | **LIVE when reachable** | else UNAVAILABLE |
| Geocode (Nominatim) | **LIVE when reachable** | else UNAVAILABLE |
| Bhuvan / ISRO layers | **CONFIGURED-BUT-DISABLED** (token/key not set here) | UI footer even says “Syncing with Bhuvan Satellite (Simulated)” |
| Evacuation routing | **LIVE (local curated A* DEMO)** | real algorithm on curated graph; labelled curated_demo |
| OSRM routing | NOT CONFIGURED (optional) | default `local` |
| Risk assessment / risk zones / safe locations | **LIVE (rule-based)** | deterministic, honest UNKNOWN; world is real inputs |
| Historical Kerala rainfall | **NOT CONFIGURED** (no import) | UI shows NOT-CONFIGURED banner until CSV imported |
| Disaster events (curated) | **HISTORICAL/CURATED** (DB rows, if seeded) | `seed_disaster_events.py` |
| Census 2011 villages | **NOT IMPORTED** | CSV payload missing (LFS pointer only) |
| Admin boundaries | **NOT IMPORTED** | import script exists, no supply file |
| Admin upload-hazard-data | **MOCK** | simulated success, no real ingestion |
| Frontend read fallbacks | **MOCK fallback** | `api.ts` derives a Chamoli dashboard summary labelled `data_status:'SIMULATED'` with `is_synthetic_demo_data:false` when backend unreachable (documented caveat) |
| README packaging | **BROKEN state on disk** | contains literal `<<<<<<< HEAD` conflict markers |

---

## 14. Known errors & likely causes

1. **Unresolved merge conflict in README.md** (lines ~1/54/56, `<<<<<<< HEAD … >>>>>>> 8e8016d4…`). Cause: a merge
   (`8bccf5c Merge GitHub repository…`) was committed without resolving README. Fix: resolve and commit.
2. **Demo credentials published + predictable passwords + token in localStorage.** Cause: design for a persona demo;
   the fallback `officer` login lives in the shipped client bundle. Risk: any XSS can exfiltrate the JWT; anyone can
   log in as any role. Required fix for any deploy (env-based creds + real hashing).
3. **Hardcoded `JWT_SECRET` default** in `config.py` and `docker-compose.yml` (compose also sets a static DB password).
   Cause: pilot convenience. Risk: forged tokens if attacker knows the default. Must be env-injected in production.
4. **Core data lost on restart** — in-memory seed store + fake writes. Cause: demo scope. Symptom: no persistence of
   newly raised alerts/accommodations/sessions.
5. **`apikeynasa.env.env` contains a live NASA JWT** on disk (gitignored, good) — it is a real credential and must be
   rotated if the repo is ever shared; also it may expire (~60-day tokens).
6. **Per-call silent auth failure** — the API client treats login failure as “use demo/officer fallback”, so a broken
   backend yields pages that look populated (mock summary) instead of erroring (see §13 mock caveat).
7. **Dead code paths** — `WeatherForecastMap.tsx` (unused ~40 KB), `ml_model.py`/`routing.py` `NotImplementedError`
   placeholders, `flood_service.py:38` and `flood_forecast.py:230` bare `pass` placeholders. Not failures today; they are
   incomplete-implementation markers.
8. **CORS `allow_origins=["*"]` with `allow_credentials=True`** — permissive; browsers reject credentialed wildcard
   CORS in practice and it weakens origin policy when credentials are used.
9. **Stray root `nammasafe.db`** (0 bytes) + **`processes.json` committed** in `.nammasafe-runtime/` (PID file = machine
   noise that will churn the git index).
10. **E2E “honest error” probe mismatch** — the preview/`p_e2e_prod` check that expects a down-backend banner fails when
    the dev backend is actually up behind the preview proxy (`live:true, banner:false, loading:false` is the correct,
    healthy outcome; the probe mis-assumes unreachable backend).

Candidate *likely causes are consistent with the code*; none were reproduced for this audit beyond the static
inspection above (a prior E2E run verified terrain, weather, roles, and theme flows green).

---

## 15. Performance issues

- **Repo/blame weight:** 1,827 tracked files, of which **1,605 (~88%) are `scripts/.cache/lgd`** HTTP-cache response
  files committed to git — large clones, slow `git status`, noisy diffs. Consider untracking (keep `scripts/` generated
  artifacts out of VCS) and rebuild via `build-regions.mjs`.
- **`tsc --noEmit` as “lint”:** a 716k-line `src/` (94% = village chunks) makes typecheck slow; no ESLint for quick feedback.
- **Frontend bundle:** 6,871 village records are code-split per-state (good), but the inlined `hierarchy.ts` is large
  (15k+ lines); `WeatherMap`/`LeafletMap` are heavyweight but acceptable.
- **Terrain grid:** can fan out 8 parallel ~26 MB tile downloads; bounded by the 45 s deadline and `UNAVAILABLE` beyond —
  still the slowest endpoint. Per-cell DB caching mitigates repeats.
- **Sqlite single-writer** + in-memory authoritative store means horizontal scaling is off the table until persistence
  moves to Postgres/PostGIS (already provisioned via compose).
- Client 25 s timeout guards loops; grid fetch bounded (≤600 points, batch 200, concurrency 2) to respect free-tier
  rate limits.

---

## 16. Deployment requirements & production dependencies

- **Backend:** `python3` venv + `requirements.txt` (fastapi, uvicorn, sqlalchemy, alembic, pyjwt, passlib, httpx, h5py…).
  `uvicorn app.main:app` on :8000. Runs `Base.metadata.create_all` at startup. `/health` used by container healthcheck.
- **Frontend:** Node + npm, `npm install`, `npm run dev` (:3000, optional `DISABLE_HMR=true`), `vite build` +
  preview (:4173) proxying `/api` → 8000; or `Dockerfile.frontend` + compose.
- **Docker stack (production-shaped):** `docker-compose.yml` → `postgis/postgis:15-3.3` (db :5432),
  backend (:8000), frontend (:3000) on one bridge network; `DATABASE_URL` must switch to Postgres and **secrets must be
  injected (JWT secret, DB password, NASA token, Bhuvan key) — never the committed defaults**.
- **To actually enable live intelligence:**
  - Live weather → `WEATHER_LIVE_ENABLED=on` (no key for Open-Meteo);
  - Terrain → NASA Earthdata JWT (already local via `apikeynasa.env.env`);
  - Flood → create CDS account, set `CDS_API_KEY/SECRET`, download GloFAS NetCDF via `scripts/fetch_glofas_data.py`;
  - Rainfall → ingest IMERG tile via `scripts/fetch_gpm_data.py`, set `GPM_MODE=on`, `GPM_DATA_DIR`;
  - Bhuvan → obtain portal tokens, set `BHUVAN_API_TOKEN`/`BHUVAN_API_KEY` in `backend/.env`.
- **Data pipelines (scripts):** `build-regions.mjs` (frontend chunks), `fetch_glofas_data.py`, `fetch_gpm_data.py`,
  `import_admin_boundaries.py`, `import_census_2011.py`, `import_historical_data.py` (Kerala CSV),
  `import_historical_weather.py` (ERA5 samples CSV), `seed_disaster_events.py` — all idempotent, most with `--dry-run`.
- **25 backend test files** (weather/terrain/flood/energy/RBAC/historical/evacuation/NASA-client/Bhuvan/multi-state)
  run under pytest with stubbed HTTP + in-memory SQLite. Frontend has 11 vitest files (api client times/terrain/weather
  layers/popup states/Navbar persona gating/etc.). `npm run lint` = `tsc --noEmit`.

---

## 17. Git / GitHub / Git LFS status

- **Repo:** `git` at repo root, branch `main`, remote `origin = https://github.com/monish-arc/final-project-.git`.
  History (3 commits): `8a70104 Initial commit` → `7dc8a72 Save current SafeMove AI project state` →
  `8bccf5c Merge GitHub repository with current SafeMove AI project` (HEAD; the merge that left README conflicted).
  **Working tree is clean.**
- **Tracked inventory:** 1,827 files; **1,605 under `scripts/.cache/lgd`** (committed cache — see §15);
  `.nammasafe-runtime/processes.json` committed (machine-specific PID); `bun.lock` and `package-lock.json` both present
  (dual-lockfile ambiguity; decide one).
- **Gitignore:** `apikeynasa.env.*` ignored (line 12) ✓; `nammasafe-ai/backend/nammasafe.db`, `.venv`, `node_modules`,
  `dist` covered by ignore rules.
- **Git LFS:** `.gitattributes` routes `scripts/.cache/mirror/4-village.csv` through LFS; the on-disk file is a
  **133-byte LFS pointer declaring a 65,310,419-byte payload (~62.3 MB) that is absent** (no `git lfs pull`, no object
  on disk) — census geo data cannot be imported on this machine until the LFS object is fetched.
- No other LFS rules; `4-village.csv` is untracked (the pointer is only an ignore-rule candidate).

---

## 18. Important datasets & sources

| Dataset | Source | Location | Status on disk |
|---|---|---|---|
| LGD state/district/sub-district/village tree (6,871 villages) | Census/LGD via `scripts/.cache/lgd` | `src/data/regions/*` | STATIC, bundled (name+code only) |
| Census 2011 village detail | Census of India CSV | `4-village.csv` (LFS) | NOT AVAILABLE (payload missing) |
| Chamoli pilot curated seed | hand-curated | `seed_data.py` (memory) | MOCK/CURATED |
| Road graph (NH-07 + feeders) | curated | `road_network.py` | CURATED DEMO |
| Disaster events | public records | `disaster_events` table / `seed_disaster_events.py` | HISTORICAL (curated, DB) |
| Kerala rainfall observations | India-WRIS/IMD/KSDMA CSV | `historical_hazard_observations` | NOT CONFIGURED (needs import) |
| ERA5 reanalysis | Open-Meteo archive (ECMWF) | `historical_weather_samples` + live archive | LIVE/HISTORICAL |
| Open-Meteo/ECMWF forecast | Open-Meteo | live API | NOT CONFIGURED (off) |
| NASA SRTM DEM | LP DAAC Earthdata Cloud | `terrain_samples` + live tile | LIVE (token present locally) |
| GloFAS | Copernicus CDS | NetCDF | NOT CONFIGURED |
| IMERG rainfall | NASA GES DISC | HDF5 tiles | NOT CONFIGURED |
| OSM POIs / villages | Overpass | live API | LIVE when reachable |
| Nominatim geocoding | OSM | live API | LIVE when reachable |
| Bhuvan (census geocode, LULC, CartoDEM, routing, hospitals) | ISRO Bhuvan | live API | NOT CONFIGURED (no token/key) |

---

## 19. TODOs & technical risks (prioritised)

**High**
1. Resolve README merge conflict and re-commit cleanly.
2. Persist core data (users/alerts/accommodations/field reports) to the DB; stop treating memory as storage.
3. Replace published demo credentials + hardcoded JWT default with real env secrets before any deployment (and rotate
   the on-disk NASA JWT).
4. Fetch the missing LFS object for `4-village.csv` or drop LFS; decide the canonical lockfile (npm vs bun); untrack
   `scripts/.cache/lgd` and `.nammasafe-runtime/processes.json`.
5. Enforce server-side RBAC for write flows end-to-end and remove credentials from the shipped client bundle
   (the `officer` fallback); harden login (rate-limit, no plaintext-suffix compare).

**Medium**
6. Document `WEATHER_LIVE_ENABLED` & the full `config.py` env set in `.env.example`.
7. Make `ASSESSMENT_MODE` genuinely switchable to hybrid/ML (implement `ml_model.py` backend or remove the stub).
8. Wire real GloFAS/GPM/Bhuvan data or keep them off explicitly in the shipped default.
9. Decide CORS policy (origins list, drop credentials wildcard) for production.
10. Mark frontend mock fallback more honestly (currently `data_status: SIMULATED` with `is_synthetic_demo_data: false`).

**Low**
11. Remove dead components/deps (`WeatherForecastMap`, recharts, motion, @google/genai, express, dotenv, esbuild,
    autoprefixer); add an ESLint config; delete the stray root `nammasafe.db`.
12. Unify `NOT_CONFIGURED` vs `NOT CONFIGURED` labelling across client/server.

---

## 20. Final summary of current project state

- **Identity:** a working, self-hostable **Chamoli pilot demonstration** of a disaster decision-support platform. The
  NammaSafe relocation-planning core runs on **curated demo seed data in memory** (fully navigable; 8 demo personas;
  RBAC JWT auth; relocation priority/matrix/simulator; local risk-aware evacuation routing on a curated road graph).
- **The real-data differentiator (SAFE_MOVE_AI) is genuinely live where it doesn’t need credentials:** NASA SRTM
  terrain elevation/slope (LIVE via the local Earthdata token), ERA5 historical weather (LIVE, completed months), a
  transparent rule-based flood overlay and risk engine (CALCULATED), Overpass/Nominatim (LIVE), curated disaster-event
  history (HISTORICAL). The honesty contract is consistently enforced (`LIVE`/`HISTORICAL`/`CALCULATED`/`CURATED`/
  `UNAVAILABLE`/`NOT_CONFIGURED`/`SIMULATED` labels), and the UI never fabricates provider failures.
- **Deliberately disabled until provisioned:** live Open-Meteo/ECMWF weather (`API_NOT_ADDED`), IMD, GPM rainfall,
  GloFAS flood forecast, Bhuvan/ISRO layers, OSRM, census-2011 import, Kerala historical import, admin boundaries.
- **Key gaps to close before it can be called production-ready:** no persistence (memory store), published demo
  credentials + hardcoded JWT default, committed caches (88% of tracked files) + dual lockfiles + missing LFS payload,
  README merge conflict, and an ML path that is still a stub.
- **Overall maturity:** a high-quality, test-covered (**≈36 automated test files across frontend + backend**),
  honesty-first **prototype that is green as a demo** on this machine and clearly designed for staged data-provider
  enablement — but with persistence, secrets hygiene, and repo hygiene as the three must-fix pillars for any
  real-world deployment.