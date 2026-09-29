# Weather Map Replacement + Terrain Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans
> (native execution chosen). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the standalone "Terrain Elevation Map" page with a
dedicated historical Weather Map (default 2025 ERA5, rainfall default,
month timeline, date control, optional-disabled live providers), keep
terrain as a click feature inside the Interactive GIS Map, and fix the
stuck "Loading elevation…" popup.

**Architecture:** Extend `src/components/weathermap/WeatherMap.tsx` (keeps
its ERA5 grid flow); extract new panels/helpers into focused files under
`src/components/weathermap/` and `src/lib/`; remove the standalone terrain
page from nav; fix the GIS-map terrain handler with timeout+abort. Backend
and `src/services/api.ts` untouched.

**Tech Stack:** React 18 + TypeScript + Vite, Leaflet, Playwright E2E
probes (node scripts), Vitest.

**Spec:** `docs/superpowers/specs/2026-09-27-weather-map-design.md`

## Global Constraints

- Backend (`nammasafe-ai/backend`) is NOT modified — pytest baseline 321
  pass + 1 intentional fail must hold.
- No fabricated weather/terrain values; unavailability is shown honestly.
- Historical grid is monthly ERA5 aggregate; only point-level daily rows
  exist → map raster stays monthly; the day control affects only the popup.
- Frontend dev server runs with `DISABLE_HMR` (watch off in
  `vite.config.ts:19`) → restart `npm.cmd run dev` after source edits
  before E2E probes.
- Keep `terrainPopup.ts` (used by the GIS map). Delete only the standalone
  terrain page components.
- Rainfall (`precipitation`) default layer; default year 2025; default
  basemap Street (light); Dark/Satellite remain options.
- Not a git repository — no commit steps.

## Review Focus

1. Re-clicking a cached terrain point in the GIS map → instant full popup,
   zero network (no refetch).
2. Historical layer absent from ERA5 archive (Humidity, Cloud, Direction,
   U, V, Probability, Visibility, Feels-like) → listed but disabled with
   honest reason; selecting Live fires no network (no 429).
3. Year 2026 → only completed months enabled (Jan–Aug today), disabled
   future months, "completed · NOT LIVE" wording.
4. Terrain popup whose fetch never settles → flips to `TEMPORARILY
   UNAVAILABLE` within 10 s; never stuck on "Loading elevation…".
5. Live provider not configured → "Disabled / No live provider
   configured", `+ Add Live Provider` present, zero auto live calls,
   historical map unaffected.
6. Weather +/− zoom → no white flash, no duplicate layers/markers, grid
   refetch only on settled viewport change.

---

### Task 1: Remove standalone terrain page from navigation

Files: modify `src/components/Sidebar.tsx` (NavTab union 27-41, NAV_ITEMS
63-68, imports), `src/App.tsx` (terrain block 578-584 + import); delete
`src/pages/TerrainMapPage.tsx`, `src/components/terrainmap/TerrainMap.tsx`.

- [ ] Step 1: grep `src/` for `'terrain'`/`TerrainMap`/`TerrainMapPage`
      references (Navbar, DashboardPage, RiskIntelligencePage, DocsPage).
- [ ] Step 2: remove `terrain` from NavTab; delete terrain NAV_ITEMS entry;
      rename weather label to "Weather Map"; drop unused `Mountain` import.
- [ ] Step 3: remove the `activeTab === 'terrain'` render block and import
      in App.tsx.
- [ ] Step 4: delete the two terrain page files; confirm no imports remain;
      leave `weatherLayers.ts` terrain exports (unused exports OK).
- [ ] Step 5: verify `npx tsc --noEmit` EXIT 0; `npx vitest run` green;
      grep confirms `terrain-map-view`/`terrain-map-canvas` gone.

### Task 2: Weather-map defaults, Rainfall layer/legend, layer order

Files: modify `src/lib/weatherLayers.ts`, `WeatherMap.tsx:165-167`;
create `src/components/weathermap/WeatherLegend.tsx`; test
`src/lib/weatherLayers.test.ts`.

Interfaces:
- `VariableMeta` gains optional `stops?: number[]` and `stopsPrefix?: 'over'`.
- Produces `RAINFALL_COLORS` (blue→cyan→green→yellow→orange→red→purple),
  `RAINFALL_STOPS = [0,1,5,10,20,50,100,200]`.
- `WEATHER_LAYER_ORDER` = [precipitation, temperature_2m, apparent_temperature,
  wind_speed_10m, wind_direction_10m, wind_u, wind_v, precipitation_probability,
  precipitation_accumulation, storm_indicator, relative_humidity, pressure_msl,
  cloud_cover, visibility].

- [ ] Step 1: write failing tests in `weatherLayers.test.ts` (label
      "Rainfall", RAINFALL_STOPS, order first = 'precipitation', purple
      endpoint in precipitation colors).
- [ ] Step 2: run `npx vitest run src/lib/weatherLayers.test.ts` → FAIL.
- [ ] Step 3: implement relabel + ramp + stops + reorder in weatherLayers.ts.
- [ ] Step 4: WeatherMap defaults: variable `'precipitation'`, basemap
      `'street'`, historicalYear `HISTORICAL_YEAR_DEFAULT`.
- [ ] Step 5: create `WeatherLegend.tsx` (discrete stops legend for
      rainfall) and wire to replace legend block WeatherMap.tsx:1226-1250.
- [ ] Step 6: `npx vitest run`; `npx tsc --noEmit`.

### Task 3: Historical controls — month timeline, date control, NOT-LIVE indicator, popup

Files: create `src/lib/historicalDates.ts`,
`src/components/weathermap/MonthTimeline.tsx`,
`src/components/weathermap/DateControl.tsx`; modify WeatherMap.tsx; test
`src/lib/historicalDates.test.ts`.

Interfaces:
- `monthShort(n)`, `daysInMonth(y,m)`, `completedMonthsFor(y, availability)
  : number`, `fmtDateLabel(y,m,d)` ("12 Aug 2025"), `withinCompleted(y,m,
  availability)`.
- WeatherMap state: `historicalDay: number | null`, `dayMode: 'monthly' |
  'daily'`, `settingsOpen: boolean`.

- [ ] Step 1: write `historicalDates.test.ts`.
- [ ] Step 2: run → FAIL (module missing).
- [ ] Step 3: implement historicalDates.ts.
- [ ] Step 4: create MonthTimeline.tsx.
- [ ] Step 5: create DateControl.tsx.
- [ ] Step 6: WeatherMap — replace historical bottom note (1392-1401) with
      MonthTimeline + DateControl (keep live hourly timeline 1332-1389);
      strengthened HISTORICAL DATA · ERA5/GPM · NOT LIVE chip near badge
      (839-849); grid fetch deps unchanged (no day).
- [ ] Step 7: extend HistoricalPointPanel (1454) to read daily rows per
      day/daily vs monthly.
- [ ] Step 8: `npx tsc --noEmit`; `npx vitest run`.

### Task 4: Weather Settings + Live Provider (optional/disabled)

Files: create `src/lib/liveProviders.ts`,
`src/components/weathermap/LiveProviderPanel.tsx`,
`src/components/weathermap/WeatherSettingsPanel.tsx`; modify WeatherMap.tsx;
test `src/lib/liveProviders.test.ts`.

Interfaces:
- `LiveProviderConfig { id; name; kind: 'open-meteo'|'ecmwf'|'noaa'|'nws'|
  'other'; baseUrl?; note?; enabled: false }`.
- `LIVE_PROVIDER_TEMPLATES`; `getLiveProviders()`, `saveLiveProvider(cfg)`,
  `removeLiveProvider(id)`, `liveProviderStatus(cfg) → 'disabled'`.
- localStorage key `safe-move/live-providers`.

- [ ] Step 1: write liveProviders.test.ts.
- [ ] Step 2: run → FAIL; implement liveProviders.ts.
- [ ] Step 3: LiveProviderPanel.tsx (Disabled, empty state, Add form).
- [ ] Step 4: WeatherSettingsPanel.tsx (data-source toggle + panel).
- [ ] Step 5: WeatherMap top bar chips + settings gear
      (`id="weather-settings-btn"`); remove `Live (today)` from year select.
- [ ] Step 6: grep guard — historical requests send only year/month.
- [ ] Step 7: `npx tsc --noEmit`; `npx vitest run`.

### Task 5: GIS-map terrain fix — never stuck on "Loading elevation…"

Files: modify `src/lib/terrainPopup.ts`, `src/components/LeafletMap.tsx:
17-78, 281-321`; test `src/lib/terrainPopup.test.ts`.

Interfaces:
- Export `TERRAIN_POPUP_TIMEOUT_MS = 10_000` from terrainPopup.ts.

- [ ] Step 1: terrainPopup.test.ts asserts exported constant === 10000.
- [ ] Step 2: run → FAIL; export constant.
- [ ] Step 3: LeafletMap.tsx — remove local builder; use shared builder +
      10 s timeout + per-click AbortController (signal passed to
      getElevationFast/getTerrain, seq guard, abort on new click/teardown);
      timeout flips to TEMPORARILY UNAVAILABLE payload.
- [ ] Step 4: `npx tsc --noEmit`; `npx vitest run`.

### Task 6: Static verification + dev server restart

- [ ] Step 1: `npx tsc --noEmit` (0); `npx vitest run` (green); `npm run
      build` (0).
- [ ] Step 2: kill + restart frontend dev server (`DISABLE_HMR=true`,
      Start-Process npm.cmd, logs `%TEMP%\opencode\vite*.log`); confirm
      :3000 serves new module (curl transformed WeatherMap.tsx, grep for
      sentinel strings).

### Task 7: E2E probes + backend regression

Files (temp `%TEMP%\opencode`): update `p7_acceptance.cjs`,
`p_citizen_no_weather.cjs`; delete `p_terrain.cjs`, `p_terrain_cache.cjs`,
`p_terrain_change5.cjs`; create `p_gis_terrain.cjs`, `p_weather_v2.cjs`.

- [ ] Step 1: p7_acceptance.cjs — no "Terrain Elevation Map", "Weather Map"
      present.
- [ ] Step 2: p_citizen_no_weather.cjs — citizen nav = Map/Alerts/Risk
      Intelligence; GIS terrain click works for citizen.
- [ ] Step 3: p_gis_terrain.cjs — cached-cell clicks resolve LIVE in <10s
      (never stuck), repeat click cached (no refetch).
- [ ] Step 4: p_weather_v2.cjs — full assertion list (see spec).
- [ ] Step 5: run all probes + `python -m pytest` (321 + 1 intentional).

---

Execution method: native (selected). Final fresh-context review via
subagent after Task 7, then one fix pass for Critical/Important findings.