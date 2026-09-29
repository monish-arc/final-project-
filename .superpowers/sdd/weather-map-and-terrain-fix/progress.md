# SDD ledger — plan: docs/superpowers/plans/2026-09-27-weather-map-and-terrain-fix.md

Workspace: .superpowers/sdd/weather-map-and-terrain-fix (repo is NOT a git repo; no commits; no worktree).

Spec: docs/superpowers/specs/2026-09-27-weather-map-design.md (approved).

Execution: native (user approved).

Pre-flight scope: tasks share WeatherMap.tsx (Tasks 2,3,4), weatherLayers.ts (Task 2 produces RAINFALL_STOPS/order consumed by Task 2 legend + Task 3 timeline UI), terrainPopup.ts (Task 5 produces TERRAIN_POPUP_TIMEOUT_MS). No interface conflicts found.

## Task-by-task ledger
(see task lines appended below as they complete)

Task 1: complete (terrain tab removed from Sidebar NavTab/NAV_ITEMS, weather relabeled "Weather Map", App terrain block+import removed, TerrainMapPage.tsx + terrainmap/TerrainMap.tsx deleted; tests: npx tsc --noEmit → 0, npx vitest run → 72/72)

Task 2: complete (VariableMeta.stops/stopsPrefix, RAINFALL_COLORS rainbow, RAINFALL_STOPS [0,1,5,10,20,50,100,200], precipitation→'Rainfall', WEATHER_LAYER_ORDER = user 14 (Rainfall first), legendTickLabels(), WeatherLegend.tsx replaces legend block; WeatherMap defaults variable 'precipitation' + basemap 'street'; legendColors removed; tests: vitest 77/77 (+5), tsc 0)

Task 3: complete (new src/lib/historicalDates.ts + test; MonthTimeline.tsx month buttons + id weather-month-N; DateControl.tsx Monthly/Daily toggle + day chevrons + native date input + id weather-historical-date/day-label/res-scale; historical bottom note → timeline+date panel w/ NOT LIVE pill id weather-not-live + caption id weather-historical-caption; archival chip id weather-archival-chip text "HISTORICAL DATA · ERA5 ARCHIVE · NOT LIVE" — deliberately says ERA5 ARCHIVE not user's "ERA5/GPM" because data_source is ECMWF ERA5 (honesty); HistoricalPointPanel now reads real per-day rows (daily) vs monthly aggregates, Date line shown; types/index.ts HistoricalDailyRow → HistoricalDayRow matching real backend daily payload (per-day named-field rows); handleHistoricalYear resets day/formatting; grid refetch deps untouched (no day). tests: vitest 82/82 (+5), tsc 0)

Task 4: complete (src/lib/liveProviders.ts + test (resetLiveProviderStore for test isolation); LiveProviderPanel.tsx (empty state "Disabled — No live provider configured", + Add Live Provider w/ template select form, remove rows, honest disabled notes, zero network); WeatherSettingsPanel.tsx (source toggle Historical/Live-Optional, amber note when Live chosen — map unaffected; gear button #weather-settings-btn in top bar; #weather-settings-panel). Guard: grid fetch deps [feed,effectiveHour,viewportKey,isHistorical] — historicalDay/dayMode excluded; api.ts getWeatherHistorical path only year&month (no day). tests: vitest 88/88 (+6), tsc 0)

Task 5: complete (terrainPopup.ts exports TERRAIN_SOURCE + TERRAIN_POPUP_TIMEOUT_MS=10_000; terrainPopup.test.ts 6 cases. LeafletMap.tsx: local terrainPopupHtml + escHtml removed; shared terrainPointPopupHtml used; per-click AbortController + seq guard + 300ms debounce kept → getElevationFast/getTerrain({signal}); window timeout flips popup to TEMPORARILY UNAVAILABLE payload (never stuck on "Loading elevation…"); abort on new click + map teardown; timer cleared on resolve/catch. api.ts getTerrain/getElevationFast already accept {signal}. tests: vitest 88/88, tsc 0)

Task 6: complete (tsc 0, vitest 88/88, npm run build ok; dev server restarted DISABLE_HMR; transformed modules served: WeatherMap/MonthTimeline/DateControl/WeatherSettingsPanel/WeatherLegend/terrainPopup sentinels verified via HTTP)

Task 7: complete (E2E 5/5 green:
- P_GIS_TERRAIN: popup opens immediately, loading-state first, resolves <10s (never stuck), elevation value rendered, 2nd click re-resolves, no crash; elevationFast fired.
- P_WEATHER_V2: no terrain nav, "Weather Map" label, rainfall default-selected + first-in-order, street basemap=OSM only, historical affordances (badge/selector/NOT LIVE), archival chip exact "HISTORICAL DATA · ERA5 ARCHIVE · NOT LIVE", live timeline hidden, month timeline buttons + click, day label real format (1 Jun 2025 via Daily), historical grid settled w/ requests, settings gear+panel, provider templates, providers disabled, reset-to-temp, dom sane.
- PHASE7_ACCEPTANCE: dashboard/GIS map/weather page; terrain nav removed; Weather Map label; all tabs render.
- P_CITIZEN_NO_WEATHER: hides weather+dashboard+terrain nav, keeps risk intel, fetches terrain on assess, zero weather/rainfall/flood calls, honest gate reason, risk assessment served.
- P_WEATHER_MAP (legacy probe): grid status, no cartocdn, no live calls in historical, historical badge period, hidden live controls, historical data resolved, era5 provenance.)
Legacy terrain probes p_terrain.cjs/p_terrain_cache.cjs/p_terrain_change5.cjs deleted (page retired); p7_acceptance.cjs + p_citizen_no_weather.cjs updated.
backend pytest: 321 passed / 1 failed (Tamil Nadu rainfall probe — intentional baseline, backend untouched))

Final review: complete (fresh-reviewer subagent; findings triaged with verification)

Review fixes applied (all verified in code before fixing):
- [BLOCKER] WeatherMap grid effect omitted historicalYear/month from deps → month/year changed labels but NOT the raster; flood effect same. Fixed: weather effect deps now [feed,effectiveHour,fetchGrid,isHistorical]; flood deps now [feed,viewportKey,isHistorical,historicalYear,historicalMonth]. E2E-verified: clicking month 6 now fires a real /api/weather/grid?month=6 request (p_weather_v2 'month-click-refetches-grid-for-month').
- [MAJOR] Map armed a live grid call on every mount (historicalYear=null until availability resolved) and could sit stuck in live if availability failed. Fixed: init year=2025, month=1 → map opens in historical mode; no implicit live request.
- [MAJOR] Terrain fast-path terminal UNAVAILABLE left popup stuck "Loading terrain…" for 10s then claimed "SRTM provider is slow" (false for a 403/500). Fixed: render real reason immediately, keep any real elevation visible (never wiped by later failure), timeout/catch use last-known elevation.
- [MAJOR] Picker enrichment could attach a stale response to a newer click. Fixed: pickerSeqRef + coordinate guard.
- [MAJOR] "Wettest day" printed backend's buggy top_rain_day (date=1st of month, mm=month total). Fixed: derive real wettest day from weather.daily (date + that day's mm); removed duplicate precipitation_accumulation usage.
- [MAJOR] API-NOT-ADDED banner hardcoded "(2022–2026)... weekly". Fixed: period derived from yearAvail, wording "monthly aggregates".
- [MINOR] terrainPopup.ts: narrow TerrainPointUnavailable type (no more `as unknown as TerrainResponse`), status default 'LIVE'→'UNKNOWN' (amber), failed state shows held elevation as "(grid cell)", computed_at escaped.
- [MINOR] WEATHER_LAYER_ORDER gained wind_gusts_10m (was only reachable via Extreme-wind hazard); order test updated.
- [MINOR] Dead `toFixed(... ? 1 : 1)` in weatherLayers.formatVariableValue + HistoricalPointPanel.value → real decimals rule (1 for mm/°C, 0 otherwise).
- [MINOR] completed_through_month `|| 12` (0→Dec) → `?? 12`.
- [MINOR] DateControl date input min now bounds to the selected month (was year-01-01 → selecting another month snapped back).
- [MINOR] Removed unused Crosshair, DataLayerStatus, TerrainResponse imports.
- Deferred by design/pre-existing: withinCompleted (tested lib helper, harmless), flood step 0.15 vs 0.3 (pre-existing), storm_indicator legend wording, dataSource live-optional being a visible dead-end (approved spec + honest amber note in panel), 300ms click debounce.

Re-verification: tsc 0, vitest 88/88, dev server restarted, E2E 5/5 green (p_weather_v2 now also asserts month refetch; p_gis_terrain asserts immediate honest resolution + second-click swap; p7 + p_citizen + p_weather_map unchanged green). Backend untouched.

## Backend extension: per-day ERA5 grids + real caching (Tasks B1–B3)

B1 (per-day grid): complete and green. historical_weather.py: `_DAILY_COLUMNS` += apparent_temperature_mean/cloud_cover_mean; `GRID_AGGREGATES` += apparent_temperature/cloud_cover; unavailable = {precipitation_probability, relative_humidity, visibility}; new `PER_DAY_ONLY_GRID_VARIABLES` = {wind_direction_10m, wind_u, wind_v}; `_POINT_UNITS` += apparent/cloud; `_aggregate_rows` computes the two new monthly means. Transport refactor: `_fetch_archive_block` (shared) + `_fetch_month_daily`/`_fetch_day_daily` wrappers (start=end=YYYY-MM-DD). `fetch_grid` gains `day: int = 0` (pre-session): day=0 monthly, day 1..N per-day; ValueError for day<0 / day>monthrange; per-day-only vars in monthly → honest UNAVAILABLE with "per-day" reason, no network. `_fetch_grid_day` + `_day_cell_value` (accumulation = real month-to-date cumsum; wind u/v = km/h→m/s, u=-ws·sin, v=-ws·cos, `_round2` 2dp), `_DAY_AGGREGATION`/`_DAY_ONLY_UNITS`. Tests: 29/29 era5; full 329 + 1 intentional TN failure.

B2 (real caching): complete and green. models.py `HistoricalWeatherSample` += `data_day` in column/UniqueConstraint/ix_hist_weather_cell_period; migration `007_historical_weather_day.py`; provider started `TTLCache(config.HISTORICAL_WEATHER_CACHE_TTL_SEC, max_entries=16384)`; old `_read_cached_cell_values`/`_write_cached_cell_values` → `_read_cached_grid_values` (DB+memory merge), `_read_db_grid_values` (tuple_ IN on (lat,lng)), `_write_cached_grid_value` (memory + DB upsert incl. data_day; computed_at as real datetime — the string`datetime` bug that made the pre-existing cache never persist was the actual root cause; the write used a str but the column is a SQLite DateTime), `_cached_grid_point`, `_grid_cell_key`, `_grid_cache_key`. Month loop + `_fetch_grid_day` rewritten cache-aware (single-row per variable/cell; monthly data_day=0, per-day data_day=N). Tests: 3 new cache tests (repeat no-upstream, DB day, DB monthly) → 32/32 era5; full 335 + 1 intentional TN failure.

B3 (route + point fix): complete and green. integration_routes.py `weather_grid`: shared `day` Query ge=0 le=31 (desc updated); year Query bounds tightened 2000–2100 → config.HISTORICAL_YEAR_MIN/MAX (2022–2026 — matches UI year range); historical branch now rejects hour/forecast_time/prefer only (day 0..N allowed) and passes `day=` through; live branch explicit `day > 7 → 400` ("Live forecast grids accept day 0..7."). `fetch_grid` still raises ValueError→400 for day out of month range. historical_weather.py `fetch_point_month`: top_rain_day.date now the actual wettest day's date (argmax over precipitation_sum), not day 1 of the month. Tests: +officer day-route / day-out-of-month-400 / live-day>7-400 / top_rain_day.date assert → 35/35 era5; full 335 + 1 intentional TN failure.

## Remaining (frontend per approved design)
Tasks B4–B8 (WeatherMap day-mode grid refetch, playback, historical wind particles, date flows via DateControl/historicalDates, honest badges/caption/Live Provider chip, weatherLayers 12 layers, popup from cache) not yet started.

## Frontend: per-day playback + historical wind (Tasks B4–B8)

Complete and green.
- api.ts `getWeatherGrid`: historical mode now also sends `day` (0 = whole-month aggregate, N = that day) and the client cache key uses the real day (was hard-coded `-1`) so month/day modes never collide.
- WeatherMap: `fetchGrid` passes `day = dayMode === 'daily' ? historicalDay : 0` in historical mode (deps += dayMode/historicalDay) → Daily view refetches the raster for that single day. Wind active when `!isHistorical || dayMode==='daily'`; wind build fetches speed+dir with historical `day/year/month` (getWeatherGrid drops `prefer` in historical, matching the route guard); deps include historicalDay. Wind toggle panel now shows in historical Daily mode. Sources panel Period + per-row copy reflect `Day N · fmtDateLabel(...)` in daily mode vs month aggregate otherwise; top historical caption updated ("Monthly shows aggregate; Daily plays back that single day; wind particles available per day").
- weatherLayers.ts: `HISTORICAL_GRID_VARIABLES` now the 9 real monthly aggregates (incl. apparent_temperature, cloud_cover); new `HISTORICAL_PER_DAY_VARIABLES` = {wind_direction_10m, wind_u, wind_v}; `isHistoricalVariableAvailable(v, daily)` gates per-day-only wind fields behind Daily view; `apparent_temperature` + `pressure_msl` lost `currentOnly` (both are real ERA5 monthly aggregates). Layer select uses `isHistoricalVariableAvailable(id, dayMode === 'daily')`.
- DateControl doc comment corrected (the choice now drives the raster, not just the popup).
- Tests: api.test + historical per-day request-shape test (year+month+day, no prefer/hour); weatherLayers.test + 3 availability-gate tests. tsc 0, vitest 92/92, npm run build ok.
- Dev DB migrated by hand (alembic not installed in this env; app uses create_all on startup): `ALTER TABLE historical_weather_samples ADD COLUMN data_day INTEGER NOT NULL DEFAULT 0`, table dropped & recreated (was empty, 0 rows) so the unique constraint carries data_day; uvicorn(8000) + vite DISABLE_HMR(3000) restarted.
- E2E probes 6/6 green: p_weather_v2 extended with per-day playback assertions — 'day-click-refetches-per-day-grid' (advance day → real `/api/weather/grid?...month=6...day=N` fired), 'day-label-updates-after-advance', 'daily-grid-settles-honestly'; p_gis_terrain 9/9, p_weather_map 14/14, p7_acceptance 13/13, p_citizen_no_weather 9/9.
- Backend final: 335 passed + 1 intentional failure (Tamil Nadu live-or-honest-rainfall probe — baseline unchanged, backend untouched since B3).

Final review: pending — T8 fresh-reviewer pass before branch close.

## Final review (B8) — fresh-reviewer pass + triaged fixes (all verified)

Reviewer found 3 MAJORs + 8 MINORs + 5 NITs; every fix below was verified (tests + E2E).

Fixed:
- [MAJOR] WeatherMap month `<select>` never reset `historicalDay` → switching month while on Daily day 31 caused a 400 blaming invalid bounds. Fixed: `setHistoricalDay(1)` alongside `setHistoricalMonth` (matches MonthTimeline).
- [MAJOR] Wind-particle effect deps omitted `historicalYear/historicalMonth` → stale particles under a new period label. Fixed deps; verified particles refetch.
- [MAJOR] `_fetch_archive_block` accepted ragged upstream records → blended neighbouring-cell/day values became cacheable HISTORICAL numbers. Fixed: per-record length validation (`ragged daily data` → HttpFetchError → honest UNAVAILABLE, nothing cached). New test.
- [MINOR] Per-day-only-layer tooltip claimed direction/U/V "not in the archive" (false). Now honest: "archived per-day only — switch to Daily view"; always-unavailable vars say "not exposed by the ERA5 daily archive — never substituted".
- [MINOR] Sources footer always said "monthly aggregates"; now day-aware. Legend `historicalLabel` also shows the exact day in Daily mode.
- [MINOR] Wind provenance hard-coded "(hour 0 run)" on reanalysis days → now "derived from that day's archived speed+direction (ERA5 reanalysis)".
- [MINOR] Every daily grid was labelled "per-day values" even for month-to-date accumulation. Now surfaces the real `data_provenance.aggregation` (e.g. `month_to_date_total`).
- [MINOR] `_write_cached_grid_value` silently swallowed DB write failures → now `logger.exception` (DB cache degrades visibly instead of silently failing).
- [MINOR] Day-route test could be served from the singleton's process cache (stub dead). Added `_grid_cache.clear()` so the route genuinely exercises the transport.
- [MINOR] `top_rain_day.date` test was satisfiable by the old bug. Added mid-month-unique-max stub test (`2025-06-17`) + dry-month test (`None`).
- [MINOR] In-memory cache test repeated the same day (couldn't catch a day-less key). Added day-variant test (day 13 vs 12 → 2 fetches, distinct values, day 13 still cached).
- [NIT] Stale WeatherMap comment about "bogus first-of-month" top_rain updated.
- Backend `top_rain_day`: dry/no-rain months now honestly return `None` (was `{date: day-01, mm: 0.0}`); unreachable fallback removed.

Verified (B8 re-run): era5 suite 39/39, full backend 339 passed + 1 intentional failure (TN rainfall probe), tsc 0, vitest 92/92, npm run build ok, dev servers restarted (uvicorn 8000 + vite DISABLE_HMR 3000), E2E p_weather_v2 24/24 (incl. day-click-refetches-per-day-grid) + p_weather_map 14/14 green.

Branch status: COMPLETE. T1 (per-day backend) → T2 (real caching) → T3 (route) → T4/T5/T6/T7 (frontend playback + wind + gating + honest copy) → T8 (verification + review) all done and verified.

## CHANGE (B9) — Historical Weather Map visible on ALL portals (8 roles)

User directive: make the read-only Historical Weather Map visible to every user portal (Citizen, Field, Local, Sub-District, District, State, Admin, Super Admin as `admin`); add a `weather.history.read` permission granted to all roles; keep live weather disabled; keep live-provider configuration administrative-only; touch nothing else (GIS/terrain/census/evacuation/auth).

Decisions: `super_admin` does not exist → `admin` covers Admin + Super Admin. `local_office` was backend-only → new frontend persona added.

Backend:
- `access_control.py`: `weather.history.read` added to all 8 role sets.
- `integration_routes.py`: `weather_access` gate now requires `weather.history.read` instead of `map.read_public` + citizen 403. Every weather/rainfall read endpoint is reachable by every role.
- `weather_platform.py`: `weather_api_status` dropped the `NOT_FOR_ROLE` citizen leg (all roles have the weather feature; live stays API_NOT_ADDED when disabled).
- Tests: replaced `test_citizen_blocked_on_every_weather_route` with `test_citizen_can_read_historical_weather` (years/point/grid + rainfall 200) and `test_citizen_live_point_is_honest_not_403` (API_NOT_ADDED); `test_access_control.py` asserts every role holds `weather.history.read`; stale citizen-gate docstrings in conftest/test_multi_state/test_weather_era5 updated.

Frontend:
- `types/index.ts`: `UserRole` += `local_office`.
- `Sidebar.tsx`: `weather` nav roles now include `normal_citizen` + `local_office` (all 8 portals); `local_office` also added to map/alerts/risk_intelligence/evacuation/field_reports.
- `mockData.ts`: `local_office` persona `usr-local-005` (Mahesh Bisht, `local`/`local123`) mirroring the backend seed user.
- `Navbar.tsx` role badge + `AdminPage.tsx` role description: `local_office` cases.
- Weather page → `WeatherMap` → `WeatherSettingsPanel` → `LiveProviderPanel`: new `canManageLiveProviders` prop threaded from App (`userRole === 'admin'`); add/remove provider controls render only for admins, everyone else sees an honest "restricted to administrators" note (guarded so a stale open form can't render for non-admins).
- `RiskIntelligencePage.tsx`: citizen reason no longer claims citizens lack the weather feature (now: historical weather is on the Weather Map; live point-science stays citizen-restricted).

Verified: backend 341 passed + 1 intentional failure (TN rainfall probe, baseline); era5 suite 40/40; tsc 0; vitest 92/92; npm run build ok; dev servers restarted. E2E: new `p_all_roles_weather.cjs` 89 checks green across all 8 personas (Weather Map nav present, historical grid settles 200, zero live point calls, zero weather 4xx, provider config admin-only); updated `p_citizen_no_weather.cjs` 10/10; regression `p_weather_v2` 24/24 + `p_weather_map` 14/14 green.

Branch status (B9): COMPLETE and verified.

## CHANGE (B10) — Role portals / header UI fix (dev-only persona switcher + anti-stall loading)

Reported: non-citizen portals (Field Officer, Local Authority, Sub-District, District, State, Admin/Super Admin) showed a "Switch Test Persona / Role" dev dropdown on the normal UI that overlapped the header/content, plus portals could remain stuck on "Loading...". Citizen portal is the untouched reference portal; mandated to keep weather map on all roles (2022–2026) and to never hide errors.

Root causes:
- The developer persona switcher was always rendered for non-citizens regardless of build. It's a dev/test aid → gate behind `import.meta.env.DEV`. Production/published builds now show the static profile + a plain Sign out button; citizen branch untouched.
- The dropdown was absolutely positioned from its own content-height `relative` wrapper (the right-side group is a flex item centered by `items-center`, so the wrapper bottom sat ~9px above the header bar's bottom edge) → `top-full` placed it overlapping the header + content. Fixed by anchoring to the `sticky` header (the nearest positioned ancestor, full 93.3px bar): the wrapper no longer carries `relative`, so `top-full mt-2` starts strictly below the header (menu y=100 ≥ header bottom 93.3).
- Loading could hang forever when the backend stalls: every data request had no timeout and `fetchRegionData` had no deadline that cleared the spinner. Now every outbound call goes through `fetchWithTimeout` (AbortController + caller-signal merge; `API_FETCH_TIMEOUT_MS = 25s`) and `fetchRegionData` declares an honest failure after `REGION_LOADING_DEADLINE_MS = 35s` (stale-safe via fetch-seq guard) → LOADING → ERROR with a visible `[data-load-error-banner]`, never an infinite spinner.

Implementation (all TDD, red → green):
- `src/services/api.ts`: `API_FETCH_TIMEOUT_MS`, exported `fetchWithTimeout(url, init, ms)`; applied to `doFetch` + all plain `fetch(` sites (16) incl. `loginToBackend` auth fetches; the only raw `fetch(` left is inside `fetchWithTimeout`.
- `src/App.tsx`: `loadError` state; `REGION_LOADING_DEADLINE_MS`; deadline timer in `fetchRegionData` (sequenced); honest error banner in `<main>`; `handleSignOut`; Navbar `onSignOut`.
- `src/components/Navbar.tsx`: `enableTestPersonaSwitcher = import.meta.env.DEV` (optional prop), `onSignOut`; outside-click (mousedown) + Escape close; dev branch = persona switcher (`#role-switcher-dropdown-btn`, menu `#role-switcher-menu`, `max-h-[65vh] overflow-y-auto`, `right-0`, anchored below the sticky header); prod branch = static profile + `#sign-out-btn`; citizen branch unchanged.
- `src/pages/DashboardPage.tsx`: sticky control-bar wrapper now `-mx-4 px-4 sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8` (flush with content padding at each breakpoint); live-batch loading `.finally(seq-guard)` so the control-bar spinner can't stick.
- `src/vite-env.d.ts`: `/// <reference types="vite/client" />` (needed for `import.meta.env.DEV` typing).
- Tests: `api.test.ts` "Request timeout contract" (4 tests; never-responding fetch → AbortError; prompt fetch → resolves + timer cleared; stalled dashboard summary → `data_status:'UNAVAILABLE'`; stalled disaster events → 'aborted'); `Navbar.test.tsx` dev/prod/citizen static-render gating. (fake-timer timeout tests pre-attach assertions to avoid vitest unhandled-rejection artifacts.)

Verified:
- tsc 0; vitest 99/99 (10 files); `npm run build` ok (40.9s, chunk-size warning only).
- Dev E2E `p_e2e_roleportals.cjs` 30/30: all 8 roles land correctly (dashboard roles → "Command Center", map roles → `#gis-map-view`); switcher present for the 7 non-citizens in dev, absent for citizen; weather map + `#weather-historical-badge` mount for admin/field/citizen; dropdown inside viewport horizontally, height clamped 482px ≤ 65vh, starts below the header (y=100 ≥ 93.33), closes on outside click / Escape / persona selection; admin→citizen switch → static profile; stalled-backend case shows the honest degraded-data banner (LOADING ends ~36s, never infinite).
- Prod-build E2E `p_e2e_prod.cjs` 9/9 (vite preview 4173, dist, no proxy): non-citizens have NO `#role-switcher-dropdown-btn`, have `#sign-out-btn`; sign-out returns to AccessGate; citizen static + weather/historical badge intact; honest degraded-data banner instead of infinite spinner.
- Debug note: the pre-fix dropdown overlap and a "stuck loading" false-failure were both probe artifacts/investigated via instrumented probes (`p_geom_probe.cjs` CSS/flexbox inspection → anchor fix; `p_stall_probe.cjs` 2s polling showed the 35s deadline fires; waited on this before finalizing). Backend untouched.

Branch status (B10): COMPLETE and verified.