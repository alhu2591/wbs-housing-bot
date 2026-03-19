"""
Jobcenter (KdU) + Wohngeld filter — Berlin 2024/2025.
Each filter checks ALL conditions: price, size, AND rooms.

Sources:
- KdU: SenSoIaS Berlin AV Wohnen 2024
- Wohngeld: §12 WoGG, Berlin = Mietenstufe VI (2023+)
"""
import logging

logger = logging.getLogger(__name__)

# ── Jobcenter KdU Warmmiete limits (€) ───────────────────────────────────────
JOBCENTER_KDU_WARMMIETE: dict[int, float] = {
    1: 549.0,
    2: 671.0,
    3: 789.0,
    4: 911.0,
    5: 1021.0,
    6: 1131.0,
}
_JC_PRICE_STEP = 110.0

# ── Jobcenter max apartment size (m²) ────────────────────────────────────────
JOBCENTER_SIZE_LIMITS: dict[int, int] = {
    1: 50,
    2: 60,
    3: 75,
    4: 85,
    5: 95,
    6: 105,
}
_JC_SIZE_STEP = 10

# ── Jobcenter minimum rooms per household ────────────────────────────────────
# Based on AV Wohnen Berlin practical requirements
JOBCENTER_MIN_ROOMS: dict[int, float] = {
    1: 1.0,
    2: 1.0,   # 1 or 2 rooms acceptable
    3: 2.0,
    4: 3.0,
    5: 3.0,
    6: 4.0,
}
_JC_ROOMS_STEP = 1.0

# ── Wohngeld Berlin rent limits (Mietenstufe VI, 2025) ───────────────────────
WOHNGELD_RENT_LIMITS: dict[int, float] = {
    1: 580.0,
    2: 680.0,
    3: 800.0,
    4: 910.0,
    5: 1030.0,
    6: 1150.0,
    7: 1270.0,
}
_WG_PRICE_STEP = 120.0

# ── Wohngeld minimum apartment size (m²) — adequate housing ──────────────────
WOHNGELD_SIZE_LIMITS: dict[int, int] = {
    1: 0,    # no minimum for 1 person
    2: 40,
    3: 55,
    4: 65,
    5: 75,
    6: 85,
    7: 95,
}
_WG_SIZE_STEP = 10

# ── Wohngeld minimum rooms per household ─────────────────────────────────────
WOHNGELD_MIN_ROOMS: dict[int, float] = {
    1: 1.0,
    2: 1.0,
    3: 2.0,
    4: 2.0,
    5: 3.0,
    6: 3.0,
    7: 4.0,
}
_WG_ROOMS_STEP = 1.0


def _clamp(n: int) -> int:
    try:
        return max(1, int(n))
    except (TypeError, ValueError):
        return 1


# ── Limit getters ─────────────────────────────────────────────────────────────

def get_jobcenter_limit(n: int) -> float:
    n = _clamp(n)
    if n in JOBCENTER_KDU_WARMMIETE:
        return JOBCENTER_KDU_WARMMIETE[n]
    return JOBCENTER_KDU_WARMMIETE[6] + (n - 6) * _JC_PRICE_STEP

def get_jobcenter_min_rooms(n: int) -> float:
    n = _clamp(n)
    if n in JOBCENTER_MIN_ROOMS:
        return JOBCENTER_MIN_ROOMS[n]
    return JOBCENTER_MIN_ROOMS[6] + (n - 6) * _JC_ROOMS_STEP

def get_size_limit(n: int) -> int:
    n = _clamp(n)
    if n in JOBCENTER_SIZE_LIMITS:
        return JOBCENTER_SIZE_LIMITS[n]
    return JOBCENTER_SIZE_LIMITS[6] + (n - 6) * _JC_SIZE_STEP

def get_wohngeld_limit(n: int) -> float:
    n = _clamp(n)
    if n in WOHNGELD_RENT_LIMITS:
        return WOHNGELD_RENT_LIMITS[n]
    return WOHNGELD_RENT_LIMITS[7] + (n - 7) * _WG_PRICE_STEP

def get_wohngeld_min_rooms(n: int) -> float:
    n = _clamp(n)
    if n in WOHNGELD_MIN_ROOMS:
        return WOHNGELD_MIN_ROOMS[n]
    return WOHNGELD_MIN_ROOMS[7] + (n - 7) * _WG_ROOMS_STEP


# ── Core filter functions ─────────────────────────────────────────────────────

def _check_price(listing: dict, limit: float) -> bool | None:
    """True=ok, False=fail, None=unknown"""
    price = listing.get("price")
    if price is None:  return None
    if price <= 0:     return False
    return price <= limit

def _check_size_max(listing: dict, limit: int) -> bool | None:
    size = listing.get("size_m2")
    if size is None or size <= 0: return None
    return size <= limit

def _check_size_min(listing: dict, minimum: int) -> bool | None:
    if minimum <= 0: return None
    size = listing.get("size_m2")
    if size is None or size <= 0: return None
    return size >= minimum

def _check_rooms_min(listing: dict, min_rooms: float) -> bool | None:
    rooms = listing.get("rooms")
    if rooms is None or rooms <= 0: return None
    return rooms >= min_rooms


def passes_jobcenter(listing: dict, household_size: int) -> bool:
    """
    Returns True ONLY if ALL known conditions pass for Jobcenter KdU.
    Unknown values (None) are treated as benefit-of-the-doubt (pass).

    Conditions:
      1. Warmmiete ≤ KdU price limit
      2. Size ≤ max m² limit
      3. Rooms ≥ min rooms for household size
    """
    n           = _clamp(household_size)
    price_lim   = get_jobcenter_limit(n)
    size_lim    = get_size_limit(n)
    min_rooms   = get_jobcenter_min_rooms(n)

    price_ok = _check_price(listing, price_lim)
    size_ok  = _check_size_max(listing, size_lim)
    rooms_ok = _check_rooms_min(listing, min_rooms)

    # Fail if any known condition fails
    if price_ok is False:  return False
    if size_ok  is False:  return False
    if rooms_ok is False:  return False
    return True


def passes_wohngeld(listing: dict, household_size: int) -> bool:
    """
    Returns True ONLY if ALL known conditions pass for Wohngeld.

    Conditions:
      1. Rent ≤ Wohngeld limit
      2. Size ≥ minimum adequate size (if known)
      3. Rooms ≥ minimum adequate rooms for household
    """
    n           = _clamp(household_size)
    price_lim   = get_wohngeld_limit(n)
    min_size    = WOHNGELD_SIZE_LIMITS.get(min(n, max(WOHNGELD_SIZE_LIMITS)), 0)
    min_rooms   = get_wohngeld_min_rooms(n)

    price_ok    = _check_price(listing, price_lim)
    size_ok     = _check_size_min(listing, min_size)
    rooms_ok    = _check_rooms_min(listing, min_rooms)

    if price_ok is False:  return False
    if size_ok  is False:  return False
    if rooms_ok is False:  return False
    return True


def get_social_badge(listing: dict, household_size: int) -> tuple[bool, bool, str]:
    """
    Returns (jobcenter_ok, wohngeld_ok, badge_text).
    OR logic: passes if EITHER condition is satisfied.
    Badge shows all condition details.
    """
    n  = _clamp(household_size)
    jc = passes_jobcenter(listing, n)
    wg = passes_wohngeld(listing, n)

    jc_lim = get_jobcenter_limit(n)
    wg_lim = get_wohngeld_limit(n)
    sz_lim = get_size_limit(n)
    jc_rooms = get_jobcenter_min_rooms(n)

    if jc and wg:
        badge = f"🏛 Jobcenter ✅ · Wohngeld ✅"
    elif jc:
        badge = f"🏛 Jobcenter ✅ ({jc_lim:.0f}€/{sz_lim}m²) · Wohngeld ❌"
    elif wg:
        badge = f"🏛 Jobcenter ❌ · Wohngeld ✅ ({wg_lim:.0f}€)"
    else:
        badge = f"🏛 Jobcenter ❌ ({jc_lim:.0f}€/{sz_lim}m²) · Wohngeld ❌"

    return jc, wg, badge


def get_full_requirements(household_size: int) -> dict:
    """Return all limits for a given household size — used in /status display."""
    n = _clamp(household_size)
    return {
        "jc_price":     get_jobcenter_limit(n),
        "jc_size_max":  get_size_limit(n),
        "jc_rooms_min": get_jobcenter_min_rooms(n),
        "wg_price":     get_wohngeld_limit(n),
        "wg_rooms_min": get_wohngeld_min_rooms(n),
    }
