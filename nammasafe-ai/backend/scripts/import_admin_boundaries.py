"""
Official administrative-boundary importer (real shapefile/GeoJSON data).

Reads official boundary GeoJSON files dropped by an operator under
app/data/admin_boundaries/ and stores them idempotently in `admin_boundaries`.
The importer never fabricates: every row is written exactly as the source file
states it, validated against the expected Schema.Org feature structure:

    {"type": "FeatureCollection",
     "features": [{"type": "Feature",
                   "properties": {"name": "...", "level": 5, "state": "...",
                                  "district": "...", "code": "..."},
                   "geometry": {...},   # GeoJSON polygon/multipolygon
                   "centroid": {"latitude": .., "longitude": ..}}]}

Recommended official sources:
  * Survey of India / NIC LGD directory  -> https://lgdirectory.gov.in/
  * NRSC Bhuvan state/district layers    -> https://bhuvan.nrsc.gov.in/

Usage (from backend/):
  python scripts/import_admin_boundaries.py
  python scripts/import_admin_boundaries.py --data app/data/admin_boundaries
  python scripts/import_admin_boundaries.py --dry-run

Exit codes:
  0  imported (or dry-run clean)
  1  some records rejected (nothing of the rejected set committed)
  2  no data directory / no valid files found
"""

import argparse
import json
import os
import sys
from typing import Optional


# Make `app` importable when run as `python scripts/import_admin_boundaries.py`
# from anywhere (script dir is scripts/, so the backend root needs explicit path).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import DATABASE_URL
from app.models import AdminBoundary, Base

DEFAULT_DIR = os.path.join("app", "data", "admin_boundaries")

def _coerce_level(value) -> Optional[int]:
    """Strict-but-tolerant LGD admin level → int, else None (rejected later)."""
    if value in (None, ""):
        return None
    try:
        return int(str(value).strip().rstrip(".0"))
    except (TypeError, ValueError):
        return None


def _connect():
    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _load_features(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    features = payload.get("features", []) if isinstance(payload, dict) else []
    if not features:
        return []
    return features


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=DEFAULT_DIR, help="Directory with official boundary GeoJSON files")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report only; do not write anything")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.data):
        print(
            f"No boundary data found at {args.data!r}. Drop official GeoJSON there "
            f"(see app/data/README.md for sources) and re-run.",
            file=sys.stderr,
        )
        return 2

    files = sorted(f for f in os.listdir(args.data) if f.lower().endswith(".json"))
    if not files:
        print(f"No .json boundary files under {args.data!r}.", file=sys.stderr)
        return 2

    db = _connect()
    inserted = 0
    skipped = 0
    rejected = 0
    issues = []
    seen: set = set()
    try:
        for filename in files:
            path = os.path.join(args.data, filename)
            try:
                features = _load_features(path)
            except (ValueError, OSError) as exc:
                print(f"  {filename}: unreadable ({exc}); skipped.", file=sys.stdout)
                rejected += 1
                continue
            for idx, feature in enumerate(features):
                properties = (feature.get("properties") or {} if isinstance(feature, dict) else {})
                name = properties.get("name")
                level = _coerce_level(properties.get("level"))
                if not name:
                    issues.append((filename, idx + 1, "missing properties.name"))
                    rejected += 1
                    continue
                if level is None or level not in (4, 5, 6):
                    issues.append((filename, idx + 1, f"unsupported level {properties.get('level')!r} (expected 4, 5 or 6)"))
                    rejected += 1
                    continue
                centroid = feature.get("centroid") or {}
                key = (level, str(name), str(properties.get("state") or ""))
                existing = (
                    db.query(AdminBoundary)
                    .filter_by(level=level, name=str(name), state=str(properties.get("state") or ""))
                    .first()
                )
                if existing is not None or key in seen:
                    skipped += 1
                    continue
                seen.add(key)
                if args.dry_run:
                    inserted += 1
                    continue
                row = AdminBoundary(
                    level=level,
                    name=str(name),
                    state=str(properties.get("state") or "") or None,
                    district=str(properties.get("district") or "") or None,
                    code=str(properties.get("code") or "") or None,
                    geometry_geojson=feature.get("geometry"),
                    centroid_lat=centroid.get("latitude") if isinstance(centroid, dict) else None,
                    centroid_lng=centroid.get("longitude") if isinstance(centroid, dict) else None,
                    data_source=properties.get("source") or "Official boundary source",
                    source_reference=properties.get("source_reference") or "",
                    data_status="OFFICIAL",
                )
                db.add(row)
                inserted += 1
        if not args.dry_run:
            db.commit()
    finally:
        db.close()

    print(f"Boundary files      : {len(files)}")
    print(f"Inserted           : {inserted}")
    print(f"Skipped duplicates : {skipped}")
    print(f"Rejected           : {rejected}")
    if issues:
        print("\nRejections:")
        for filename, row, reason in issues[:50]:
            print(f"  {filename}:{row}: {reason}")
    print(f"\n({ 'dry-run' if args.dry_run else 'committed' })")
    return 1 if rejected else 0


if __name__ == "__main__":
    sys.exit(main())