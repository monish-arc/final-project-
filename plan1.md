# GIS Basemap Upgrade Plan — plan1
## STREET / SATELLITE / HYBRID (Google Maps-like experience)

### Provider Strategy
- **Primary**: Google Maps Platform Map Tiles API (`lyrs=y` for hybrid)
- **Fallback**: Esri reference layers (free, no key) when `VITE_GOOGLE_MAPS_API_KEY` not set
- **Library**: Leaflet 1.9.4 (unchanged — supports Google ZXY tiles natively)

### Tile URL Reference
| Mode | Google `lyrs=` | Esri Fallback |
|---|---|---|
| STREET | `m` (roadmap) | OSM (current) |
| SATELLITE | `s` (satellite only) | Esri World Imagery (current) |
| HYBRID | `y` (satellite + labels) | Esri World Imagery + Reference/World_Transportation + Reference/World_Boundaries_and_Places |
| TERRAIN | `t` (terrain) | Esri World Terrain (current) |

### Google Tile URL Format
```
https://maps.googleapis.com/maps/vt?lyrs={type}&x={x}&y={y}&z={z}&key={API_KEY}
```
- Official Map Tiles API: https://developers.google.com/maps/documentation/tile
- Standard ZXY — native Leaflet compatibility, no library change
- API key security: HTTP referrer restriction (localhost + production domain)

### Files to Modify
1. `src/types/index.ts` — add `'hybrid'` + `'terrain'` to BasemapKey.id
2. `src/components/LeafletMap.tsx` — add hybrid/Google tileConfig with Esri fallback
3. `src/components/MapLayerPanel.tsx` — add hybrid + terrain buttons (4 total)
4. `src/components/DataSourceStatus.tsx` — add `google_map_tiles` label
5. `nammasafe-ai/backend/app/config.py` — add `GOOGLE_MAPS_API_KEY`
6. `nammasafe-ai/backend/app/flood_forecast.py` — add `google_map_tiles` to data status
7. `.env.example` — add `VITE_GOOGLE_MAPS_API_KEY=`
8. `.gitignore` — confirm `.env` listed
9. `src/components/MapLayerPanel.test.tsx` — update for hybrid basemap
10. E2E evac-check.mjs — add hybrid basemap switch check

### Dependencies
None — zero new npm/pip packages required.

### Environment Variables
```bash
# Frontend (.env — NOT committed to git)
VITE_GOOGLE_MAPS_API_KEY=your_key_here

# Backend (.env — NOT committed to git)
GOOGLE_MAPS_API_KEY=your_key_here
```

### Attribution
- Google: `Map data ©Google` (via Leaflet attribution option)
- Esri fallback: Already present in current code
- OSM: Already present in current code

### Performance
- Google `lyrs=y` is a single composite tile (imagery + labels) — no double-load
- Fallback Esri hybrid: 3 tile requests per viewport (imagery + transport + boundaries)
- Browser tile caching handles pan/zoom seamlessly

### Testing
- `tsc --noEmit` — type check
- `vitest` — MapLayerPanel renders hybrid button
- `pytest` — data-status returns google_map_tiles entry
- E2E Playwright — hybrid button click, satellite + labels visible, overlays preserved
