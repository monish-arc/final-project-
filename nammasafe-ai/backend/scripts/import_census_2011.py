"""
Census of India 2011 village-level importer (REAL Census CSV data).

Reads official Census 2011 village CSVs dropped by an operator under
app/data/census_2011/ and stores them idempotently in `census_villages`.
Values are written exactly as published — the importer rejects (never infers)
any record that does not carry a village code.

Expected CSV columns (utf-8-sig, header row present):
  village_code, village_name, district, state,
  total_population, total_households, male_population, female_population,
  child_population, area_km2, latitude, longitude

Recommended official source: Census of India 2011 Primary Census Abstract
  -> https://censusindia.gov.in/ (PCA village tables, state-wise CSV/XLSX)
  Licence: Census of India, official statistics.

Usage (from backend/):
  python scripts/import_census_2011.py --year 2011
  python scripts/import_census_2011.py --year 2011 --data app/data/census_2011
  python scripts/import_census_2011.py --dry-run

Exit codes:
  0  imported (or dry-run clean)
  1  some rows rejected (nothing of the rejected set committed)
  2  no data directory / no valid .csv files found
"""

import argparse
import csv
import os
import sys

# Make `app` importable when run as `python scripts/import_census_2011.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import DATABASE_URL
from app.models import Base, CensusVillage

DEFAULT_DIR = os.path.join("app", "data", "census_2011")

REQUIRED = {"village_code", "village_name"}
OPTIONAL = {
    "district", "state",
    "total_population", "total_households", "male_population",
    "female_population", "child_population", "area_km2",
    "latitude", "longitude",
}


def _connect():
    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _int_opt(value):
    if value in (None, ""):
        return None
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _float_opt(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=DEFAULT_DIR, help="Directory with official Census 2011 CSV files")
    parser.add_argument("--year", type=int, default=2011, help="Census year in the files (default 2011)")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report only; do not write anything")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.data):
        print(
            f"No census data found at {args.data!r}. Drop official Census 2011 CSVs there "
            f"(see app/data/README.md for the source URL) and re-run.",
            file=sys.stderr,
        )
        return 2
    files = sorted(f for f in os.listdir(args.data) if f.lower().endswith(".csv"))
    if not files:
        print(f"No .csv census files under {args.data!r}.", file=sys.stderr)
        return 2

    db = _connect()
    inserted = 0
    skipped = 0
    rejected = 0
    issues = []
    try:
        for filename in files:
            path = os.path.join(args.data, filename)
            with open(path, "r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames:
                    issues.append((filename, 0, "no header row"))
                    rejected += 1
                    continue
                missing = REQUIRED - set(reader.fieldnames)
                if missing:
                    issues.append((filename, 0, f"missing required columns: {sorted(missing)}"))
                    rejected += 1
                    continue
                for row_number, row in enumerate(reader, start=2):
                    code = (row.get("village_code") or "").strip()
                    name = (row.get("village_name") or "").strip()
                    if not code or not name:
                        issues.append((filename, row_number, "missing village_code/village_name"))
                        rejected += 1
                        continue
                    existing = (
                        db.query(CensusVillage)
                        .filter_by(village_code=code, data_year=args.year)
                        .first()
                    )
                    if existing is not None:
                        skipped += 1
                        continue
                    if args.dry_run:
                        inserted += 1
                        continue
                    db.add(
                        CensusVillage(
                            village_code=code,
                            village_name=name,
                            district=(row.get("district") or "").strip() or None,
                            state=(row.get("state") or "").strip() or None,
                            total_population=_int_opt(row.get("total_population")),
                            total_households=_int_opt(row.get("total_households")),
                            male_population=_int_opt(row.get("male_population")),
                            female_population=_int_opt(row.get("female_population")),
                            child_population=_int_opt(row.get("child_population")),
                            area_km2=_float_opt(row.get("area_km2")),
                            latitude=_float_opt(row.get("latitude")),
                            longitude=_float_opt(row.get("longitude")),
                            data_year=args.year,
                            data_source="Census of India 2011 (Primary Census Abstract)",
                            source_reference=row.get("source_reference") or "",
                        )
                    )
                    inserted += 1
        if not args.dry_run:
            db.commit()
    finally:
        db.close()

    print(f"Census files       : {len(files)}")
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