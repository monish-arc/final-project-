# Weather Map Replacement + Terrain Preservation — Design

Date: 2026-09-27. Status: approved by user (native execution).

## Goal

Replace the standalone "Terrain Elevation Map" navigation page with a
dedicated historical Weather Map, while keeping terrain/elevation working
as a click feature inside the Interactive GIS Map and fixing the stuck
"Loading elevation…" popup. The backend is not modified.

## Non-negotiable constraints

- Backend (`nammasafe-ai/backend`) is NOT modified. pytest baseline: 321
  pass + 1 intentional failure must hold.
- No fabricated weather/terrain/population/capacity values. Unavailability
  is shown honestly ("Historical data unavailable for this selection",
  disabled-with-reason, `DATA UNAVAILABLE`).
- Historical ERA5 is a MONTHLY aggregated grid (map raster). Only
  point-level daily rows exist. The map raster stays monthly; the day
  control affects only the location popup readout.
- Everything else (village/census, accommodation, risk, GIS layers,
  authentication/RBAC, live-provider abstraction) is preserved.
- Frontend dev server runs with `DISABLE_HMR` (file watching off) — the
  server must be restarted after source edits before E2E probes.

## Navigation

- Sidebar keeps all 14 items except `terrain` (deleted). `weather` label
  changes to **"Weather Map"** and keeps its position after Interactive
  GIS Map. Terrain stays available via GIS-map clicks (citizens included).
- Delete `src/pages/TerrainMapPage.tsx` and
  `src/components/terrainmap/TerrainMap.tsx`. Keep `src/lib/terrainPopup.ts`
  (used by the GIS map).

## Weather Map (existing `src/components/weathermap/WeatherMap.tsx`, extended)

Defaults: layer = **Rainfall** (`precipitation`), historical year = **2025**,
basemap = **Street (light)** (Dark/Satellite remain options).

Controls:
- Top: Search, Locate, Year selector, **Historical Data** + **Live Provider**
  chips, **Weather Settings** gear, fullscreen, basemap buttons.
- Historical bottom bar: **Jan–Dec month timeline** (selected month
  highlighted; months beyond completed disabled; current-year caption
  "2026 (Jan–Aug) · Historical / completed months only · NOT LIVE").
- **Date control** `[Monthly | Daily ▼] < ‹ 12 Aug 2025 › >`: prev/next +
  native date picker bounded to the completed month; Daily mode makes the
  location popup read the selected day's actual daily row.
- **HISTORICAL DATA · ERA5/GPM · NOT LIVE** chip pinned top-left in
  historical mode.
- Live hourly timeline and wind particles remain live-mode-only (wind u/v/
  direction are not in the ERA5 archive — no honest historical streamlines).

Layers & legend: layer list ordered per user spec (Rainfall first);
`precipitation` relabeled "Rainfall"; Windy-style rainfall ramp
blue→cyan→green→yellow→orange→red→purple; rainfall legend stops
0 / 1 / 5 / 10 / 20 / 50 / 100 / 200+ mm. Variables absent from the ERA5
archive (humidity, cloud cover, wind direction, U, V, rain probability,
visibility, feels-like) stay listed but disabled with an honest reason.

Location popup: Latitude, Longitude, `Date: DD MMM YYYY` (selected day),
Rainfall mm, Temperature °C, Wind Speed km/h, Humidity % (only when present
in the response), Source: ERA5 (Historical), status. Monthly mode keeps
month aggregates; absent values are omitted, never fabricated.

Settings / Live provider: **Weather Data Source `[Historical] [Live
(Optional)]`** toggle in a settings popover; Live disabled by default.
**Live Weather Provider**: "Disabled — No live provider configured" +
`+ Add Live Provider` (template list Open-Meteo / ECMWF / NOAA / NWS /
other; stored in localStorage by a new `src/lib/liveProviders.ts`; never
fires network calls; always marked "Disabled (backend live weather not
enabled)"). Selecting Live with no enabled provider shows an honest note
and changes nothing on the map. Historical mode requests carry only
`year`+`month` (no `day`/`prefer`) — no auto live calls, no 429s.

## Terrain fix (Interactive GIS Map — `src/components/LeafletMap.tsx`)

Root cause: `LeafletMap.tsx:301-321` opens the popup with hard-coded
"Loading elevation…" and issues `getElevationFast`/`getTerrain` with no
timeout, no AbortController, no signal — a never-settling fetch leaves the
popup stuck forever.

Fix (client-side only; api.ts + backend untouched):
- Reuse shared `terrainPointPopupHtml` (`src/lib/terrainPopup.ts`).
- Per-click AbortController (abort in-flight on next click + map teardown);
  keep monotonic `seq` guard and 300 ms debounce.
- `TERRAIN_POPUP_TIMEOUT_MS = 10_000` exported from `terrainPopup.ts`:
  an unresolved popup flips to the honest `TEMPORARILY UNAVAILABLE`
  payload ("SRTM provider is slow — the point may still arrive; re-click
  to retry."), never stuck.

## Out of scope

Backend edits (including the `top_rain_day` date quirk at
`historical_weather.py:584`), a real daily historical grid, and live
provider implementation. All remain as-is; unavailability surfaced honestly.