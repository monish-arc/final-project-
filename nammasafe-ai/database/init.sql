-- ============================================================================
-- NammaSafe AI Database Initialization Script (PostgreSQL + PostGIS)
-- Pilot District: Chamoli, Uttarakhand, India
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. USERS
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) PRIMARY KEY,
    username VARCHAR(64) UNIQUE NOT NULL,
    email VARCHAR(128) UNIQUE NOT NULL,
    hashed_password VARCHAR(256) NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'viewer',
    full_name VARCHAR(128) NOT NULL,
    designation VARCHAR(128),
    department VARCHAR(128),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. HABITATIONS
CREATE TABLE IF NOT EXISTS habitations (
    id VARCHAR(64) PRIMARY KEY,
    village_code VARCHAR(32) UNIQUE NOT NULL,
    village_name VARCHAR(128) NOT NULL,
    district VARCHAR(64) NOT NULL DEFAULT 'Chamoli',
    state VARCHAR(64) NOT NULL DEFAULT 'Uttarakhand',
    population INTEGER NOT NULL,
    households INTEGER NOT NULL,
    children_count INTEGER DEFAULT 0,
    elderly_count INTEGER DEFAULT 0,
    hospital_distance_km DOUBLE PRECISION NOT NULL,
    road_access_score DOUBLE PRECISION DEFAULT 50.0,
    vulnerability_score DOUBLE PRECISION DEFAULT 50.0,
    hazard_score DOUBLE PRECISION DEFAULT 50.0,
    priority_score DOUBLE PRECISION DEFAULT 50.0,
    priority_level VARCHAR(64) DEFAULT 'Medium-Term Relocation',
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    landslide_risk DOUBLE PRECISION DEFAULT 50.0,
    flood_risk DOUBLE PRECISION DEFAULT 50.0,
    extreme_rainfall_risk DOUBLE PRECISION DEFAULT 50.0,
    past_disaster_frequency DOUBLE PRECISION DEFAULT 50.0,
    disaster_history_count INTEGER DEFAULT 0,
    notes TEXT,
    location GEOMETRY(Point, 4326)
);
CREATE INDEX IF NOT EXISTS idx_habitations_location ON habitations USING GIST (location);

-- 3. HAZARD EVENTS
CREATE TABLE IF NOT EXISTS hazard_events (
    id VARCHAR(64) PRIMARY KEY,
    habitation_id VARCHAR(64) REFERENCES habitations(id) ON DELETE CASCADE,
    hazard_type VARCHAR(64) NOT NULL,
    event_date VARCHAR(32) NOT NULL,
    intensity VARCHAR(128) NOT NULL,
    severity_level VARCHAR(32) DEFAULT 'High',
    affected_people INTEGER DEFAULT 0,
    houses_damaged INTEGER DEFAULT 0,
    deaths INTEGER DEFAULT 0,
    source_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. RED ZONES
CREATE TABLE IF NOT EXISTS red_zones (
    id VARCHAR(64) PRIMARY KEY,
    zone_name VARCHAR(128) NOT NULL,
    hazard_type VARCHAR(64) NOT NULL,
    risk_level VARCHAR(32) DEFAULT 'Critical',
    hazard_score DOUBLE PRECISION NOT NULL,
    data_source VARCHAR(128) NOT NULL,
    last_updated VARCHAR(32) NOT NULL,
    zone_geometry GEOMETRY(MultiPolygon, 4326)
);
CREATE INDEX IF NOT EXISTS idx_red_zones_geom ON red_zones USING GIST (zone_geometry);

-- 5. RELOCATION SITES
CREATE TABLE IF NOT EXISTS relocation_sites (
    id VARCHAR(64) PRIMARY KEY,
    site_name VARCHAR(128) NOT NULL,
    district VARCHAR(64) NOT NULL DEFAULT 'Chamoli',
    land_area_acres DOUBLE PRECISION NOT NULL,
    estimated_capacity INTEGER NOT NULL,
    current_occupancy_families INTEGER DEFAULT 0,
    water_score DOUBLE PRECISION DEFAULT 80.0,
    road_score DOUBLE PRECISION DEFAULT 80.0,
    school_score DOUBLE PRECISION DEFAULT 80.0,
    hospital_score DOUBLE PRECISION DEFAULT 80.0,
    low_hazard_score DOUBLE PRECISION DEFAULT 90.0,
    flat_land_score DOUBLE PRECISION DEFAULT 85.0,
    suitability_score DOUBLE PRECISION DEFAULT 85.0,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    land_capacity_families INTEGER DEFAULT 500,
    water_capacity_families INTEGER DEFAULT 500,
    school_capacity_families INTEGER DEFAULT 400,
    health_capacity_families INTEGER DEFAULT 450,
    road_capacity_families INTEGER DEFAULT 600,
    final_capacity_families INTEGER DEFAULT 400,
    available_capacity_families INTEGER DEFAULT 400,
    location GEOMETRY(Point, 4326)
);
CREATE INDEX IF NOT EXISTS idx_relocation_sites_location ON relocation_sites USING GIST (location);

-- 6. RELOCATION RECOMMENDATIONS
CREATE TABLE IF NOT EXISTS relocation_recommendations (
    id VARCHAR(64) PRIMARY KEY,
    habitation_id VARCHAR(64) REFERENCES habitations(id) ON DELETE CASCADE,
    relocation_site_id VARCHAR(64) REFERENCES relocation_sites(id) ON DELETE CASCADE,
    hazard_score DOUBLE PRECISION NOT NULL,
    vulnerability_score DOUBLE PRECISION NOT NULL,
    disaster_history_score DOUBLE PRECISION NOT NULL,
    final_priority_score DOUBLE PRECISION NOT NULL,
    priority_level VARCHAR(64) NOT NULL,
    recommended_families INTEGER DEFAULT 100,
    risk_reduction_percent DOUBLE PRECISION DEFAULT 80.0,
    explanation TEXT NOT NULL,
    status VARCHAR(32) DEFAULT 'Draft',
    created_at VARCHAR(64) NOT NULL
);

-- 7. FIELD REPORTS
CREATE TABLE IF NOT EXISTS field_reports (
    id VARCHAR(64) PRIMARY KEY,
    habitation_id VARCHAR(64) REFERENCES habitations(id) ON DELETE CASCADE,
    officer_id VARCHAR(64) REFERENCES users(id) ON DELETE CASCADE,
    report_type VARCHAR(64) NOT NULL,
    description TEXT NOT NULL,
    image_url TEXT,
    reported_at VARCHAR(64) NOT NULL,
    verified BOOLEAN DEFAULT FALSE,
    severity VARCHAR(32) DEFAULT 'High',
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL
);

-- 8. DISASTER EVENTS (curated historical provenance, India-wide)
-- Every row references a public source. Rows are seeds only; operators extend
-- the table via backend/scripts/seed_disaster_events.py (--dry-run supported).
CREATE TABLE IF NOT EXISTS disaster_events (
    id SERIAL PRIMARY KEY,
    name VARCHAR(256) NOT NULL,
    hazard_type VARCHAR(64) NOT NULL,
    event_date DATE NOT NULL,
    state VARCHAR(64) NOT NULL,
    district VARCHAR(128),
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    severity_level VARCHAR(32),
    affected_population INTEGER,
    fatalities INTEGER,
    damage_estimate_inr_crore DOUBLE PRECISION,
    description TEXT,
    source VARCHAR(128) NOT NULL,
    source_reference VARCHAR(512) NOT NULL DEFAULT '',
    data_status VARCHAR(32) NOT NULL DEFAULT 'HISTORICAL',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_disaster_event_name_date_source UNIQUE (name, event_date, source_reference)
);
CREATE INDEX IF NOT EXISTS ix_disaster_events_event_date ON disaster_events (event_date);
CREATE INDEX IF NOT EXISTS ix_disaster_events_hazard_type ON disaster_events (hazard_type);
CREATE INDEX IF NOT EXISTS ix_disaster_events_state ON disaster_events (state);
CREATE INDEX IF NOT EXISTS ix_disaster_events_district ON disaster_events (district);

-- SEED DEMO USERS
INSERT INTO users (id, username, email, hashed_password, role, full_name, designation, department)
VALUES
('usr-admin-001', 'admin', 'admin@nammasafe.gov.in', 'pbkdf2:sha256:admin123', 'admin', 'Dr. Rajeshwar Semwal', 'State Geotechnical Director & GIS Admin', 'Uttarakhand Disaster Management Authority (USDMA)'),
('usr-officer-002', 'officer', 'officer@nammasafe.gov.in', 'pbkdf2:sha256:officer123', 'disaster_officer', 'Smt. Priyanka Bhandari', 'District Emergency Operations Officer', 'DDMA Chamoli'),
('usr-field-003', 'field', 'field@nammasafe.gov.in', 'pbkdf2:sha256:field123', 'field_officer', 'Kavita Negi', 'Rapid Assessment Field Surveyor', 'Revenue & Geological Survey Wing'),
('usr-viewer-004', 'viewer', 'viewer@nammasafe.gov.in', 'pbkdf2:sha256:viewer123', 'viewer', 'Arun Rawat', 'Community Liaison & Public Auditor', 'Civil Defense Uttarakhand')
ON CONFLICT (id) DO NOTHING;

-- SEED HABITATIONS
INSERT INTO habitations (id, village_code, village_name, district, state, population, households, children_count, elderly_count, hospital_distance_km, road_access_score, vulnerability_score, hazard_score, priority_score, priority_level, latitude, longitude, landslide_risk, flood_risk, extreme_rainfall_risk, past_disaster_frequency, disaster_history_count, notes, location)
VALUES
('hab-joshimath', 'VIL-CHM-001', 'Joshimath (Subsidence Sector)', 'Chamoli', 'Uttarakhand', 16700, 3400, 2800, 2200, 4.5, 45.0, 82.5, 89.2, 86.8, 'Immediate Relocation', 30.5574, 79.5658, 95.0, 82.0, 88.0, 90.0, 7, 'Severe differential subsidence and crack widening across residential wards', ST_SetSRID(ST_MakePoint(79.5658, 30.5574), 4326)),
('hab-raini', 'VIL-CHM-002', 'Raini (Rishiganga Bank)', 'Chamoli', 'Uttarakhand', 1250, 240, 230, 190, 28.0, 25.0, 78.4, 93.5, 87.2, 'Immediate Relocation', 30.4851, 79.6974, 94.0, 98.0, 85.0, 95.0, 5, 'Rishiganga flash flood flashpoint with unstable lateral scree slopes', ST_SetSRID(ST_MakePoint(79.6974, 30.4851), 4326)),
('hab-tapovan', 'VIL-CHM-003', 'Tapovan (Dhauliganga)', 'Chamoli', 'Uttarakhand', 2400, 480, 390, 310, 22.0, 35.0, 74.0, 88.0, 81.2, 'Immediate Relocation', 30.4950, 79.6300, 88.0, 92.0, 84.0, 85.0, 4, 'Direct confluence inundation and landslide scree runouts', ST_SetSRID(ST_MakePoint(79.6300, 30.4950), 4326)),
('hab-helang', 'VIL-CHM-004', 'Helang (Alaknanda Gorge)', 'Chamoli', 'Uttarakhand', 1800, 360, 280, 220, 14.0, 50.0, 68.0, 82.5, 76.1, 'Immediate Relocation', 30.5280, 79.5100, 90.0, 75.0, 80.0, 80.0, 4, 'Active rockfall barrier impact on highway corridor', ST_SetSRID(ST_MakePoint(79.5100, 30.5280), 4326)),
('hab-ghat', 'VIL-CHM-008', 'Ghat (Nandakini Valley)', 'Chamoli', 'Uttarakhand', 2800, 560, 420, 380, 24.0, 45.0, 71.0, 86.8, 77.2, 'Immediate Relocation', 30.2600, 79.4800, 85.0, 88.0, 92.0, 80.0, 4, 'Cloudburst and flash-flood sediment inundation area', ST_SetSRID(ST_MakePoint(79.4800, 30.2600), 4326)),
('hab-pandukeshwar', 'VIL-CHM-005', 'Pandukeshwar (Badrinath Route)', 'Chamoli', 'Uttarakhand', 3100, 620, 450, 410, 19.0, 40.0, 69.5, 81.3, 73.8, 'Short-Term Relocation', 30.6350, 79.5550, 82.0, 86.0, 85.0, 75.0, 3, 'Valley funnel prone to river swelling and winter avalanche release', ST_SetSRID(ST_MakePoint(79.5550, 30.6350), 4326)),
('hab-tharali', 'VIL-CHM-010', 'Tharali (Pindar Valley)', 'Chamoli', 'Uttarakhand', 3600, 720, 520, 460, 26.0, 55.0, 65.0, 75.4, 69.8, 'Short-Term Relocation', 30.0750, 79.5050, 70.0, 85.0, 82.0, 75.0, 3, 'Pindar seasonal flash surges inundating lower commercial market', ST_SetSRID(ST_MakePoint(79.5050, 30.0750), 4326)),
('hab-urgam', 'VIL-CHM-009', 'Urgam (Kalpeshwar Valley)', 'Chamoli', 'Uttarakhand', 1950, 390, 300, 260, 32.0, 28.0, 72.0, 70.1, 63.1, 'Short-Term Relocation', 30.5600, 79.4400, 74.0, 60.0, 75.0, 55.0, 2, 'Single-lane road isolation and hillside debris slips', ST_SetSRID(ST_MakePoint(79.4400, 30.5600), 4326)),
('hab-pipalkoti', 'VIL-CHM-007', 'Pipalkoti (Middle Valley)', 'Chamoli', 'Uttarakhand', 4500, 900, 650, 550, 16.0, 75.0, 58.0, 64.7, 59.4, 'Short-Term Relocation', 30.4300, 79.4300, 68.0, 65.0, 60.0, 60.0, 3, 'Alaknanda riverbank erosion and retaining wall distress', ST_SetSRID(ST_MakePoint(79.4300, 30.4300), 4326)),
('hab-mana', 'VIL-CHM-006', 'Mana (Frontier High Altitude)', 'Chamoli', 'Uttarakhand', 1200, 240, 180, 160, 36.0, 30.0, 62.0, 77.2, 58.6, 'Short-Term Relocation', 30.7680, 79.4950, 78.0, 70.0, 90.0, 70.0, 2, 'High altitude moraine rockfall and seasonal snow isolation', ST_SetSRID(ST_MakePoint(79.4950, 30.7680), 4326))
ON CONFLICT (id) DO NOTHING;

-- SEED RELOCATION SITES
INSERT INTO relocation_sites (id, site_name, district, land_area_acres, estimated_capacity, current_occupancy_families, water_score, road_score, school_score, hospital_score, low_hazard_score, flat_land_score, suitability_score, latitude, longitude, land_capacity_families, water_capacity_families, school_capacity_families, health_capacity_families, road_capacity_families, final_capacity_families, available_capacity_families, location)
VALUES
('site-gauchar-01', 'Gauchar Plateau Safe Enclave', 'Chamoli', 48.0, 650, 45, 92.0, 95.0, 90.0, 88.0, 94.0, 92.0, 92.2, 30.2900, 79.1550, 700, 650, 600, 620, 750, 600, 555, ST_SetSRID(ST_MakePoint(79.1550, 30.2900), 4326)),
('site-gwaldam-02', 'Gwaldam Hill Terrace Reserve', 'Chamoli', 34.0, 420, 30, 84.0, 82.0, 80.0, 75.0, 88.0, 80.0, 82.3, 30.0150, 79.5600, 500, 420, 450, 430, 480, 420, 390, ST_SetSRID(ST_MakePoint(79.5600, 30.0150), 4326)),
('site-karanprayag-03', 'Karnaprayag Upper Ridge Township', 'Chamoli', 28.5, 380, 20, 88.0, 90.0, 85.0, 92.0, 85.0, 78.0, 85.6, 30.2650, 79.2250, 420, 400, 380, 450, 500, 380, 360, ST_SetSRID(ST_MakePoint(79.2250, 30.2650), 4326)),
('site-nandprayag-04', 'Nandprayag Plateau Buffer', 'Chamoli', 22.0, 290, 15, 86.0, 84.0, 78.0, 80.0, 89.0, 82.0, 84.5, 30.3350, 79.3150, 330, 310, 290, 320, 350, 290, 275, ST_SetSRID(ST_MakePoint(79.3150, 30.3350), 4326))
ON CONFLICT (id) DO NOTHING;
