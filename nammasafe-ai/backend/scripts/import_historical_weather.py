"""
ERA5 historical-weather importer (REAL reanalysis samples).

Reads an operator-produced export CSV of completed-month ERA5 samples and
loads them into `historical_weather_samples` so the app can serve historical
weather without re-fetching the archive API. Values come verbatim from the
export, which must be produced from the ECMWF ERA5 reanalysis (e.g. via the
Open-Meteo Archive API or the C3S CDS) — the importer refuses to record any
value it cannot attribute.

Expected CSV columns (utf-8-sig, header row present):
  latitude, longitude, year, month, variable, aggregation, value,
  [data_source, dataset, provider]

`aggregation` labels the summarisation, matching the archive caller's table:
  monthly_total, monthly_mean, monthly_mean_of_daily_max, days, monthly_max, ...
`variable` uses the ERA5/C3S key, e.g. temperature_2m, precipitation,
thunderstorm_days.

Usage (from backend/):
  python scripts/import_historical_weather.py --dataset app/data/historical/era5_2025_07.csv
  python scripts/import_historical_weather.py --dataset ... --dry-run

Exit codes:
  0  imported (or dry-run clean)
  1  some rows rejected (nothing of the rejected set committed)
  2  no dataset / unreadable file
"""

import argparse
import csv
import os
import sys

# Make `app` importable when run as `python scripts/import_historical_weather.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import DATABASE_URL
from app.models import Base, HistoricalWeatherSample

REQUIRED = {"latitude", "longitude", "year", "month", "variable", "aggregation", "value"}


def _connect():
    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _float_opt(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _int_opt(value):
    if value in (None, ""):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help="Path to the ERA5 export CSV")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report only; do not write anything")
    args = parser.parse_args(argv)

    if not args.dataset or not os.path.exists(args.dataset):
        print(f"Dataset not found: {args.dataset!r}", file=sys.stderr)
        return 2

    db = _connect()
    inserted = 0
    skipped = 0
    rejected = 0
    issues = []
    try:
        with open(args.dataset, "r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                print("CSV has no header row.", file=sys.stderr)
                return 2
            missing = REQUIRED - set(reader.fieldnames)
            if missing:
                print(f"Missing required columns: {sorted(missing)}", file=sys.stderr)
                return 2
            for row_number, row in enumerate(reader, start=2):
                lat = _float_opt(row.get("latitude"))
                lng = _float_opt(row.get("longitude"))
                year = _int_opt(row.get("year"))
                month = _int_opt(row.get("month"))
                variable = (row.get("variable") or "").strip()
                aggregation = (row.get("aggregation") or "").strip()
                value = _float_opt(row.get("value"))
                source = (row.get("data_source") or "Open-Meteo ERA5 Archive").strip()
                if lat is None or lng is None or year is None or month is None:
                    issues.append((row_number, "missing required field(s) or non-numeric coordinate/period"))
                    rejected += 1
                    continue
                if not variable or not aggregation:
                    issues.append((row_number, "missing variable/aggregation"))
                    rejected += 1
                    continue
                existing = (
                    db.query(HistoricalWeatherSample)
                    .filter_by(
                        latitude=round(lat, 5),
                        longitude=round(lng, 5),
                        data_year=year,
                        data_month=month,
                        variable=variable,
                        aggregation=aggregation,
                        data_source=source,
                    )
                    .first()
                )
                if existing is not None:
                    skipped += 1
                    continue
                if args.dry_run:
                    inserted += 1
                    continue
                db.add(
                    HistoricalWeatherSample(
                        latitude=round(lat, 5),
                        longitude=round(lng, 5),
                        data_year=year,
                        data_month=month,
                        variable=variable,
                        aggregation=aggregation,
                        value=value,
                        data_source=source,
                        dataset=(row.get("dataset") or "").strip() or None,
                        provider=(row.get("provider") or "").strip() or None,
                        data_status="HISTORICAL",
                    )
                )
                inserted += 1
        if not args.dry_run:
            db.commit()
    finally:
        db.close()

    print(f"Dataset            : {args.dataset}")
    print(f"Inserted           : {inserted}")
    print(f"Skipped duplicates : {skipped}")
    print(f"Rejected           : {rejected}")
    if issues:
        print("\nRejections:")
        for row, reason in issues[:50]:
            print(f"  row {row}: {reason}")
    print(f"\n({ 'dry-run' if args.dry_run else 'committed' })")
    return 1 if rejected else 0


if __name__ == "__main__":
    sys.exit(main())