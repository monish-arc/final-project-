"""
Seed CLI for the curated historical disaster-events provenance table.

Populates disaster_events with real, well-documented disasters that affected
India, each carrying a public source reference. The seed is intentionally small
and auditable — it never invents events.

Usage (from backend/):
  python scripts/seed_disaster_events.py
  python scripts/seed_disaster_events.py --dry-run
  python scripts/seed_disaster_events.py --state Uttarakhand   # filter seed set

Exit codes:
  0  seeded (or dry-run clean)
  1  some rows rejected (reported, nothing of them committed)
"""

import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import DATABASE_URL
from app.models import Base, DisasterEvent

# (name, hazard_type, event_date, state, district, lat, lng, severity,
#  affected_population, fatalities, damage_inr_crore, description, source, url)
SEED_EVENTS = [
    (
        "2004 Indian Ocean tsunami (Nagapattinam)",
        "TSUNAMI", date(2004, 12, 26), "Tamil Nadu", "Nagapattinam",
        10.7672, 79.8440, "EXTREME",
        2_200_000, 12400, None,
        "Tsunami waves up to 5 m inundated low-lying coastal districts; Nagapattinam was the worst-hit Indian district.",
        "NDMA / Wikipedia (2004 Indian Ocean earthquake and tsunami in India)",
        "https://en.wikipedia.org/wiki/2004_Indian_Ocean_earthquake_and_tsunami_in_India",
    ),
    (
        "Kedarnath floods",
        "FLOOD", date(2013, 6, 16), "Uttarakhand", "Rudraprayag",
        30.7350, 79.0669, "EXTREME",
        110_000, 5700, 40_000,
        "Cloudburst-driven flash floods and a breach of the Chorabari glacial lake devastated Kedarnath and the Mandakini valley.",
        "NDMA-led Uttarakhand disaster reports / Wikipedia (2013 North India floods)",
        "https://en.wikipedia.org/wiki/2013_North_India_floods",
    ),
    (
        "Kerala floods",
        "FLOOD", date(2018, 8, 8), "Kerala", "Ernakulam",
        9.9816, 76.2999, "EXTREME",
        5_400_000, 483, 30_000,
        "Exceptional monsoon rainfall (record since 1924) triggered statewide floods and landslides across all 14 districts.",
        "Kerala State Disaster Management Authority (KSDMA) / Wikipedia (2018 Kerala floods)",
        "https://en.wikipedia.org/wiki/2018_Kerala_floods",
    ),
    (
        "Chamoli glacier burst",
        "LANDSLIDE", date(2021, 2, 7), "Uttarakhand", "Chamoli",
        30.4340, 79.7250, "EXTREME",
        10_000, 204, None,
        "A rock-ice avalanche in the Rishiganga valley caused a flash flood through Tapovan, destroying the Rishiganga and Dhauliganga hydel projects.",
        "WIHG / NDMA / Wikipedia (2021 Uttarakhand flood)",
        "https://en.wikipedia.org/wiki/2021_Uttarakhand_flood",
    ),
    (
        "Cyclone Tauktae",
        "CYCLONE", date(2021, 5, 17), "Gujarat", "Gir Somnath",
        20.9186, 70.8423, "SEVERE",
        2_100_000, 122, 10_000,
        "Very Severe Cyclonic Storm making landfall near Veraval; over 200,000 evacuated from Gujarat coastal districts.",
        "IMD cyclone reports / Wikipedia (Cyclone Tauktae)",
        "https://en.wikipedia.org/wiki/Cyclone_Tauktae",
    ),
    (
        "Mumbai great floods",
        "FLOOD", date(2005, 7, 26), "Maharashtra", "Mumbai",
        19.0760, 72.8777, "EXTREME",
        20_000_000, 1000, 6_000,
        "About 944 mm of rain fell in a single day (Vihar lake), paralyzing the city with subsurface flash flooding.",
        "IMD / BMC records / Wikipedia (2005 Maharashtra floods)",
        "https://en.wikipedia.org/wiki/2005_Maharashtra_floods",
    ),
    (
        "Cyclone Fani",
        "CYCLONE", date(2019, 5, 3), "Odisha", "Puri",
        19.8134, 85.8312, "SEVERE",
        28_000_000, 89, 12_000,
        "Extremely Severe Cyclonic Storm, the strongest to hit Odisha in 20 years; over 1.2 million evacuated pre-landfall.",
        "IMD / NDRF / Wikipedia (Cyclone Fani)",
        "https://en.wikipedia.org/wiki/Cyclone_Fani",
    ),
    (
        "Assam monsoon floods",
        "FLOOD", date(2020, 5, 15), "Assam", "Goalpara",
        26.1766, 90.6256, "SEVERE",
        5_400_000, 91, None,
        "Waves of Brahmaputra flooding through the monsoon; 34 of 33 districts affected at the peak (2020 season).",
        "ASDMA disaster reports / Wikipedia (2020 Assam floods)",
        "https://en.wikipedia.org/wiki/2020_Assam_floods",
    ),
    (
        "Cyclone Phailin",
        "CYCLONE", date(2013, 10, 12), "Odisha", "Ganjam",
        19.1370, 84.4960, "SEVERE",
        12_000_000, 45, 4_330,
        "Very Severe Cyclonic Storm; successful mass evacuation (over 1 million) limited fatalities to 45 in India.",
        "IMD / NDMA / Wikipedia (Cyclone Phailin)",
        "https://en.wikipedia.org/wiki/Cyclone_Phailin",
    ),
    (
        "Leh cloudburst",
        "FLASH_FLOOD", date(2010, 8, 5), "Ladakh", "Leh",
        34.1526, 77.5771, "SEVERE",
        1_000_000, 234, None,
        "A cloudburst unleashed destructive flash floods and mudslides across Leh town and its valley.",
        "NDMA report / Wikipedia (2010 Ladakh floods)",
        "https://en.wikipedia.org/wiki/2010_Ladakh_floods",
    ),
    (
        "Cyclone Amphan",
        "CYCLONE", date(2020, 5, 20), "West Bengal", "South 24 Parganas",
        21.7211, 88.8786, "SEVERE",
        30_000_000, 98, 13_000,
        "Super Cyclonic Storm making landfall near Sagar Island; extensive storm-surge flooding in the Sundarbans coastal belt.",
        "IMD / NDRF / Wikipedia (Cyclone Amphan)",
        "https://en.wikipedia.org/wiki/Cyclone_Amphan",
    ),
    (
        "Bihar kosi floods",
        "FLOOD", date(2019, 9, 20), "Bihar", "Sitamarhi",
        26.5950, 85.4940, "SEVERE",
        16_000_000, 120, None,
        "Kosi and Mahananda river floods drowned nearly 16 million people across Bihar in the 2019 monsoon season.",
        "Bihar Disaster Management Department / Wikipedia (2019 Bihar floods)",
        "https://en.wikipedia.org/wiki/2019_Bihar_floods",
    ),
]


def _connect():
    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Validate and report only; do not write anything")
    parser.add_argument("--state", default=None, help="Seed only events for this state (case-insensitive substring)")
    args = parser.parse_args(argv)

    events = SEED_EVENTS
    if args.state:
        needle = args.state.lower()
        events = [event for event in events if needle in event[3].lower()]
        print(f"Filtered to {len(events)} events matching state '{args.state}'.")

    rejected = []
    for index, event in enumerate(events, start=1):
        *_, source, reference = event
        if not source or not reference:
            rejected.append((index, "missing source or source_reference"))
    done = [event for event in events]
    for index, reason in rejected:
        print(f"  row {index}: rejected — {reason}")

    if rejected:
        if args.dry_run:
            print(f"\nDry-run rejected {len(rejected)} rows; nothing was written.")
        else:
            print("\nRefusing to write while {len(rejected)} row(s) are rejected.")
        return 1

    inserted = 0
    skipped = 0
    db = _connect()
    try:
        for event in done:
            name, hazard_type, event_date, state, district, lat, lng, severity, affected, fatalities, damage, description, source, reference = event
            exists = db.execute(
                select(DisasterEvent.id).where(
                    DisasterEvent.name == name,
                    DisasterEvent.event_date == event_date,
                    DisasterEvent.source_reference == reference,
                ).limit(1)
            ).scalars().first()
            if exists:
                skipped += 1
                continue
            if not args.dry_run:
                db.add(DisasterEvent(
                    name=name,
                    hazard_type=hazard_type,
                    event_date=event_date,
                    state=state,
                    district=district,
                    latitude=lat,
                    longitude=lng,
                    severity_level=severity,
                    affected_population=affected,
                    fatalities=fatalities,
                    damage_estimate_inr_crore=damage,
                    description=description,
                    source=source,
                    source_reference=reference,
                    data_status="HISTORICAL",
                ))
            inserted += 1
        if not args.dry_run:
            db.commit()
        else:
            db.rollback()
    finally:
        db.close()

    print(f"Valid events     : {len(done)}")
    print(f"Would/inserted   : {inserted}")
    print(f"Skipped existing : {skipped}")
    if args.dry_run:
        print("\nDry-run complete — nothing was written to the database.")
    else:
        print("\nSeed complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())