# NammaSafe AI - Architecture & Technical Specification

**Tagline**: *Proactive Red-Zone and Relocation Planning Platform*  
**Pilot Geography**: *Chamoli District, Uttarakhand, India* (Himalayan Alaknanda, Rishiganga, Dhauliganga, and Pindar Basins)

---

## 1. Executive Summary

**NammaSafe AI** is an AI-driven geospatial decision-support platform engineered for state and district disaster management authorities (USDMA, DDMA Chamoli, NDMA) in India. Mountainous regions experience compound disasters: seismic shifts, glacial lake outbursts (GLOFs), cloudbursts, debris flows, and chronic land subsidence (such as observed in Joshimath). 

Traditional disaster response is reactive. **NammaSafe AI** delivers proactive decision support by:
1. Identifying multi-hazard composite **Red Zones** across terrain layers.
2. Formulating objective **Relocation Priority Indices** for vulnerable habitations.
3. Calculating true multi-resource **Carrying Capacity** for safe destination sites.
4. Enabling **SafeShift Simulation** to model population transfers before physical resettlement.

---

## 2. High-Level System Architecture

```
+------------------------------------------------------------------------------------+
|                                PRESENTATION TIER                                   |
|  React 19 + TypeScript + Tailwind CSS + Lucide Icons + Recharts Data Visualizers   |
|  Interactive GIS Engine: Leaflet + OpenStreetMap + Multi-Layer GeoJSON Switcher    |
|  Role-Based Access: Admin | Disaster Officer | Field Officer | Viewer              |
+-----------------------------------------+------------------------------------------+
                                          | REST / JSON (JWT Bearer Token)
                                          v
+------------------------------------------------------------------------------------+
|                                APPLICATION TIER                                    |
|                       Python 3.11 FastAPI Async Microservice                       |
|                                                                                    |
|  +--------------------+  +----------------------+  +----------------------------+  |
|  | Multi-Hazard Engine|  | Vulnerability Engine |  | Relocation Priority Engine |  |
|  | 40% Landslide      |  | 35% Pop Density      |  | 50% Hazard Score           |  |
|  | 30% Flash Flood    |  | 25% Dependents Ratio |  | 30% Vulnerability Score    |  |
|  | 20% Extreme Rain   |  | 20% Poor Road Access |  | 20% Disaster History       |  |
|  | 10% Past Frequency |  | 20% Hospital Distance|  +----------------------------+  |
|  +--------------------+  +----------------------+                                  |
|                                                                                    |
|  +-------------------------------------+  +-------------------------------------+  |
|  | Site Suitability Evaluation Engine  |  | SafeShift Multi-Resource Capacity   |  |
|  | 30% Low Hazard + 20% Low Slope     |  | Min(Land, Water, School, Health,    |  |
|  | 15% Road + 15% Water + 10% School   |  |     Road Capacity)                  |  |
|  | + 10% Hospital Access               |  | Bottleneck Discovery & Alt Recomm.  |  |
|  +-------------------------------------+  +-------------------------------------+  |
+-----------------------------------------+------------------------------------------+
                                          | SQLAlchemy ORM / GeoAlchemy2
                                          v
+------------------------------------------------------------------------------------+
|                               PERSISTENCE TIER                                     |
|                       PostgreSQL 15 with PostGIS 3.3                               |
|                                                                                    |
|  - habitations (Point Geometry, GIST Spatial Index: idx_habitations_location)      |
|  - red_zones (MultiPolygon Geometry, GIST Spatial Index: idx_red_zones_geom)        |
|  - relocation_sites (Point Geometry, GIST Spatial Index: idx_relocation_sites_loc) |
|  - hazard_events, relocation_recommendations, field_reports, users                 |
+------------------------------------------------------------------------------------+
```

---

## 3. Mathematical Decision Support Models

### 3.1 Composite Hazard Score ($H_s$)
Measures total biophysical threat intensity in a habitation's drainage basin:
$$H_s = 0.40 \cdot R_{\text{landslide}} + 0.30 \cdot R_{\text{flood}} + 0.20 \cdot R_{\text{rainfall}} + 0.10 \cdot F_{\text{past}}$$
Where all sub-factors are normalized on a scale of $[0, 100]$.

### 3.2 Habitation Vulnerability Score ($V_s$)
Quantifies demographic exposure and evacuation friction:
$$V_s = 0.35 \cdot D_{\text{pop}} + 0.25 \cdot R_{\text{dependents}} + 0.20 \cdot (100 - A_{\text{road}}) + 0.20 \cdot D_{\text{hospital}}$$
- $R_{\text{dependents}} = \frac{\text{Children} + \text{Elderly}}{\text{Total Population}} \times 100$
- $D_{\text{hospital}} = \min\left(100, \frac{\text{Hospital Distance (km)}}{40} \times 100\right)$

### 3.3 Relocation Priority Index ($P$)
Synthesizes hazard, vulnerability, and historic empirical frequency:
$$P = 0.50 \cdot H_s + 0.30 \cdot V_s + 0.20 \cdot S_{\text{disaster\_history}}$$

**Administrative Decision Thresholds:**
| Priority Score ($P$) | Action Classification | Operational Directive |
| :--- | :--- | :--- |
| **75.0 - 100.0** | **Immediate Relocation** | Evacuation camp mobilization; high priority land parcel deed transfer |
| **50.0 - 74.9** | **Short-Term Relocation** | Pre-monsoon structured relocation; seasonal safety transit |
| **30.0 - 49.9** | **Medium-Term Relocation** | Slope stabilization, retaining walls, early warning sensors |
| **< 30.0** | **Monitor Only** | Regular GIS InSAR satellite monitoring and community drill |

### 3.4 Relocation Site Suitability ($S_{\text{site}}$)
$$S_{\text{site}} = 0.30 \cdot L_{\text{hazard}} + 0.20 \cdot F_{\text{slope}} + 0.15 \cdot A_{\text{road}} + 0.15 \cdot W_{\text{water}} + 0.10 \cdot E_{\text{school}} + 0.10 \cdot H_{\text{health}}$$

### 3.5 Carrying Capacity Bottleneck Principle
$$C_{\text{final}} = \min(C_{\text{land}}, C_{\text{water}}, C_{\text{school}}, C_{\text{health}}, C_{\text{road}})$$
A site cannot accommodate more families than its weakest infrastructure pillar allows.

---

## 4. Privacy & Ethical Guardrails

- **Zero PII**: No personal names, phone numbers, biometric identifiers, or Aadhaar details are collected or stored.
- **Village-Level Aggregation**: Data is strictly aggregated to Census Village / Habitation wards to prevent privacy exposure.
- **Synthetic Demonstration Base**: Pilot data is marked with clear metadata flags ensuring safety in public demonstration environments while retaining exact mathematical fidelity to official USDMA methodologies.

---

## 5. Bhuvan / ISRO Integration (Supporting Geospatial Layer)

The platform authenticates against the official **Bhuvan v2 REST gateways** (`https://bhuvan-app1.nrsc.gov.in/api`) as a *supporting* India-wide layer. It is additive only — it never replaces or weakens the verified live providers (Open-Meteo, Copernicus GloFAS, NASA GPM, OpenStreetMap) and never overrides the SAFE_MOVE_AI risk engine.

### 5.1 Services added

| Endpoint | Bhuvan upstream | Coverage / notes |
| :--- | :--- | :--- |
| `GET /api/bhuvan/village/geocode` | `curl_village_geocode.php` | Census-2001, AP & Karnataka. Returns **no coordinates** and says so — the `has_coordinates=false` + `coordinate_note` contract. `LOCATION_MISMATCH` is surfaced (never merged) when `dhq_name` disagrees with the requested district. |
| `GET /api/bhuvan/village/reverse-geocode` | `curl_reverse_village.php` | AP & Karnataka. |
| `GET /api/bhuvan/hospitals` | `curl_hos_pos_prox.php` | Andhra Pradesh only. |
| `GET /api/bhuvan/lulc` | `curl_lulc250k_point.php` | ISRO LULC 250K point class. |
| `GET /api/bhuvan/lulc/aoi` | `curl_lulc250k.php` | LULC 250K AOI breakdown. |
| `GET /api/bhuvan/lulc/50k` | `curljson.php` | LULC 50K district statistics (`distcode`/`statcode`). |
| `GET /api/bhuvan/lulc/50k/aoi` | `curl_aoi.php` | LULC 50K AOI statistics (WKT). |
| `POST /api/bhuvan/shortest-path` | `curl_routing_state.php` | Intra-state only. Decorative assist beside the risk-classified SAFE/CAUTION route. Requires `evacuation.read`. |
| `GET /api/bhuvan/geoid` | `curl_gdal_api.php` | **Download proxy only** (`proxy=true`). The documented API streams a CartoDEM tile; it is exposed as `download_endpoint` with a `height_note` stating no single-point height is fabricated. Elevation keeps NASA Earthdata SRTM. |

All reads require `map.read_public`. Upstream calls carry `Content-Type: application/x-www-form-urlencoded` (required by Bhuvan). Results are TTL-cached in-process; cache hits return `data_status: CACHED`.

### 5.2 Data-status vocabulary

`AVAILABLE | CACHED | UNAVAILABLE | ERROR | LOCATION_MISMATCH` — static/historical datasets are **never** labelled `LIVE`. Missing token → `UNAVAILABLE`; upstream >= 400 or transport failure → `ERROR`; locational disagreement → `LOCATION_MISMATCH`; no data / outside coverage → `UNAVAILABLE` with an explicit reason.

### 5.3 Risk-engine participation (opt-in)

The `lulc` and `geoid` factors exist in the engine as explicit `NOT_AVAILABLE` by default. Setting `BHUVAN_RISK_FACTOR=on` (and, for geoid, `BHUVAN_API_KEY`) lets them participate:
- `lulc` — heuristic surface-cover susceptibility mapped from the ISRO class (documented in `bhuvan_service.py::_LULC_SUSCEPTIBILITY`, default 30.0); weight 0.06.
- `geoid` — annotation-only `NOT_ATTRIBUTABLE` score (geoid offsets are vertical datum corrections, not hazards); weight 0.02.

### 5.4 Configuration (backend-only secrets)

`.env.example` (root) documents all `BHUVAN_*` variables. The token (`BHUVAN_API_TOKEN`) and key (`BHUVAN_API_KEY`) belong in gitignored `backend/.env` and are consumed only server-side — never forwarded to the browser bundle.

### 5.5 Frontend

Risk Intelligence shows a **Bhuvan / ISRO (Supporting)** card set (village census, LULC class, hospitals, intra-state route note) behind a "Query Bhuvan" button. `DataStatusBadge` maps `AVAILABLE→LIVE`, `CACHED→CACHED`, `RECENT→RECENT`, `ERROR`/`LOCATION_MISMATCH→UNAVAILABLE`. The GIS map adds a Bhuvan route polyline (violet dashed, from Risk Intelligence) and an optional thematic LULC WMS overlay (`https://bhuvan-vec2.nrsc.gov.in/bhuvan/wms`, layer `lulc:BR_LULC50K_1112`) labelled as historical land-cover.

### 5.6 Files changed

- Backend: `app/bhuvan_service.py` (new), `app/config.py`, `app/schemas.py`, `app/integration_routes.py`, `app/risk_assessment_service.py`, `app/flood_forecast.py`, `app/safe_location_service.py`.
- Tests: `tests/test_bhuvan_service.py`, `tests/test_bhuvan_routes.py` (new); `tests/test_risk_assessment_service.py` updated for the two new factors (key-set + missing-signal count 5).
- Frontend: `src/types/index.ts`, `src/services/api.ts`, `src/components/DataStatusBadge.tsx`, `src/components/MapLayerPanel.tsx`, `src/components/LeafletMap.tsx`, `src/pages/RiskIntelligencePage.tsx`, `src/pages/GisMapPage.tsx`, `src/App.tsx`.

### 5.7 Verification

`python -m pytest` (backend) — 213 passed; `npm run lint` (tsc) — clean; `vitest run` — 38 passed; `npm run build` — succeeds.
