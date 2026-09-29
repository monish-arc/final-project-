"""
Single source of truth for Kerala administrative geography used by the
historical-data subsystem (importer, baseline, API endpoints).

The district codes are the official LGD numeric codes and match the generated
frontend hierarchy at src/data/regions/hierarchy.ts (state code 32).

Do NOT duplicate these names/codes elsewhere — import from here.
"""

from typing import Dict, Optional, Tuple

KERALA_STATE_CODE = 32
KERALA_STATE_NAME = "Kerala"

# Order matches the LGD listing: Alappuzha (554) .. Wayanad (567).
KERALA_DISTRICTS: Tuple[Tuple[int, str], ...] = (
    (554, "Alappuzha"),
    (555, "Ernakulam"),
    (556, "Idukki"),
    (557, "Kannur"),
    (558, "Kasaragod"),
    (559, "Kollam"),
    (560, "Kottayam"),
    (561, "Kozhikode"),
    (562, "Malappuram"),
    (563, "Palakkad"),
    (564, "Pathanamthitta"),
    (565, "Thiruvananthapuram"),
    (566, "Thrissur"),
    (567, "Wayanad"),
)

CODE_TO_NAME: Dict[int, str] = dict(KERALA_DISTRICTS)
NAME_TO_CODE: Dict[str, int] = {name.lower(): code for code, name in KERALA_DISTRICTS}


def district_code(value) -> Optional[int]:
    """Resolve a district name (case-insensitive) or LGD code integer."""
    if value is None:
        return None
    if isinstance(value, int):
        return value if value in CODE_TO_NAME else None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if text.isdigit():
        code = int(text)
        return code if code in CODE_TO_NAME else None
    return NAME_TO_CODE.get(text.lower())


def district_name(value) -> Optional[str]:
    code = district_code(value)
    if code is None:
        return None
    return CODE_TO_NAME[code]


def is_valid_district(value) -> bool:
    return district_code(value) is not None


def resolve_district(value) -> Tuple[Optional[int], Optional[str]]:
    """Return (code, name) for a district value, or (None, None) if unknown."""
    code = district_code(value)
    if code is None:
        return None, None
    return code, CODE_TO_NAME[code]