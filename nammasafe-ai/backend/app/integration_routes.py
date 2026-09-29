"""SAFE_MOVE_AI live-intelligence API router.

Mounted under the main FastAPI app. All heavy lifting is delegated to the
provider services so this module stays a thin contract layer.

Auth model:
  * public / read endpoints  -> map.read_public  (every role incl. citizens)
  * safe-route planning      -> evacuation.read  (route planning is decorative
                                UI on top of the existing evacuation module)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_permissions
from app import config
from app import weather_platform
from app.bhuvan_service import bhuvan_service
from app.database import get_db
from app.disaster_events import get_disaster_events, get_disaster_events_near
from app.flood_service import flood_service
from app.geocode_service import geocode_service
from app.historical_weather import (
    HISTORICAL_GRID_VARIABLES,
    available_periods,
    completed_through_month_for_year,
    current_year,
    historical_weather,
)
from app.nearby_places import NearbyPlacesService, nearby_places_service, SUPPORTED_KINDS
from app.rainfall_service import rainfall_service
from app.risk_assessment_service import RiskAssessmentService
from app.routing_service import routing_service
from app.safe_location_service import safe_location_service
from app.schemas import (
    BhuvanGeoidResponse,
    BhuvanHospitalsResponse,
    BhuvanLulcResponse,
    BhuvanReverseGeocodeResponse,
    BhuvanShortestPathRequest,
    BhuvanShortestPathResponse,
    BhuvanVillageGeocodeResponse,
    DataCatalogResponse,
    DisasterEventsResponse,
    FloodRiskGridResponse,
    FloodRiskResponse,
    GeocodeResponse,
    HistoricalWeatherResponse,
    HistoricalWeatherYearsResponse,
    NearbyPlacesResponse,
    RainfallGridResponse,
    RainfallResponse,
    RecalculateRequest,
    RiskAssessmentResponse,
    RiskZonesResponse,
    SafeLocationsResponse,
    SafeRoutesResponse,
    TerrainGridResponse,
    TerrainResponse,
    WeatherGridResponse,
    WeatherResponse,
)
from app.flood_risk_overlay import get_flood_risk_grid
from app.data_catalog import build_data_catalog
from app.terrain_service import terrain_service
from app.weather_service import GRID_VARIABLES, weather_service

DEFAULT_HABITATIONS = 80


def build_integration_router(data_provider: Callable[[], Dict[str, Any]]) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["safe-move-ai"])

    assessment_service = RiskAssessmentService()

    def weather_access(user: dict = Depends(require_permissions("weather.history.read"))) -> dict:
        """Read gate for weather/rainfall endpoints.

        weather.history.read is granted to every role (the read-only Historical
        Weather Map is visible on all portals, citizens included), so this
        blocks nobody today. It exists so a future role that lacks the
        permission is refused even if a stale client fires the request. Live
        weather remains optional and disabled — the map serves historical ERA5."""
        return user

    # ---------------- Weather / Rainfall / Flood / Terrain ----------------
    # NOTE: the literal /weather/grid and /weather/forecast routes MUST be
    # declared before the parameterised /weather/{latitude}/{longitude} route
    # or "grid"/"forecast" would be captured as the latitude segment.

    @router.get("/weather/grid", response_model=WeatherGridResponse)
    def weather_grid(
        bounds: str = Query(
            ...,
            description="India grid window 'north,south,east,west' (clamped to India internally).",
        ),
        step: float = Query(config.WEATHER_GRID_STEP, ge=0.01, le=0.5),
        max_points: int = Query(config.WEATHER_GRID_MAX_POINTS, ge=1, le=600),
        variable: str = Query("temperature_2m", description="Grid layer variable"),
        layer: Optional[str] = Query(None, description="Alias for `variable`"),
        day: int = Query(
            0,
            ge=0,
            le=31,
            description="0 = current conditions (live) or the whole completed month (historical); "
            "1..7 = that live forecast day; 1..N = that day of the completed historical month",
        ),
        hour: Optional[int] = Query(
            None,
            ge=0,
            le=47,
            description="Intraday hour offset from now (0..47). When set, serves the hourly "
            "block at +hour instead of the daily `day` block.",
        ),
        forecast_time: Optional[str] = Query(
            None,
            description="ISO 8601 UTC timestamp; resolved to the nearest hourly stop (0..47). "
            "Cannot be combined with `hour`.",
        ),
        prefer: str = Query(
            config.WEATHER_PREFERRED_PROVIDER,
            pattern="^(auto|ecmwf)$",
            description="Provider chain: 'auto' (Open-Meteo first) or 'ecmwf' (ECMWF IFS 0.25° first).",
        ),
        year: Optional[int] = Query(
            None,
            ge=config.HISTORICAL_YEAR_MIN,
            le=config.HISTORICAL_YEAR_MAX,
            description="Historical year. When set the grid is served from the ERA5 archive "
            f"for that year+month (completed months only, {config.HISTORICAL_YEAR_MIN}..{config.HISTORICAL_YEAR_MAX}) "
            "— never from the live chain.",
        ),
        month: Optional[int] = Query(
            None,
            ge=1,
            le=12,
            description="Historical month (1..12). Only completed months are served; the "
            "current month is returned honestly as UNAVAILABLE until it completes.",
        ),
        user: dict = Depends(weather_access),
        db: Session = Depends(get_db),
    ):
        resolved_variable = layer or variable
        historical_mode = year is not None
        if historical_mode:
            if resolved_variable not in HISTORICAL_GRID_VARIABLES:
                raise HTTPException(
                    status_code=400,
                    detail=f"variable for historical grids must be one of {', '.join(HISTORICAL_GRID_VARIABLES)}.",
                )
            if month is None:
                raise HTTPException(
                    status_code=400,
                    detail="month is required when year is set (1..12, completed month).",
                )
            if hour is not None or forecast_time is not None or prefer != config.WEATHER_PREFERRED_PROVIDER:
                raise HTTPException(
                    status_code=400,
                    detail="Historical grids accept day=0 (whole completed month) or day 1..N "
                    "(that day's per-day grid); hour/forecast_time/prefer apply to live grids only.",
                )
        else:
            if resolved_variable not in GRID_VARIABLES:
                raise HTTPException(
                    status_code=400,
                    detail=f"variable must be one of {', '.join(GRID_VARIABLES)}.",
                )
            if month is not None:
                raise HTTPException(status_code=400, detail="month is only valid together with year (historical mode).")
            if hour is not None and forecast_time is not None:
                raise HTTPException(
                    status_code=400,
                    detail="Provide either `hour` (0..47 offset) or `forecast_time` (ISO UTC), not both.",
                )
            if day > 7:
                raise HTTPException(
                    status_code=400,
                    detail="Live forecast grids accept day 0..7.",
                )
        try:
            parts = [float(part) for part in bounds.split(",")]
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="bounds must be four numeric values 'north,south,east,west'.",
            )
        if len(parts) != 4:
            raise HTTPException(
                status_code=400,
                detail="bounds must be 'north,south,east,west'. Resolve bounds from the selected region.",
            )
        north, south, east, west = parts
        if south >= north or east <= west:
            raise HTTPException(
                status_code=400,
                detail="Invalid bounds: south must be < north and west must be < east.",
            )
        if historical_mode:
            try:
                return historical_weather.fetch_grid(
                    north,
                    south,
                    east,
                    west,
                    step=step,
                    max_points=max_points,
                    variable=resolved_variable,
                    year=int(year or 0),
                    month=int(month or 0),
                    day=int(day),
                    session=db,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
        try:
            return weather_service.get_grid_samples(
                north,
                south,
                east,
                west,
                step=step,
                max_points=max_points,
                variable=resolved_variable,
                day=day,
                hour=hour,
                forecast_time=forecast_time,
                prefer=prefer,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.get("/weather/forecast", response_model=WeatherResponse)
    def weather_forecast(
        latitude: float = Query(..., ge=-90, le=90, description="Point latitude"),
        longitude: float = Query(..., ge=-180, le=180, description="Point longitude"),
        days: int = Query(config.WEATHER_FORECAST_DAYS, ge=1, le=7),
        user: dict = Depends(weather_access),
    ):
        return weather_service.get_weather(latitude, longitude, days=days)

    @router.get("/weather/{latitude}/{longitude}", response_model=WeatherResponse)
    def weather(
        latitude: float,
        longitude: float,
        days: int = Query(config.WEATHER_FORECAST_DAYS, ge=1, le=7),
        user: dict = Depends(weather_access),
    ):
        return weather_service.get_weather(latitude, longitude, days=days)

    @router.get("/weather/{latitude}/{longitude}/historical", response_model=HistoricalWeatherResponse)
    def weather_historical_point(
        latitude: float,
        longitude: float,
        year: int = Query(..., ge=config.HISTORICAL_YEAR_MIN, le=config.HISTORICAL_YEAR_MAX,
                          description="Historical year (ERA5 archive)."),
        month: int = Query(..., ge=1, le=12, description="Historical month (1..12, completed months only)."),
        user: dict = Depends(weather_access),
    ):
        """Completed-month historical summary for a point — ERA5 reanalysis,
        labelled HISTORICAL with full provenance (never a live observation)."""
        return historical_weather.fetch_point_month(latitude, longitude, year, month)

    @router.get("/historical/weather/years", response_model=HistoricalWeatherYearsResponse)
    def historical_weather_years(
        user: dict = Depends(weather_access),
    ):
        """Year availability for the historical weather selector: every supported
        year plus the completed-month bound for the current year."""
        return {
            "availability": available_periods(),
            "current_year": current_year(),
            "completed_through_month": completed_through_month_for_year(current_year()),
            "provider": historical_weather.provider_identity(),
            "provenance": (
                "Historical weather is ERA5 reanalysis (ECMWF) served by the Open-Meteo "
                "archive API. Only completed months are exposed; every payload is labelled "
                "HISTORICAL and carries source/year/period provenance."
            ),
        }

    @router.get("/rainfall/{latitude}/{longitude}", response_model=RainfallResponse)
    def rainfall(
        latitude: float,
        longitude: float,
        user: dict = Depends(weather_access),
    ):
        return rainfall_service.get_rainfall(latitude, longitude)

    @router.get("/rainfall-grid", response_model=RainfallGridResponse)
    def rainfall_grid(
        bounds: str = Query(..., description="north,south,east,west (required; the client resolves bounds from the selected region)"),
        step: float = Query(0.05, ge=0.01, le=0.2),
        max_points: int = Query(400, ge=1, le=600),
        user: dict = Depends(weather_access),
    ):
        try:
            parts = [float(part) for part in bounds.split(",")]
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="bounds must be four numeric values 'north,south,east,west'.",
            )
        if len(parts) != 4:
            raise HTTPException(
                status_code=400,
                detail="bounds must be 'north,south,east,west'. Resolve bounds from the selected region.",
            )
        north, south, east, west = parts
        return rainfall_service.get_grid_samples(
            north, south, east, west, step=step, max_points=max_points
        )

    @router.get("/terrain-grid", response_model=TerrainGridResponse)
    def terrain_grid(
        bounds: str = Query(..., description="north,south,east,west"),
        step: float = Query(0.05, ge=0.01, le=0.5),
        max_points: int = Query(400, ge=1, le=600),
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        """Real SRTM elevation + slope layer for the weather & hazard map
        (per-cell via the normal SRTM/fallback chain, DB+TLL cached)."""
        try:
            parts = [float(part) for part in bounds.split(",")]
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="bounds must be four numeric values 'north,south,east,west'.",
            )
        if len(parts) != 4:
            raise HTTPException(
                status_code=400,
                detail="bounds must be 'north,south,east,west'. Resolve bounds from the selected region.",
            )
        north, south, east, west = parts
        if south >= north or east <= west:
            raise HTTPException(
                status_code=400,
                detail="Invalid bounds: south must be < north and west must be < east.",
            )
        return terrain_service.get_terrain_grid(
            north, south, east, west, step=step, max_points=max_points
        )

    @router.get("/flood-risk-grid", response_model=FloodRiskGridResponse)
    def flood_risk_grid(
        bounds: str = Query(..., description="north,south,east,west"),
        step: float = Query(0.1, ge=0.05, le=0.5),
        max_points: int = Query(300, ge=1, le=400),
        year: Optional[int] = Query(
            None,
            ge=2000,
            le=2100,
            description="Historical year: when set the overlay is computed from ERA5 historical "
            "precipitation + storm days + SRTM terrain for that completed month.",
        ),
        month: Optional[int] = Query(None, ge=1, le=12, description="Historical month (completed months only)."),
        user: dict = Depends(require_permissions("map.read_public")),
        db: Session = Depends(get_db),
    ):
        """Transparent rule-based flood-risk overlay scoring, from real weather
        + SRTM terrain inputs. data_status CALCULATED, never fabricated. With
        year+month set it scores historical (ERA5) rainfall + SRTM terrain."""
        try:
            parts = [float(part) for part in bounds.split(",")]
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="bounds must be four numeric values 'north,south,east,west'.",
            )
        if len(parts) != 4:
            raise HTTPException(
                status_code=400,
                detail="bounds must be 'north,south,east,west'. Resolve bounds from the selected region.",
            )
        north, south, east, west = parts
        if south >= north or east <= west:
            raise HTTPException(
                status_code=400,
                detail="Invalid bounds: south must be < north and west must be < east.",
            )
        if year is not None and month is None:
            raise HTTPException(status_code=400, detail="month is required when year is set (historical overlay).")
        return get_flood_risk_grid(
            north, south, east, west, step=step, max_points=max_points,
            year=year, month=month, db=db,
        )

    @router.get("/flood-risk/{latitude}/{longitude}", response_model=FloodRiskResponse)
    def flood_risk(
        latitude: float,
        longitude: float,
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        return flood_service.get_flood_risk(latitude, longitude)

    @router.get("/terrain/{latitude}/{longitude}", response_model=TerrainResponse)
    def terrain(
        latitude: float,
        longitude: float,
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
            raise HTTPException(
                status_code=400,
                detail="latitude must be in [-90, 90] and longitude in [-180, 180].",
            )
        return terrain_service.get_terrain(latitude, longitude)

    @router.get("/elevation", response_model=TerrainResponse)
    def elevation(
        lat: float = Query(..., ge=-90, le=90),
        lon: Optional[float] = Query(None, ge=-180, le=180),
        longitude: Optional[float] = Query(None, ge=-180, le=180, description="alias for lon"),
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        """Elevation-only fast path (real SRTM, cached tile, no slope window).
        Use this for the progressive Terrain-map popup; call /api/terrain when
        slope/drainage is required. Elevation is real — never fabricated."""
        lng = lon if lon is not None else longitude
        if lng is None:
            raise HTTPException(status_code=400, detail="Provide lon (or longitude).")
        return terrain_service.get_elevation_fast(lat, lng)

    # ---------------- Nearby critical facilities ----------------
    @router.get("/nearby/{kind}", response_model=NearbyPlacesResponse)
    def nearby(
        kind: str,
        lat: float = Query(..., ge=-90, le=90),
        lng: float = Query(..., ge=-180, le=180),
        radius: Optional[float] = Query(None, gt=0, le=200),
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        if kind not in SUPPORTED_KINDS:
            raise HTTPException(status_code=400, detail=f"Unknown kind '{kind}'. Choose from {list(SUPPORTED_KINDS)}.")
        service = nearby_places_service
        if radius:
            from app.nearby_places import NearbyPlacesService

            service = NearbyPlacesService(radius_km=radius)
        return service.get_nearby(kind, lat, lng)

    # ---------------- Dynamic habitations (OSM-derived) ----------------
    # Habitations for any India location are resolved live from OpenStreetMap
    # villages/towns around the anchor point. Pilot seed habitations remain the
    # source only for the Chamoli pilot region (they ARE the real curationed
    # dataset). Nothing here is fabricated.
    @router.get("/habitations/dynamic")
    def dynamic_habitations(
        state: Optional[str] = Query(None),
        district: Optional[str] = Query(None),
        lat: float = Query(..., ge=-90, le=90),
        lng: float = Query(..., ge=-180, le=180),
        radius: float = Query(25, gt=1, le=200),
        limit: int = Query(60, ge=1, le=200),
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        service = nearby_places_service
        if radius and radius != config.NEARBY_RADIUS_KM_DEFAULT:
            service = NearbyPlacesService(radius_km=radius)
        payload = service.get_nearby("villages", lat, lng)

        habitations: List[Dict[str, Any]] = []
        for place in payload.get("places", [])[:limit]:
            habitations.append(
                {
                    "id": f"osm-{place.get('osm_type', 'node')}-{place.get('osm_id')}",
                    "village_code": f"osm-{place.get('osm_id')}",
                    "village_name": place.get("name") or f"Village {place['latitude']:.4f},{place['longitude']:.4f}",
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "state": state or "",
                    "district": district or "",
                    "population": None,
                    "priority_level": None,
                    "priority_score": None,
                    "is_dynamic_osm": True,
                    "source": "OpenStreetMap (Overpass API)",
                    "data_status": payload.get("data_status", "UNAVAILABLE"),
                    "distance_km": place.get("distance_km"),
                }
            )

        return {
            "habitations": habitations,
            "data_status": payload.get("data_status", "UNAVAILABLE"),
            "data_source": "OpenStreetMap (Overpass API)",
            "count": len(habitations),
            "center": payload.get("center"),
            "radius_km": payload.get("radius_km"),
            "reason": payload.get("reason"),
        }

    # ---------------- Geocoding (server-side) ----------------
    @router.get("/geocode", response_model=GeocodeResponse)
    def geocode(
        q: str = Query(..., min_length=3),
        limit: int = Query(3, ge=1, le=10),
        country: str = Query("in"),
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        return geocode_service.search(q, limit=limit, country=country)

    # ---------------- Bhuvan / ISRO (supporting geospatial layer) ----------------
    # Official Bhuvan v2 REST gateways, proxied server-side. Token stays in
    # backend/.env. Responses use the explicit data vocabulary:
    # AVAILABLE | CACHED | UNAVAILABLE | ERROR | LOCATION_MISMATCH. Static
    # datasets (census-2001, LULC) are annotated with their dataset year and are
    # never labelled LIVE. LOCATION_MISMATCH is surfaced when a census record
    # belongs to a different district than requested — never merged.

    @router.get("/bhuvan/village/geocode", response_model=BhuvanVillageGeocodeResponse)
    def bhuvan_village_geocode(
        village: str = Query(..., min_length=2),
        state: Optional[str] = Query(None),
        district: Optional[str] = Query(None),
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        return bhuvan_service.resolve_village(village, state=state, district=district)

    @router.get("/bhuvan/village/reverse-geocode", response_model=BhuvanReverseGeocodeResponse)
    def bhuvan_reverse_geocode(
        lat: float = Query(..., ge=-90, le=90),
        lng: float = Query(..., ge=-180, le=180),
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        return bhuvan_service.reverse_geocode(lat, lng)

    @router.get("/bhuvan/hospitals", response_model=BhuvanHospitalsResponse)
    def bhuvan_hospitals(
        lat: float = Query(..., ge=-90, le=90),
        lng: float = Query(..., ge=-180, le=180),
        buffer_m: int = Query(3000, ge=500, le=50000),
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        return bhuvan_service.get_hospitals(lat, lng, buffer_m=buffer_m)

    @router.get("/bhuvan/lulc", response_model=BhuvanLulcResponse)
    def bhuvan_lulc(
        lat: float = Query(..., ge=-90, le=90),
        lng: float = Query(..., ge=-180, le=180),
        year: str = Query("all", min_length=1),
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        return bhuvan_service.get_lulc_250k(lng, lat, year=year)

    @router.get("/bhuvan/lulc/aoi", response_model=BhuvanLulcResponse)
    def bhuvan_lulc_aoi(
        polygon_wkt: str = Query(..., min_length=12, description="WKT polygon, e.g. POLYGON((lon lat,...))"),
        year: str = Query("all", min_length=1),
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        return bhuvan_service.get_lulc_250k_aoi(polygon_wkt, year=year)

    @router.get("/bhuvan/lulc/50k", response_model=BhuvanLulcResponse)
    def bhuvan_lulc_50k(
        state_abbr: Optional[str] = Query(None, description="2-letter ISRO state code, e.g. UK / TN / AP"),
        district_code: Optional[str] = Query(None, description="4-digit ISRO district code (state(2)+district(2))"),
        year: str = Query("1112", min_length=1),
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        return bhuvan_service.get_lulc_50k(state_abbr=state_abbr, district_code=district_code, year=year)

    @router.get("/bhuvan/lulc/50k/aoi", response_model=BhuvanLulcResponse)
    def bhuvan_lulc_50k_aoi(
        geom_wkt: str = Query(..., min_length=12, description="WKT geometry for the AOI"),
        year: Optional[str] = Query(None),
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        return bhuvan_service.get_lulc_50k_aoi(geom_wkt, year=year)

    # Shortest path is a decorative assist over the existing evacuation planner;
    # the risk-classified SAFE/CAUTION route remains the authoritative result.
    @router.post("/bhuvan/shortest-path", response_model=BhuvanShortestPathResponse)
    def bhuvan_shortest_path(
        payload: BhuvanShortestPathRequest,
        user: dict = Depends(require_permissions("evacuation.read")),
    ):
        return bhuvan_service.get_shortest_path(payload.lat1, payload.lon1, payload.lat2, payload.lon2)

    @router.get("/bhuvan/geoid", response_model=BhuvanGeoidResponse)
    def bhuvan_geoid(
        tile_id: str = Query(..., min_length=1, description="CartoDEM tile id, e.g. cdnc43e"),
        datum: str = Query("elipsoid", pattern="^(elipsoid|geoid)$"),
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        return bhuvan_service.convert_geoid(tile_id, datum=datum)

    # ---------------- Safe routes ----------------
    @router.get("/routes/safe", response_model=SafeRoutesResponse)
    def routes_safe(
        origin_lat: float = Query(..., ge=-90, le=90),
        origin_lng: float = Query(..., ge=-180, le=180),
        dest_lat: float = Query(..., ge=-90, le=90),
        dest_lng: float = Query(..., ge=-180, le=180),
        user: dict = Depends(require_permissions("evacuation.read")),
    ):
        return routing_service.safe_routes(
            data_provider(),
            (origin_lat, origin_lng),
            (dest_lat, dest_lng),
        )

    # ---------------- Historical disaster events ----------------
    @router.get("/disaster-events", response_model=DisasterEventsResponse)
    def disaster_events(
        state: Optional[str] = Query(None),
        district: Optional[str] = Query(None),
        hazard_type: Optional[str] = Query(None),
        limit: int = Query(100, ge=1, le=500),
        db: Session = Depends(get_db),
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        return get_disaster_events(db, state=state, district=district, hazard_type=hazard_type, limit=limit)

    @router.get("/disaster-events/near", response_model=DisasterEventsResponse)
    def disaster_events_near(
        lat: float = Query(..., ge=-90, le=90),
        lng: float = Query(..., ge=-180, le=180),
        radius: Optional[float] = Query(None, gt=0, le=500),
        db: Session = Depends(get_db),
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        return get_disaster_events_near(db, lat, lng, radius_km=radius)

    # ---------------- Risk assessment ----------------
    # ---------------- Real-data catalog (Change 1) ----------------
    @router.get("/data-catalog", response_model=DataCatalogResponse)
    def data_catalog(
        db: Session = Depends(get_db),
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        """Every real dataset the platform can use, with status + provenance.
        Manifest lives in app.data_catalog (code, single source of truth);
        runtime state (provider toggles, ingested row counts) is derived live."""
        payload = build_data_catalog(db)
        payload["table_row_counts"] = {}
        from app.models import AdminBoundary, CensusVillage, DisasterEvent, HistoricalWeatherSample, TerrainSample
        for name, model in (
            ("admin_boundaries", AdminBoundary),
            ("census_villages", CensusVillage),
            ("historical_weather_samples", HistoricalWeatherSample),
            ("terrain_samples", TerrainSample),
            ("disaster_events", DisasterEvent),
        ):
            try:
                payload["table_row_counts"][name] = db.query(model).count()
            except Exception:
                payload["table_row_counts"][name] = 0
        return payload

    @router.get("/risk-assessment", response_model=RiskAssessmentResponse)
    def risk_assessment(
        lat: float = Query(..., ge=-90, le=90),
        lng: float = Query(..., ge=-180, le=180),
        state: Optional[str] = Query(None),
        district: Optional[str] = Query(None),
        village: Optional[str] = Query(None),
        place_label: Optional[str] = Query(None),
        year: Optional[int] = Query(
            None,
            ge=2000,
            le=2100,
            description="Historical year: when set, the rainfall signal uses ERA5 historical "
            "precipitation for that completed month instead of any live feed.",
        ),
        month: Optional[int] = Query(None, ge=1, le=12, description="Historical month (completed months only)."),
        force: bool = Query(False, description="Force recomputation (ignore TTL cache)"),
        db: Session = Depends(get_db),
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        data = data_provider()
        historical_month = None
        if year is not None:
            if month is None:
                raise HTTPException(status_code=400, detail="month is required when year is set (historical rainfall).")
            historical_month = historical_weather.fetch_point_month(lat, lng, year, month)
        return assessment_service.assess(
            db,
            lat,
            lng,
            place_label=place_label,
            state=state,
            district=district,
            village=village,
            field_reports=data.get("field_reports", []),
            historical_month=historical_month,
            force_recompute=force,
        )

    @router.post("/risk-assessment/recalculate", response_model=RiskAssessmentResponse)
    def risk_assessment_recalculate(
        payload: RecalculateRequest,
        db: Session = Depends(get_db),
        user: dict = Depends(require_permissions("evacuation.read")),
    ):
        """Re-run the assessment immediately (used after a field report lands)."""
        data = data_provider()
        return assessment_service.assess(
            db,
            payload.latitude,
            payload.longitude,
            place_label=payload.place_label,
            state=payload.state,
            district=payload.district,
            village=payload.village,
            field_reports=data.get("field_reports", []),
            force_recompute=True,
        )

    # ---------------- Risk zones (red-zone identification) ----------------
    @router.get("/risk-zones", response_model=RiskZonesResponse)
    def risk_zones(
        state: Optional[str] = Query(None),
        district: Optional[str] = Query(None),
        bounds: Optional[str] = Query(None, description="north,south,east,west"),
        granularity: str = Query("habitations", pattern="^(grid|habitations)$"),
        max_points: int = Query(DEFAULT_HABITATIONS, ge=1, le=500),
        db: Session = Depends(get_db),
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        data = data_provider()
        points = _zone_points(data, state, district, bounds, granularity, max_points)
        now = datetime.now(timezone.utc).isoformat()

        zones = []
        for latitude, longitude, label, population in points:
            assessment = assessment_service.assess(
                db,
                latitude,
                longitude,
                place_label=label,
                state=state,
                district=district,
                village=label,
                field_reports=data.get("field_reports", []),
            )
            if assessment.get("risk_score") is None:
                continue
            zones.append(
                {
                    "id": f"rz-{abs(hash((latitude, longitude))) % 10**10}",
                    "latitude": latitude,
                    "longitude": longitude,
                    "label": label,
                    "risk_score": assessment["risk_score"],
                    "risk_band": assessment["risk_band"],
                    "risk_level": assessment["risk_level"],
                    "assessment_mode": assessment["assessment_mode"],
                    "assessment_label": "AI-Assessed High-Risk Zone",
                    "hazards": _hazards_for(assessment),
                    "population_estimate": population,
                    "computed_at": assessment["computed_at"],
                }
            )

        zones.sort(key=lambda z: z.get("risk_score") or 0.0, reverse=True)
        return {
            "granularity": granularity,
            "data_status": "LIVE",
            "assessment_mode": zones[0]["assessment_mode"] if zones else "rule_based",
            "assessment_label": "AI-Assessed High-Risk Zone",
            "zones": zones,
            "computed_at": now,
        }

    # ---------------- Safe location engine ----------------
    @router.get("/safe-locations", response_model=SafeLocationsResponse)
    def safe_locations(
        lat: float = Query(..., ge=-90, le=90),
        lng: float = Query(..., ge=-180, le=180),
        affected_population: int = Query(0, ge=0),
        exclude_status: Optional[str] = Query(None, description="Comma-separated risk bands to exclude"),
        user: dict = Depends(require_permissions("map.read_public")),
    ):
        excluded = [item.strip().upper() for item in (exclude_status or "").split(",") if item.strip()]
        return safe_location_service.get_safe_locations(
            data_provider(),
            lat,
            lng,
            affected_population=affected_population,
            exclude_status=excluded or None,
        )

    return router


def _zone_points(
    data: Dict[str, Any],
    state: Optional[str],
    district: Optional[str],
    bounds: Optional[str],
    granularity: str,
    max_points: int,
) -> List[tuple]:
    def matches_region(h: Dict[str, Any]) -> bool:
        if state and h.get("state", "").lower() != state.lower():
            return False
        if district and h.get("district", "").lower() != district.lower():
            return False
        return True

    if granularity == "habitations":
        habitations = [h for h in data.get("habitations", []) if matches_region(h)]
        points = [
            (float(h["latitude"]), float(h["longitude"]), h["village_name"], h.get("population"))
            for h in habitations[:max_points]
        ]
        return points

    if not bounds:
        raise HTTPException(
            status_code=400,
            detail="bounds must be 'north,south,east,west' when granularity='grid'. Resolve bounds from the selected region.",
        )
    try:
        parts = [float(part) for part in bounds.split(",")]
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="bounds must be four numeric values 'north,south,east,west'.",
        )
    if len(parts) != 4:
        raise HTTPException(
            status_code=400,
            detail="bounds must be 'north,south,east,west'.",
        )
    north, south, east, west = parts
    step = 0.05
    points: List[tuple] = []
    lat = north
    while lat >= south and len(points) < max_points:
        lng = west
        while lng <= east and len(points) < max_points:
            points.append((round(lat, 5), round(lng, 5), f"Grid {lat:.3f}, {lng:.3f}", None))
            lng += step
        lat -= step
    return points


def _hazards_for(assessment: Dict[str, Any]) -> List[str]:
    hazards = []
    for factor in assessment.get("factors", []):
        if factor.get("impact") in ("ATTRIBUTABLE", "SEVERE"):
            hazards.append(factor["label"])
    if assessment.get("disaster_type"):
        hazards.append(f"Primary class: {assessment['disaster_type'].title().replace('_', ' ')}")
    return hazards