# plan2 — GIS Basemap Provider Fix & Upgrade
# Empirically verified 2025-09-14

## Problem
1. **Terrain broken**: Esri `World_Terrain_Base` serves identical 7,700-byte JPEG at z10–z16 (static placeholder, no per-zoom content)
2. **Hybrid weak**: Esri Reference Transportation/Boundaries_and_Places vanish at z14+ (2.6KB empty tiles at village zoom)

## Solution Provider Matrix (all FREE, no key, no billing)

| Mode | Provider | Why |
|---|---|---|
| STREET | Esri `World_Street_Map` (OSM fallback via tileerror) | 28KB z14, rich labels+roads+boundaries, Google-like |
| SATELLATE | Esri `World_Imagery` (unchanged) | Verified rich every zoom (62KB z16) |
| HYBRID | `World_Imagery` (base) + `World_Street_Map` overlay @ 60% opacity | Both EPSG:3857, labels locked to imagery, zoom-proportional |
| TERRAIN | Esri `World_Topo_Map` | 59KB z14, hillshade + contours + labels + roads |

## Files Changed
- `src/components/LeafletMap.tsx` — tile URLs, hybrid = LayerGroup(imagery + street overlay), terrain = topo map, tileerror fallback, failure banner
- `src/components/DataSourceStatus.tsx` — source strings
- `src/components/MapLayerPanel.test.tsx` — provider assertions
- `backend/app/flood_forecast.py` — data status source strings
- `evac-check.mjs` — E2E tile checks
