# NammaSafe AI — Architecture Assessment and Target Design

**Reviewed:** 9 September 2026  
**Scope:** React frontend at the repository root and FastAPI backend in `nammasafe-ai/backend`.

## Executive summary

NammaSafe AI is a well-structured **decision-support prototype** for multi-hazard
relocation planning in Chamoli. It has a capable React GIS interface, a FastAPI
risk engine, seed data, an initial PostGIS schema, and container definitions.

The most important architectural fact is that the currently executed system is
not yet the persistent PostGIS platform described in the original technical
documentation. The backend serves an in-memory seed-data dictionary and the
frontend silently falls back to a separate browser-side mock implementation.
This can make the same user action produce different results in different
environments. The target architecture below makes the API and database the
single source of truth while retaining an explicit demo mode for presentations.

## Current implementation

```text
Browser
  │
  ├── React 19 / TypeScript / Tailwind / Leaflet / Recharts
  │     ├── App.tsx owns data loading, navigation, modal state and mutations
  │     ├── pages/ renders dashboard, GIS, priority, simulator and reports
  │     └── services/api.ts calls /api/* or silently uses mockData.ts
  │
  └── /api/*
        │
        ├── Nginx proxy in the production frontend image
        │
        └── FastAPI (nammasafe-ai/backend/app/main.py)
              ├── authentication and RBAC helpers
              ├── risk_engine.py decision formulas
              └── DATA = get_processed_seed_data()  ← process-local state

PostgreSQL/PostGIS
  ├── Docker Compose service and database/init.sql
  └── SQLAlchemy models + Alembic migration exist, but API routes do not use them
```

### Frontend responsibilities

| Area | Current location | Notes |
| --- | --- | --- |
| Application shell and orchestration | `src/App.tsx` | Owns eight data collections, loading, mutation callbacks and navigation. |
| Presentation modules | `src/pages/`, `src/components/` | Clear feature-oriented UI split. |
| Domain contracts | `src/types/index.ts` | Useful shared client contract, but it has drifted from several API responses. |
| API and demo implementation | `src/services/api.ts` | Mixes HTTP transport, authentication state, fallback data, and decision calculations. |
| Demonstration data | `src/data/mockData.ts` | Complete browser demo dataset. |

### Backend responsibilities

| Area | Current location | Notes |
| --- | --- | --- |
| HTTP routes | `nammasafe-ai/backend/app/main.py` | All endpoints are in one module. |
| Decision rules | `nammasafe-ai/backend/app/risk_engine.py` | The right location for authoritative calculations. |
| Authentication | `nammasafe-ai/backend/app/auth.py` | JWT creation and role checks are implemented. |
| Persistence definition | `models.py`, `database.py`, `alembic/`, `database/init.sql` | Defined but not part of the request path. |
| Seed data | `seed_data.py` | Currently acts as the application's database. |

## Findings

### 1. Two sources of truth

The frontend keeps mutable copies of habitations, sites, reports and
recommendations while the backend keeps another mutable copy. A browser update
can succeed locally even when the API is unavailable or rejects it. This is
especially significant for field reports and priority recalculation.

**Decision:** production mode must use the API exclusively. A demo mode may use
mock data, but it must be selected explicitly with `VITE_DATA_MODE=demo` and
visibly identified in the UI.

### 2. Risk-engine drift

The frontend and backend implement the same hazard and priority formulas, but
their vulnerability normalisation differs. The frontend caps population density
at 5,000 people and uses an unscaled dependants ratio; the backend uses a
150-person normalisation and scales the dependants ratio. This can change a
habitation's relocation classification.

**Decision:** `risk_engine.py` is authoritative. The frontend displays returned
scores and must not calculate production scores. If a client-side demo engine is
retained, it should use the exact same tested formula specification.

### 3. Contract and mutation gaps

- The API simulator returns `target_site_id`, `families_relocated`,
  `remaining_capacity_after`, and `explanation`; the frontend expects different
  names such as `relocation_site_id`, `families_requested`,
  `remaining_capacity_after_relocation`, and `decision_rationale`.
- The frontend includes report verification and reset actions, but the backend
  currently has no matching endpoints.
- Priority recalculation returns a calculation result while the React app
  assumes a complete updated `Habitation`.
- Protected backend routes require a JWT, but the current persona switcher only
  changes browser state and does not establish an API session.

**Decision:** define one versioned JSON contract, generate or share types from
the OpenAPI schema, and provide a small API client that normalises no business
data. Add the missing report-verification and demo-reset operations before
moving mutations to the backend.

### 4. Persistence is not active

Docker Compose starts PostGIS and mounts the SQL initialisation script, but
FastAPI does not call SQLAlchemy sessions or repositories. Restarting the API
loses all report and priority changes. The backend Docker build also references
`nammasafe-ai/backend/Dockerfile`, which is currently absent.

**Decision:** treat the existing PostGIS schema as a migration target, not as a
current capability. Add a backend Dockerfile and introduce repositories before
claiming durable data storage.

### 5. Deployment topology needs one canonical entry point

There are duplicate Docker Compose and frontend Dockerfiles at the root and
under `nammasafe-ai/`. They use different relative build contexts and can drift.
The Vite development server has no `/api` proxy, whereas the production Nginx
image does have one.

**Decision:** make the repository-root `docker-compose.yml` the only supported
container entry point; configure Vite's development proxy for `localhost:8000`;
and document all environment variables in the root `.env.example`.

## Target architecture

```text
                         ┌──────────────────────────┐
                         │ React application         │
                         │ pages + feature hooks     │
                         └────────────┬─────────────┘
                                      │ HTTPS / JSON
                         ┌────────────▼─────────────┐
                         │ API client               │
                         │ auth, errors, contracts  │
                         └────────────┬─────────────┘
                                      │
                  ┌───────────────────▼───────────────────┐
                  │ FastAPI                                │
                  │ routers → services → repositories      │
                  ├────────────────────────────────────────┤
                  │ auth │ risk engine │ reporting │ GIS    │
                  └───────────────────┬───────────────────┘
                                      │ SQLAlchemy
                  ┌───────────────────▼───────────────────┐
                  │ PostgreSQL + PostGIS                   │
                  │ operational data and spatial layers    │
                  └────────────────────────────────────────┘
```

### Backend module boundaries

```text
backend/app/
  api/                 # FastAPI routers grouped by resource
    auth.py
    dashboard.py
    habitations.py
    relocation.py
    field_reports.py
    admin.py
  services/            # use cases; transaction boundaries live here
    dashboard_service.py
    habitation_service.py
    relocation_service.py
    report_service.py
  repositories/        # SQLAlchemy/PostGIS queries only
    habitation_repository.py
    relocation_repository.py
    report_repository.py
  domain/
    risk_engine.py     # pure, fully-tested decision calculations
  models/              # SQLAlchemy persistence models
  schemas/             # Pydantic request/response DTOs
  core/                # config, security, logging and database session
```

The first migration can retain the current `main.py` route behaviour while
extracting services and repositories one resource at a time. Do not split it
into network microservices: this product is currently a single bounded domain
and should remain a modular monolith.

### Frontend module boundaries

```text
src/
  app/                 # application shell, providers and route state
  features/
    dashboard/
    gis/
    habitations/
    relocation/
    field-reports/
    admin/
  shared/
    api/               # typed HTTP client and endpoint adapters
    components/
    types/
  demo/                # optional, isolated mock data adapter
```

`App.tsx` should become a composition layer. Each feature owns its query state,
loading/error state and mutations, while shared navigation and modals remain in
the application shell. A single `GET /api/bootstrap` endpoint can provide the
initial dashboard/map snapshot, avoiding the current eight independent startup
requests.

## API contract

Use `/api/v1` for all new or changed endpoints. Keep old paths temporarily
only if a deployed client requires them.

| Resource | Read operations | Write operations |
| --- | --- | --- |
| Bootstrap | `GET /api/v1/bootstrap` | — |
| Habitations | `GET /api/v1/habitations`, `GET /api/v1/habitations/{id}` | `POST /api/v1/habitations/{id}/priority-calculation` |
| Relocation | `GET /api/v1/relocation-sites`, `POST /api/v1/relocation-simulations` | Simulation remains non-persistent unless explicitly saved. |
| Field reports | `GET /api/v1/field-reports` | `POST /api/v1/field-reports`, `POST /api/v1/field-reports/{id}/verify` |
| Administration | — | `POST /api/v1/admin/hazard-imports`; demo reset only in demo environments. |

All write operations require a bearer token. Return a complete resource after a
mutation, or return a clear result DTO that the frontend explicitly consumes.
The simulator contract should use one naming convention consistently:
`relocation_site_id`, `families_requested`,
`remaining_capacity_after_relocation`, and `decision_rationale`.

## Data and geospatial design

- Store habitation and relocation-site coordinates as PostGIS `geometry(Point,
  4326)`; store red zones as `geometry(MultiPolygon, 4326)`.
- Use GIST spatial indexes and perform proximity/intersection calculations in
  repositories, not in React.
- Keep raw hazard feeds in an ingestion/audit table with source, timestamp,
  geometry validation result, checksum, and operator identity.
- Record risk-calculation inputs, formula version and output in an immutable
  calculation history table. A relocation recommendation must be traceable to
  the exact source data and formula version used.
- Keep synthetic seed data separate from production migrations and load it only
  through an explicit demo/seed command.

## Security and reliability baseline

- Replace the default JWT secret with a required environment variable outside
  demo development. Rotate credentials rather than placing them in Compose.
- Restrict CORS to configured frontend origins; `allow_credentials=true` cannot
  safely be paired with a wildcard origin in a production browser deployment.
- Add structured request logging, a health endpoint, readiness checks for the
  database, and an error response envelope.
- Enforce role checks in backend services, not only by hiding frontend buttons.
- Add database transactions for report verification, priority recalculation and
  any saved relocation decision.

## Access-control architecture

### Governing rules

Access is both **role-based** and **geographically scoped**. A role grants a
set of actions; the officer's assignment grants the geographic boundary in
which those actions are allowed. Higher operational roles inherit the read and
operational permissions of the levels below them, but never receive access to
data outside their assigned jurisdiction.

Before authentication, every non-admin user must select **State, District,
Sub-district, and Area/Division**. All four selections are mandatory. The
portal uses the chosen area to find eligible user assignments and, after login,
must confirm that the selected scope is contained in the authenticated user's
assigned scope. Administrators do not choose an operational geography before
login because their work is platform-wide.

```text
Pre-login (all non-admin users)
  State → District → Sub-district → Area/Division → Sign in
                                                   │
                                                   ▼
                  Assignment + hierarchy validation at API boundary
                                                   │
                                                   ▼
                  Role permissions ∩ assigned geographic scope
```

The selected geography is a filter and a login context, never proof of
permission by itself. The API must independently enforce the assignment on
every request.

### Role matrix

| Role | Geographic scope | Permitted capabilities |
| --- | --- | --- |
| Normal citizen | Selected public area | View public GIS layers, safe accommodation information and active risk alerts only. |
| Field officer | Assigned area/division | All citizen views; create and update risk-alert reports for assigned regions. Cannot publish outside the workflow or manage accommodation or staff. |
| Local office | Assigned area/division | All field-officer capabilities; maintain approved safe-accommodation locations, size, capacity and availability in the assigned division. Published accommodation data is visible to citizens and field officers. |
| Sub-district officer | Assigned sub-district and its divisions | All local-office capabilities; assign, move or remove local-office and field-officer assignments within the sub-district. |
| District officer | Assigned district and its sub-districts | All sub-district capabilities; assign, move or remove lower-level operational officers within the district. |
| State officer | Assigned state and its districts | All district capabilities; assign, move or remove lower-level operational officers within the state. |
| GIS analysis officer | Assigned analytical jurisdiction | View all approved map, alert, accommodation and historical-hazard data in scope; analyse current and historical events (including 20+ years), compare rainfall and hazard trends, and access analytical charts. Cannot raise alerts, edit accommodation, or manage staff. |
| Administrator | Platform-wide technical scope | Manage technical configuration, repair operational data under a controlled workflow, manage approved lower-level access roles, review server health and audit user login/session records. The administrator does not replace a jurisdictional officer for ordinary disaster decisions. |

### Permission model

Use explicit permissions rather than hard-coding role names in UI components or
route handlers. Recommended permission keys are:

```text
map.read_public                 alert.read                 alert.raise
accommodation.read             accommodation.manage
assignment.read                assignment.manage
hazard-history.read            analytics.read
audit-log.read                 session-log.read           system-health.read
technical-data.repair          role.manage
```

Role inheritance is implemented in a central policy table. The backend resolves
the effective permission set at login and still validates scope for each write.
For example, a district officer can manage a field officer only when both the
target assignment and the requested division belong to that district. A state
officer cannot silently manage a user assigned to another state.

### Alert workflow

1. A field officer creates a draft risk alert with location, hazard type,
   severity, observed time, evidence and affected geography.
2. The API validates that the geometry and affected area are inside the
   officer's assigned division.
3. The alert is visible as a pending operational alert to supervising local,
   sub-district, district and state officers.
4. An authorised supervisory workflow publishes, updates, expires or closes
   the alert. Citizens see only published alerts.
5. Every transition records actor, timestamp, selected geography, previous
   status, new status and reason.

This keeps field observations fast while preventing unverified reports from
appearing as public emergency warnings.

### Accommodation workflow

Local offices maintain accommodation records only inside their assigned
division. Each record includes location/geometry, facility type, usable area or
size, total family capacity, current occupancy, available capacity, status,
last verification time and source. The API derives availability as
`total_capacity - current_occupancy`; it must not accept a contradictory
availability value from the client.

Accommodation edits are immediately available to field officers and citizens
only when the record is marked published and operational. Historical changes
must be retained for audit and capacity planning.

### GIS analysis workspace

The GIS analysis officer receives a read-only analysis workspace rather than
operational mutation controls. It includes:

- Current-event analysis for flood, storm, landslide, cloudburst and other
  configured hazard types.
- Historical event layers and time-series data for at least the previous
  twenty years when source coverage exists.
- Rainfall comparison charts across selected years, areas and event types.
- Event counts, affected population, intensity, damage and seasonal trend
  comparisons.
- Exportable, clearly labelled analytical views that distinguish source data,
  modelled values and synthetic demo data.

Raw measurements should be held in a `hazard_observations`/`rainfall_measurements`
time-series dataset, while validated incidents live in `hazard_events`. GIS
analysis access is read-only and must honour the analyst's assigned geographic
scope.

### Required persistence model

Add the following entities to the PostGIS migration plan:

| Entity | Purpose |
| --- | --- |
| `administrative_areas` | State, district, sub-district and area/division hierarchy with geometry and parent relationship. |
| `user_assignments` | User, role, assigned administrative area, active period, assigning officer and assignment status. A user may have more than one historical assignment but only approved active assignments are effective. |
| `risk_alerts` | Alert geometry, affected area, hazard, severity, evidence, lifecycle status, reporter and publisher. |
| `risk_alert_transitions` | Immutable alert status history and approval rationale. |
| `accommodations` | Safe-location geometry, capacity inputs, occupancy, operational status and publishing status. |
| `accommodation_revisions` | Immutable history of accommodation edits and capacity changes. |
| `hazard_observations` | Dated rainfall and hazard measurements used for charts and long-term analysis. |
| `user_sessions` | Login time, logout/expiry time, selected geography, effective assignment, device/IP metadata where policy permits, and result. |
| `audit_events` | Immutable record for assignment, role, technical-repair and administrative actions. |

### API design additions

The versioned API should add the following resource groups:

```text
GET  /api/v1/geography/states
GET  /api/v1/geography/districts?state_id={id}
GET  /api/v1/geography/sub-districts?district_id={id}
GET  /api/v1/geography/areas?sub_district_id={id}
POST /api/v1/auth/login                    # includes selected geography

GET  /api/v1/alerts
POST /api/v1/alerts                         # field officer and above, scoped
POST /api/v1/alerts/{id}/publish             # supervising workflow
POST /api/v1/alerts/{id}/close

GET  /api/v1/accommodations
POST /api/v1/accommodations                  # local office and above, scoped
PATCH /api/v1/accommodations/{id}

GET  /api/v1/assignments
POST /api/v1/assignments                     # jurisdictional officer, scoped
PATCH /api/v1/assignments/{id}
DELETE /api/v1/assignments/{id}              # soft revoke; never hard delete

GET  /api/v1/analytics/hazards
GET  /api/v1/analytics/rainfall-comparison
GET  /api/v1/admin/sessions
GET  /api/v1/admin/system-health
```

Public read endpoints must return only published alerts and published
accommodation records. Every protected endpoint accepts or derives an
administrative-area filter and rejects out-of-scope IDs, coordinates and
geometries.

## Delivery roadmap

### Phase 1 — Stabilise the prototype

1. Add the missing backend Dockerfile and make root Compose canonical.
2. Add Vite `/api` proxy and documented `VITE_API_BASE_URL` / `VITE_DATA_MODE`.
3. Separate the HTTP client from the demo adapter; stop silent fallback in API
   mode.
4. Align simulator and priority response DTOs and add backend verification and
   reset endpoints.
5. Make `risk_engine.py` the only production scoring implementation.

### Phase 2 — Activate persistence

1. Introduce repositories for habitations, sites and reports using the existing
   Alembic/PostGIS schema.
2. Move each endpoint from the `DATA` dictionary to service/repository calls.
3. Seed demo data through a repeatable command instead of module import state.
4. Add integration tests against PostgreSQL/PostGIS in containers.

### Phase 3 — Operational readiness

1. Add authenticated UI login and token refresh/logout handling.
2. Add calculation audit history, source provenance and approval workflow.
3. Add observability, backup/restore, rate limits and production CORS/secrets.
4. Version the API and publish its OpenAPI contract to the frontend build.

## Acceptance criteria for the target state

- A fresh browser session displays data only from the selected source: API or
  explicitly labelled demo adapter.
- A report submission, verification or priority recalculation survives an API
  restart and appears consistently in every browser session.
- The browser never determines the official priority or relocation score.
- `docker compose up --build` from the repository root starts database, API and
  frontend successfully.
- API contract tests and frontend contract/type checks run in CI.
- The system can explain which source data and formula version produced each
  relocation decision.

## Immediate implementation priority

Build Phase 1 before adding features. It removes the current ambiguity about
which data is authoritative, makes the environment reproducible, and protects
the decision-support calculations from client/server drift. Phase 2 should be
the first production-readiness milestone because persistent, auditable data is
required for a disaster-management workflow.

---

## SAFE_MOVE_AI — implemented live-intelligence additions (18 Sep 2026)

**Objective:** extend the Chamoli pilot into a national-scale multi-hazard
decision-support system (SAFE_MOVE_AI) with live weather, rainfall, terrain and
flood intelligence feeding a scored Risk Intelligence UI.

### Live-data service layer

The backend (`nammasafe-ai/backend`) exposes live-intelligence endpoints
(`nammasafe-ai/backend/app/integration_routes.py`):

| Endpoint | Backing source | Status model |
| --- | --- | --- |
| `/api/weather/{lat}/{lon}` | Open-Meteo (keyless) | LIVE |
| `/api/terrain/{lat}/{lon}` | NASA Earthdata SRTMGL1.003 (LP DAAC Earthdata Cloud; EDL bearer token) | LIVE when the token is configured and the tile is served; `NOT_CONFIGURED` without a token, `UNAVAILABLE` on upstream failure. Open-Meteo is an opt-in, clearly-labelled fallback (`NASA_TERRAIN_FALLBACK_OPENMETEO=on`, off by default) |
| `/api/elevation?lat&lon` | Alias of the same terrain service | Same status model as `/api/terrain` |
| `/api/rainfall/{lat}/{lon}` | NASA GPM IMERG (GES DISC bulk tiles) | LIVE once an IMERG tile is ingested; otherwise `NOT_CONFIGURED` |
| `/api/rainfall-grid` | NASA GPM IMERG (sampled viewport grid) | LIVE grid of `{lat, lon, mm/hr}` points within `bounds`; powers the map "Live Rainfall" layer |
| `/api/flood-risk/{lat}/{lon}` | Copernicus GloFAS (cached dataset) | `NOT_CONFIGURED` until a dataset is present |
| `/api/flood-forecast` | Google Flood Forecasting (optional key) | `DEMO`/`FORECAST` |
| `/api/nearby/{kind}`, `/api/geocode` | OpenStreetMap Overpass / Nominatim | LIVE |
| `/api/risk-assessment`, `/api/risk-zones` | Weighted rule engine | `rule_based`/`hybrid`/`ml` |

### GPM rainfall ingest pipeline (bulk tiles, not a point API)

Rainfall is the only non-REST source: GPM/IMERG ships half-hourly HDF5 tiles.
Current product: **IMERG Early `GPM_3IMERGHHE.07`** (V06 retired; the cloud
`.06` path now returns fake-200 HTML "404" pages for everything, so it is never
used). Pipeline:

1. `backend/scripts/fetch_gpm_data.py` authenticates to GES DISC with the
   Earthdata **JWT token** (`Authorization: Bearer`, falls back to Basic) from
   gitignored `backend/.env` (`EARTHDATA_USERNAME`, `EARTHDATA_TOKEN`).
2. It lists the product directory
   `https://gpm1.gesdisc.eosdis.nasa.gov/data/s4pa/GPM_L3/GPM_3IMERGHHE.07/<YYYY>/<DDD>/`
   and resolves filenames from the directory listing (the per-day run version
   suffix varies, `V07B`/`V07C`, so names are never constructed).
   `--recent` scans backward in half-hour steps until a published slot is found,
   honouring the ~4 h Early latency (`IMERG_LATENCY_HOURS`, default 4).
   Downloads are validated with the HDF5 magic bytes
   (`\x89HDF\r\n\x1a\n`) and a non-HDF5 payload is deleted rather than kept.
3. `app/rainfall_service.py` (`NasaGpmProvider`) reads the tile with `h5py`
   (optional dependency, pinned in `requirements.txt`): V07 nests everything in
   a `Grid` group and georeferences via `Grid/lat` + `Grid/lon` 1-D arrays
   (slice is `(time, lon, lat)`, nearest-cell lookup, `_FillValue = -9999.9`
   mapped to 0.0 mm/hr). Legacy `GridLat0`/`GridLon0`/`SpanOfGrid` attribute
   layout is kept as a fallback.
4. A 403 with `error_description: EULA Acceptance Failure` prints the exact
   approval URL (`urs.earthdata.nasa.gov/approve_app?client_id=e2WVk8Pw6weeLUKZYOxvTQ`):
   the Earthdata account must approve the **GES DISC application** (user
   `nethajiraja`) before any tile downloads.

Running: `python scripts/fetch_gpm_data.py --recent` (from `nammasafe-ai/backend`),
then restart the API so the service picks up the tile.

Interactive GIS map: the GisMapPage/LeafletMap layer panel has a "Live Rainfall"
toggle (id `map-rainfall-layer-toggle`). When on, the frontend calls
`GET /api/rainfall-grid?bounds=north,south,east,west&max_points=N`
(default Chamoli viewport 30.8,29.8,79.8,79.0, step 0.05°) and renders each cell
as a colour-coded dot: light blue 0.1–2.5, blue 2.5–7.5, orange 7.5–30,
red >30 mm/hr, with a matching legend; fill cells (`< -100`) are shown as no
data and NOT_CONFIGURED/UNAVAILABLE labels the toggle via the data-status panel.

### Honest-data contract (enforced, tested)

Every payload carries an explicit `data_status` — `LIVE`/`FORECAST`/
`HISTORICAL`/`DEMO`/`NOT_CONFIGURED`/`UNAVAILABLE` — and failures are labelled,
never fabricated. Two fixes landed 18 Sep to keep provenance truthful:

- `GET /api/data-status` reported the rainfall layer `LIVE` from
  `GPM_MODE=on` alone; it now asks `rainfall_service._provider._configured()`
  and reports `LIVE` only when an IMERG tile is actually ingested.
- The rainfall point endpoint 500ed when unconfigured because the
  `NOT_CONFIGURED` payload omitted `latitude`/`longitude` that `RainfallResponse`
  requires; `get_rainfall` now always injects both, so unconfigured/UNAVAILABLE
  responses are clean 200s with an actionable `reason`.

### Activation state and testing

- Backend `pytest` **133 passing** (incl. GES DISC fetch helpers and the
  unconfigured-200 regression); frontend `npm run lint` (tsc) clean and
  `vitest run` **36 passing**.
- GES DISC EULA approved for the GES DISC application; a real `GPM_3IMERGHHE.07`
  Early tile is ingested in `backend/data/gpm` and the live stack reports
  `/api/rainfall` and `/api/data-status` rainfall as `LIVE` (risk-assessment
  rainfall source also LIVE). If the tile is removed, both revert to labelled
  `NOT_CONFIGURED`/`UNAVAILABLE`.

### All-India dynamic-location build (18 Sep 2026, phase 2)

**Objective:** the platform is now **location-driven across all states of
India**, not Chamoli-locked. Every layer follows the selected
State → District → Village; there are no silent Uttarakhand/Chamoli fallbacks;
and non-pilot regions get honest, labelled responses.

**Decision:** the landing view is a **nationwide overview** (unselected):
India viewport (lat 22.5 / lng 78.9 / zoom 5) with nationwide curated disaster
markers; on selecting a region the map flies to the resolved anchor and loads
that region's layers.

**Backend (`nammasafe-ai/backend`):**

- Pilot gating via `_is_pilot_region(state, district)` in `app/main.py`:
  state-only Chamoli (`Uttarakhand`) stays a live habitat layer; non-pilot
  state/district queries are **not** seeded with Chamoli data.
- Region filters (`_item_region`, `_region_match`) applied to `/api/habitations`,
  `/api/relocation-sites`, `/api/dashboard-summary`, `/api/map-layers`
  (per-layer `layers_status` + `pilot_center`, null for non-pilot),
  `/api/analytics/hazards`, `/api/flood-forecast` (non-pilot → empty +
  `data_status:"UNAVAILABLE"`).
- New `GET /api/habitations/dynamic?state&district&lat&lng&radius_km` in
  `app/integration_routes.py`: real **OSM/Overpass-derived habitations**
  (curated lookup first, live OSM second), returned in an envelope
  `{habitations, data_status, data_source, count, center, radius_km, reason}`.
  Dynamic records carry zeroed curated fields plus `is_dynamic_osm`, `source`,
  `data_status` so every page renders safely.
- Live providers stay coordinate-driven: Open-Meteo weather, NASA Earthdata
  SRTM terrain (LP DAAC, EDL bearer token; Open-Meteo fallback opt-in), NASA GPM
  rainfall (`/api/rainfall-grid` now **requires** `bounds`; 400 on missing or
  malformed bounds), GloFAS flood, OSM nearby/geocode, risk engine, OSRM.
- `app/nearby_places.py` gained a `villages` kind (region villages for the map).

**Frontend (`src/`):**

- `src/App.tsx` owns `fetchRegionData(region | null)` — a `null` selection is
  the national overview (no summary/risk/rainfall/flood for the whole country)
  and any region change reloads every layer for that region.
- `src/services/api.ts`:
  `getHabitations` → `HabitationsFetchResult` envelope; `getDashboardSummary`,
  `getMapLayers`, `getRelocationSites`, `getHazardEvents`, `getFloodForecast`,
  `getRainfallMap`, `getRiskZones` all take `state`/`district`; non-pilot
  summary is an honest `UNAVAILABLE` empty with `relocation_priority_distribution`
  covered across all four `PriorityLevel`s and an explanatory `message`.
- `src/lib/regionViewport.ts` maps region → `{ anchor, bounds }`, with a
  nationwide `INDIA_OVERVIEW` branch when `!region.state`.
- `src/components/DataStatusBadge.tsx` renders the user-facing honesty vocabulary
  on every external-data card (Risk Intelligence weather / terrain / flood /
  rainfall / safe-locations / nearby / disasters): backend statuses map to
  **LIVE / RECENT (FORECAST) / CACHED (HISTORICAL) / SIMULATED (DEMO) /
  UNAVAILABLE** and show **Last Updated** from `observed_at` / `computed_at` /
  `tile_time` / `updated_at`. The former per-card `statusDot` is replaced by it.
- `DataLayerStatus` in `src/types/index.ts` now includes `'SIMULATED'`.
- De-hardcoded copy across `Navbar`, `Sidebar` (nationwide breadcrumb + "Reset
  to nationwide view"), `DashboardPage`, `GisMapPage` (dynamic counts/labels,
  pilot hotspots gated), `RiskIntelligencePage` (anchor-aware defaults, generic
  habitation picker), `MapLayerPanel` ("Reset Map to India View"), `SiteModal`.
  `LeafletMap.tsx` defaults to the India viewport, adds a nationwide disaster
  layer (coloured markers + popups), and its reset flies back to India.

**Tests:** backend `pytest` **150 passing** (new `tests/test_multi_state.py`:
15 tests covering Tamil Nadu honest-empty habitations, Uttarakhand state-only
seed preservation, Kerala empty relocation-sites, non-pilot summary/map-layers
`UNAVAILABLE`, analytics filtering, Chennai dynamic-OSM envelope shape,
rainfall `bounds` validation, risk-zones near locations and flood-forecast
headers). Frontend `npx tsc --noEmit` clean and `vitest run` **38 passing**
(`api.test.ts` asserts the envelope + non-pilot empty).

**Run without Docker:** `python run_all.py` creates/uses the backend venv
(`nammasafe-ai/backend/.venv`, deps pinned in `requirements.txt`) and starts
the API (`127.0.0.1:8000`) + Vite (`127.0.0.1:3000`); `python run_all.py --stop`
tears it down. Backend env (`backend/.env`, gitignored): `GPM_MODE=on`,
`GPM_DATA_DIR`, `EARTHDATA_USERNAME`, `EARTHDATA_TOKEN`, `IMERG_LATENCY_HOURS`,
all documented in the root `.env.example`. Select any state/district (e.g.
Uttarakhand, Tamil Nadu, Cuddalore, Chennai, Kerala, Maharashtra, Odisha) and
every provider/UI relabels per selection; the unselected landing shows the
nationwide overview.

### Docker (ready to verify on a Docker-capable host)

Backend image `nammasafe-ai/backend/Dockerfile` (built on `python:3.13-slim`
for reliable manylinux wheels across the pinned stack) ships the app, GPM
`scripts/`, a public `GET /health` liveness probe (with a compose healthcheck),
`backend/.dockerignore` keeps `.venv`, tests and the gitignored `.env` out of
the build context so GPM credentials never land in an image layer. The root
`docker-compose.yml` bind-mounts `./nammasafe-ai/backend` over `/app`, so the
local `backend/.env` is picked up when present and env-var overrides
(`GPM_MODE`, `EARTHDATA_USERNAME`, `EARTHDATA_TOKEN`, `GPM_DATA_DIR`) are
documented as commented placeholders. Verified locally: `docker compose
up --build` still needs a Docker host (not available on this development
machine).
