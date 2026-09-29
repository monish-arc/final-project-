"""
Historical (previous-year) data import CLI.

Imports a verified Kerala rainfall CSV into the historical_hazard_observations
table.  See backend/app/data/historical/README.md for the exact column format
and the official source URLs (India-WRIS, IMD, KSDMA).  The importer never
fabricates data — unverified / undocumented sources must not be imported.

Usage (from backend/):
  python scripts/import_historical_data.py --dataset data/historical/kerala_2025.csv
  python scripts/import_historical_data.py --dataset data/historical/kerala_2025.csv --dry-run
  python scripts/import_historical_data.py --dataset data/historical/kerala_2025.csv --year 2025

Exit codes:
  0  imported (or dry-run clean) with zero rejections
  1  some rows rejected (reported, nothing of them committed)
"""

import argparse
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import DATABASE_URL
from app.historical_importer import import_csv_file
from app.models import Base


def _connect():
    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help="Path to the historical CSV dataset")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report only; do not write anything")
    parser.add_argument("--year", type=int, default=None, help="Expected dataset year (validated against each row)")
    args = parser.parse_args(argv)

    db = _connect()
    try:
        with open(args.dataset, "r", encoding="utf-8-sig") as handle:
            result = import_csv_file(db, handle, expected_year=args.year, dry_run=args.dry_run)
    finally:
        db.close()

    print(f"Rows read           : {result.raw}")
    print(f"Inserted           : {result.inserted}")
    print(f"Skipped duplicates : {result.skipped_duplicate}")
    print(f"Rejected           : {result.rejected}")
    if result.issues:
        print("\nRejections:")
        for issue in result.issues:
            print(f"  row {issue.row_number}: {issue.reason}")
    print(f"\nDistrict summary ({'dry-run' if args.dry_run else 'committed'}):")
    for report in result.district_reports:
        print(f"  {report.district:20s} inserted={report.inserted}")

    if args.dry_run:
        print("\nDry-run complete — nothing was written to the database.")
    else:
        print("\nImport complete.")

    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())