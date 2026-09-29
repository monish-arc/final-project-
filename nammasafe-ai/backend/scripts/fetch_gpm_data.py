"""GES DISC helper: ingest a NASA GPM IMERG precipitation tile.

IMERG is distributed as bulk HDF5 half-hour tiles, not a point API. This script
downloads an IMERG half-hour file into GPM_DATA_DIR, from which
RainfallDataService extracts point precipitation.

IMERG versioning moved on: V06 is retired. The current Early half-hour product
on the GES DISC archive is GPM_3IMERGHHE.07 (files "3B-HHR-E.MS...V07*"), served
from the classic gpm1 host at /data/s4pa/GPM_L3/<product>/<YYYY>/<DDD>/ where
DDD is the zero-padded day-of-year. Filenames carry a per-day version suffix
(V07B/V07C/...), so this script resolves files by *listing the day directory*
instead of guessing the URL — robust to version drift.

Usage (from backend/):
  # Latest available half-hour slot (IMERG Early latency is ~4 hours):
  python scripts/fetch_gpm_data.py --recent
  python scripts/fetch_gpm_data.py --recent --dry-run

  # Or pin a specific slot:
  python scripts/fetch_gpm_data.py --date 2026-09-17 --time 05:30
  python scripts/fetch_gpm_data.py --date 2026-09-17 --time 05:30 --dry-run

Environment (loaded from backend/.env, gitignored):
  EARTHDATA_TOKEN    NASA Earthdata Login token (JWT). Sent as
                     "Authorization: Bearer <token>" when it starts with "eyJ",
                     otherwise used as the basic-auth password with
                     EARTHDATA_USERNAME (legacy path).
  GPM_DATA_DIR       Directory to store the downloaded HDF5 tile.
  IMERG_PRODUCT      Optional archive collection name (default GPM_3IMERGHHE.07).
                     Set GPM_3IMERGHH.07 for the FINAL product (older latency).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make the backend package importable when run as scripts/fetch_gpm_data.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import EARTHDATA_TOKEN, EARTHDATA_USERNAME, GPM_DATA_DIR

IMERG_PRODUCT = os.getenv("IMERG_PRODUCT", "GPM_3IMERGHHE.07")
PRODUCT_BASE_URL = f"https://gpm1.gesdisc.eosdis.nasa.gov/data/s4pa/GPM_L3/{IMERG_PRODUCT}"
# IMERG Early latency: files are ~4 hours behind real time.
IMERG_LATENCY_HOURS = float(os.getenv("IMERG_LATENCY_HOURS", "4"))
DOWNLOAD_TIMEOUT_SEC = 180

_HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"


def _auth_headers() -> dict:
    """Build the GES DISC Authorization header for the configured credentials.

    Modern EDL user tokens are JWTs ("eyJ...") and GES DISC accepts them as
    bearer tokens. The legacy path (username + token-as-password via basic
    auth) is preserved for accounts configured that way.
    """
    if EARTHDATA_TOKEN.startswith("eyJ"):
        return {"Authorization": f"Bearer {EARTHDATA_TOKEN}"}
    if EARTHDATA_USERNAME and EARTHDATA_TOKEN:
        import base64

        credentials = base64.b64encode(
            f"{EARTHDATA_USERNAME}:{EARTHDATA_TOKEN}".encode("utf-8")
        ).decode("ascii")
        return {"Authorization": f"Basic {credentials}"}
    return {}


def _credentials_available() -> bool:
    return bool(EARTHDATA_TOKEN)


def _slot_stamp(date: str, time_slot: str) -> str:
    """Return the S-prefixed start marker used in IMERG filenames."""
    hour, minute = time_slot.split(":")
    return f"-S{hour}{minute}00"


def _day_listing_url(date: str) -> str:
    year, month, day = (int(part) for part in date.split("-"))
    day_of_year = datetime(year, month, day).timetuple().tm_yday
    return f"{PRODUCT_BASE_URL}/{year:04d}/{day_of_year:03d}/"


def _fail_hint(status: int, body: str | None) -> str:
    """Turn a 401/403 listing/download response into an actionable message."""
    if status not in (401, 403):
        return ""
    try:
        import json as _json

        payload = _json.loads(body or "")
        if str(payload.get("error_description", "")).lower().startswith("eula"):
            return (
                " the Earthdata account has not accepted the GES DISC EULA/application. "
                "Open this URL in a browser while logged in as your Earthdata user, "
                f"then re-run: {payload.get('resolution_url', '')}"
            )
    except Exception:
        pass
    return " authentication rejected; the EARTHDATA token may be expired (renew at urs.earthdata.nasa.gov)"


def _day_files(date: str, headers: dict) -> tuple[str, list[str], int | None, str | None]:
    """GET the day directory and return (listing_url, filenames, status, body).

    Resolves the real archive layout on the fly: the day-of-year directory holds
    one HDF5 per half-hour slot with a dynamic per-day version suffix, so the
    filename is matched from the directory index rather than fabricated.
    """
    import httpx

    listing_url = _day_listing_url(date)
    response = httpx.get(listing_url, headers=headers, timeout=60, follow_redirects=True)
    if response.status_code >= 400:
        return listing_url, [], response.status_code, response.text[:600]
    files = re.findall(r'href="([^"?#]+\.HDF5)"', response.text)
    return listing_url, files, response.status_code, None


def _tile_url(date: str, time_slot: str, headers: dict) -> str | None:
    """Return the full URL of the slot's IMERG tile, or None if not published."""
    listing_url, files, status, body = _day_files(date, headers)
    if status is not None and status >= 400:
        hint = _fail_hint(status, body)
        raise RuntimeError(f"GES DISC directory listing failed (HTTP {status}){hint}")
    stamp = _slot_stamp(date, time_slot)
    for name in files:
        if stamp in name:
            return listing_url + name
    return None


def _recent_url(headers: dict) -> str | None:
    """Return the newest IMERG Early tile URL that actually exists.

    IMERG Early latency is nominal (~4h) but varies; scan back in half-hour
    steps from now-latency until the slot file appears in the day listing.
    """
    now = datetime.now(timezone.utc) - timedelta(hours=IMERG_LATENCY_HOURS)
    now = now.replace(minute=30 if now.minute >= 30 else 0, second=0, microsecond=0)

    for back in range(0, 96):  # up to 48 hours back
        slot = now - timedelta(hours=back * 0.5)
        date, time_slot = slot.strftime("%Y-%m-%d"), slot.strftime("%H:%M")
        try:
            url = _tile_url(date, time_slot, headers)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return None
        if url:
            print(f"Resolved latest available slot: {date} {time_slot} UTC")
            return url
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--time", default=None, help="HH:MM (UTC, 30-min slot)")
    parser.add_argument("--recent", action="store_true", help="Pick the latest available half-hour slot")
    parser.add_argument("--output", default=None, help="Output HDF5 path")
    parser.add_argument("--dry-run", action="store_true", help="Print the download URL only")
    args = parser.parse_args(argv)

    if args.recent:
        recent_mode = True
    elif args.date:
        recent_mode = False
        date = args.date
        time_slot = args.time or "05:30"
    else:
        parser.error("Provide --recent or --date (with optional --time).")

    if not _credentials_available():
        print("EARTHDATA_TOKEN is not configured (see backend/.env).", file=sys.stderr)
        return 1

    data_dir = GPM_DATA_DIR or str(Path(__file__).resolve().parent.parent / "data" / "gpm")
    if not GPM_DATA_DIR:
        print(f"No GPM_DATA_DIR set; defaulting to {data_dir}")
    Path(data_dir).mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": "NammaSafeAI-DisasterDecisionSupport/1.0 (govt pilot)"}
    headers.update(_auth_headers())

    try:
        if recent_mode:
            url = _recent_url(headers)
            if not url:
                print("No IMERG Early tile found in the recent window on GES DISC.", file=sys.stderr)
                return 1
        else:
            url = _tile_url(date, time_slot, headers)
            if not url:
                print(
                    f"No IMERG tile for {date} {time_slot} UTC in {IMERG_PRODUCT} "
                    "(slot not published yet? use --recent).",
                    file=sys.stderr,
                )
                return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"IMERG tile URL (dry-run, not downloaded):\n{url}")
        return 0

    output = args.output or os.path.join(data_dir, url.rsplit("/", 1)[-1])

    import httpx

    print(f"Downloading {url} -> {output}")
    try:
        with httpx.stream(
            "GET", url, headers=headers, timeout=DOWNLOAD_TIMEOUT_SEC, follow_redirects=True
        ) as response:
            if response.status_code >= 400:
                body = ""
                try:
                    body = response.read().decode("utf-8", "replace")[:600]
                except Exception:
                    body = ""
                hint = _fail_hint(response.status_code, body)
                print(f"Download failed: HTTP {response.status_code}{hint}", file=sys.stderr)
                return 1
            with open(output, "wb") as handle:
                for chunk in response.iter_bytes(chunk_size=8192):
                    handle.write(chunk)
            first = open(output, "rb").read(len(_HDF5_MAGIC))
    except httpx.HTTPError as exc:  # pragma: no cover - network specific
        print(f"Download failed: {exc}", file=sys.stderr)
        return 1

    if first != _HDF5_MAGIC:
        os.remove(output)
        print(
            f"Downloaded payload is not an HDF5 file (got {first!r}); removed {output}.",
            file=sys.stderr,
        )
        return 1

    print(f"Downloaded IMERG tile to {output}")
    print("Restart the backend so RainfallDataService picks up the tile (GPM_MODE=on).")
    return 0


if __name__ == "__main__":
    sys.exit(main())