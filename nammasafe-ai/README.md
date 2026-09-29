# NammaSafe AI 🏔️
### Proactive Red-Zone and Relocation Planning Platform
**Pilot Location: Chamoli District, Uttarakhand, India**

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python: 3.11](https://img.shields.io/badge/Python-3.11-3776AB.svg?logo=python&logoColor=white)](https://python.org)
[![FastAPI: 0.115](https://img.shields.io/badge/FastAPI-0.115-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React: 19](https://img.shields.io/badge/React-19-61DAFB.svg?logo=react&logoColor=white)](https://react.dev)
[![PostgreSQL: 15 / PostGIS](https://img.shields.io/badge/PostgreSQL-PostGIS-336791.svg?logo=postgresql&logoColor=white)](https://postgis.net)

---

## 📌 Problem Statement & Overview

In high-altitude Himalayan territories such as **Chamoli District, Uttarakhand** (encompassing Joshimath, Raini, and Tapovan), compound disasters—including land subsidence, glacial lake outbursts (GLOFs), cloudbursts, and flash floods—threaten habitations located on fragile moraines and steep river valleys.

**NammaSafe AI** is an AI-driven GIS decision-support platform designed for disaster management authorities to:
1. Identify multi-hazard **Red Zones** across terrain layers.
2. Formulate objective **Relocation Priority Indices** using strict mathematical models.
3. Assess the multi-resource **Carrying Capacity** and suitability of designated safe relocation sites.
4. Provide the **SafeShift Simulator** to validate resettlement allocations before ground displacement.

---

## 👥 Demo User Accounts & Roles

The platform enforces JWT role-based access control with 4 pre-configured demo personas:

| Role | Username | Password | Full Name | Primary Capabilities |
| :--- | :--- | :--- | :--- | :--- |
| **Admin** | `admin` | `admin123` | Dr. Rajeshwar Semwal | Ingest hazard GIS data, trigger batch calculations, manage sites & habitations |
| **Disaster Officer** | `officer` | `officer123` | Smt. Priyanka Bhandari | Full dashboard access, GIS layer controls, approve recommendations, run SafeShift simulator |
| **Field Officer** | `field` | `field123` | Kavita Negi | Submit geo-tagged ground reports (cracks, landslides, flood levels), upload observations |
| **Viewer** | `viewer` | `viewer123` | Arun Rawat | Public transparency view, browse risk summaries and safe zone buffers |

---

## 🏗️ Monorepo Structure

```
nammasafe-ai/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application entry point
│   │   ├── config.py            # Environment configurations
│   │   ├── database.py          # SQLAlchemy database engine & sessions
│   │   ├── models.py            # ORM models (Habitation, RedZone, Site, Report, etc.)
│   │   ├── schemas.py           # Pydantic validation schemas
│   │   ├── risk_engine.py       # Mathematical hazard, vulnerability & priority algorithms
│   │   ├── auth.py              # JWT tokens & role dependencies
│   │   └── seed_data.py         # Synthetic Chamoli pilot dataset
│   ├── tests/
│   │   ├── test_risk_engine.py  # Unit tests for calculation formulas
│   │   └── test_api.py          # Unit tests for FastAPI REST endpoints
│   ├── alembic/                 # Database migrations
│   ├── Dockerfile
│   └── requirements.txt
├── database/
│   └── init.sql                 # PostGIS spatial tables, GIST indexes & seed records
├── docs/
│   └── architecture.md          # Detailed architecture, mathematical formulas & schemas
├── docker-compose.yml           # Multi-container orchestration (PostGIS, Backend, Frontend)
└── README.md
```

---

## ⚡ Quickstart Guide

### Option 1: Run with Docker Compose (Full Stack)

Ensure Docker and Docker Compose are installed, then run:

```bash
# Navigate to the project root
cd nammasafe-ai

# Build and start all services (PostGIS, FastAPI, React Frontend)
docker-compose up --build -d

# Verify all containers are healthy
docker-compose ps
```

- **Frontend Application**: http://localhost:3000
- **FastAPI Interactive Swagger Docs**: http://localhost:8000/docs
- **PostgreSQL / PostGIS Database**: `localhost:5432` (`nammasafe_db`)

---

### Option 2: Run Locally (Without Docker)

#### 1. Backend Setup:
```bash
cd nammasafe-ai/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run pytest unit tests
PYTHONPATH=. pytest tests/ -v

# Start the FastAPI server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### 2. Frontend Setup:
```bash
# In the workspace root
npm install
npm run dev
```

---

## 🧪 Testing

### Backend Unit Tests (pytest)
```bash
PYTHONPATH=nammasafe-ai/backend pytest nammasafe-ai/backend/tests/ -v
```
All 12 tests covering hazard score formulas, relocation priority classification, site carrying capacity bottlenecks, and API endpoints run and pass in `< 1s`.

### Frontend Component Tests (vitest)
```bash
npm run test
```

---

## 📐 Decision Support Formulas

1. **Hazard Score**:  
   `40% Landslide Risk + 30% Flood Risk + 20% Extreme Rainfall + 10% Past Disaster Frequency`

2. **Vulnerability Score**:  
   `35% Population Density + 25% Dependents Ratio + 20% Poor Road Access + 20% Hospital Distance`

3. **Relocation Priority**:  
   `50% Hazard Score + 30% Vulnerability Score + 20% Disaster History Score`  
   - `75 - 100`: **Immediate Relocation**
   - `50 - 74`: **Short-Term Relocation**
   - `30 - 49`: **Medium-Term Relocation**
   - `< 30`: **Monitor Only**

4. **Site Suitability**:  
   `30% Low Hazard + 20% Low Slope + 15% Road Access + 15% Water Availability + 10% School Access + 10% Hospital Access`

5. **Carrying Capacity**:  
   `Final Capacity = Min(Land Housing, Water Network, School Enrolment, Health Service, Road Access)`
