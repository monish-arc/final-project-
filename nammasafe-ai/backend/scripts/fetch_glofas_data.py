"""CDS helper: request + download a CEMS GloFAS forecast dataset.

GloFAS is a *job-based* API: request a region, poll for the job, download the
NetCDF into GLOFAS_DATA_DIR where the FloodDataService will extract point data.

Usage (from backend/, with CDS credentials configured):
  python scripts/fetch_glofas_data.py --lat0 8 --lat1 13 --lon0 74 --lon1 78
  python scripts/fetch_glofas_data.py --dry-run   # only prints the CDS request

Sets the following environment variables (or place them in .env):
  CDS_API_KEY, CDS_API_SECRET, GLOFAS_DATA_DIR
Optional:
  GLOFAS_DATASET_PATH — set to the downloaded NetCDF to bypass the directory scan.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from app.config import CDS_API_KEY, CDS_API_SECRET, CDS_API_URL, GLOPAS_DATA_DIR, GLOPAS_DATASET


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lat0", type=float, default=8.0, help="Southern latitude of the bbox")
    parser.add_argument("--lat1", type=float, default=13.0, help="Northern latitude of the bbox")
    parser.add_argument("--lon0", type=float, default=74.0, help="Western longitude of the bbox")
    parser.add_argument("--lon1", type=float, default=78.0, help="Eastern longitude of the bbox")
    parser.add_argument("--output", default=None, help="Output NetCDF path (default: <GLOFAS_DATA_DIR>/glofas_forecast.nc)")
    parser.add_argument("--dry-run", action="store_true", help="Print the CDS request only")
    args = parser.parse_args(argv)

    if not CDS_API_KEY or not CDS_API_SECRET:
        print("CDS credentials are missing (CDS_API_KEY / CDS_API_SECRET).", file=sys.stderr)
        return 1

    out_dir = GLOPAS_DATA_DIR
    if not out_dir:
        out_dir = str(Path(__file__).resolve().parent.parent / "data" / "glofas")
        print(f"No GLOFAS_DATA_DIR set; defaulting to {out_dir}")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    output = args.output or os.path.join(out_dir, "glofas_forecast.nc")

    import cdsapi  # type: ignore  # operator-only dependency

    request = {
        "system_version": ["operational"],
        "hydrological_model": ["lisflood"],
        "product_type": ["forecast"],
        "variable": ["river_discharge_in_the_last_24_hours"],
        "hyear": [str(time.gmtime().tm_year)],
        "hmonth": [f"{time.gmtime().tm_mon:02d}"],
        "hday": [f"{time.gmtime().tm_mday:02d}"],
        "area": [args.lat1, args.lon0, args.lat0, args.lon1],
        "format": ["netcdf"],
    }
    if args.dry_run:
        print("CDS request (dry-run, not submitted):")
        print(request)
        return 0

    client = cdsapi.Client(url=CDS_API_URL, key=f"{CDS_API_KEY}:{CDS_API_SECRET}")
    result = client.retrieve(GLOPAS_DATASET, request)
    result.download(output)
    print(f"Downloaded GloFAS forecast to {output}")
    print("Now set GLOFAS_DATA_DIR to the containing directory and restart the backend.")
    return 0


if __name__ == "__main__":
    sys.exit(main())