"""
Jobcenter (KdU) + Wohngeld filter for Berlin.

Jobcenter pays rent (Kosten der Unterkunft = KdU) up to official limits.
Wohngeld (housing benefit) has its own rent caps.

Both filters depend on household size (Haushaltsgröße).

Sources:
- KdU Berlin 2024/2025: SenSoIaS Berlin AV Wohnen
- Wohngeld 2023+: Wohngeldgesetz §12, Berlin = Mietenstufe VI
"""
import logging

logger = logging.getLogger(__name__)

# ── Jobcenter KdU Warmmiete limits Berlin (€/month) ──────────────────────────
# Source: Senatsverwaltung für Integration, Arbeit und Soziales
# AV Wohnen Berlin 2024 — Warmmiete includes cold rent + all utilities
JOBCENTER_KDU_WARMMIETE: dict[int, float] = {
    1: 549,
    2: 671,
    3: 789,
    4: 911,
    5: 1021,
    6: 1131,   # +110 per additional person
}

# Max apartment size per household (m²)
JOBCENTER_SIZE_LIMITS: dict[int, int] = {
    1: 50,
    2: 60,
    3: 75,
    4: 85,
    5: 95,
    6: 105,
}

# ── Wohngeld Berlin limits (Mietenstufe VI = highest) 2025 ──────────────────
# Source: §12 WoGG, Berlin qualifies as Mietenstufe VI
WOHNGELD_RENT_LIMITS: dict[int, float] = {
    1: 580,
    2: 680,
    3: 800,
    4: 910,
    5: 1030,
    6: 1150,
    7: 1270,   # +120 per additional person
}


def _clamp_size(n: int, table: dict) -> int:
    """Clamp household size to table range."""
    n = max(1, int(n))
    return min(n, max(table.keys()))


def get_jobcenter_limit(household_size: int) -> float:
    """Return max Warmmiete for Jobcenter approval."""
    n = _clamp_size(household_size, JOBCENTER_KDU_WARMMIETE)
    if n in JOBCENTER_KDU_WARMMIETE:
        return JOBCENTER_KDU_WARMMIETE[n]
    # Extrapolate beyond table
    base  = JOBCENTER_KDU_WARMMIETE[max(JOBCENTER_KDU_WARMMIETE.keys())]
    extra = n - max(JOBCENTER_KDU_WARMMIETE.keys())
    return base + extra * 110


def get_wohngeld_limit(household_size: int) -> float:
    """Return max rent for Wohngeld eligibility."""
    n = _clamp_size(household_size, WOHNGELD_RENT_LIMITS)
    if n in WOHNGELD_RENT_LIMITS:
        return WOHNGELD_RENT_LIMITS[n]
    base  = WOHNGELD_RENT_LIMITS[max(WOHNGELD_RENT_LIMITS.keys())]
    extra = n - max(WOHNGELD_RENT_LIMITS.keys())
    return base + extra * 120


def get_size_limit(household_size: int) -> int:
    """Return max apartment size (m²) for Jobcenter approval."""
    n = _clamp_size(household_size, JOBCENTER_SIZE_LIMITS)
    if n in JOBCENTER_SIZE_LIMITS:
        return JOBCENTER_SIZE_LIMITS[n]
    base  = JOBCENTER_SIZE_LIMITS[max(JOBCENTER_SIZE_LIMITS.keys())]
    extra = n - max(JOBCENTER_SIZE_LIMITS.keys())
    return base + extra * 10


def passes_jobcenter(listing: dict, household_size: int) -> bool:
    """
    Returns True if listing qualifies for Jobcenter KdU approval.
    Checks: Warmmiete ≤ limit AND size ≤ limit (if size known).
    Unknown price → passes (benefit of the doubt).
    """
    price     = listing.get("price")
    size      = listing.get("size_m2")
    price_lim = get_jobcenter_limit(household_size)
    size_lim  = get_size_limit(household_size)

    if price is not None and price > price_lim:
        return False
    if size is not None and size > size_lim:
        return False
    return True


def passes_wohngeld(listing: dict, household_size: int) -> bool:
    """
    Returns True if listing is within Wohngeld rent subsidy limits.
    Unknown price → passes.
    """
    price = listing.get("price")
    if price is None:
        return True
    return price <= get_wohngeld_limit(household_size)


def get_social_badge(listing: dict, household_size: int) -> tuple[bool, bool, str]:
    """
    Returns (jobcenter_ok, wohngeld_ok, badge_text).
    OR logic: listing qualifies if EITHER condition is met.
    """
    jc  = passes_jobcenter(listing, household_size)
    wg  = passes_wohngeld(listing, household_size)
    jc_limit = get_jobcenter_limit(household_size)
    wg_limit = get_wohngeld_limit(household_size)

    if jc and wg:
        badge = f"🏛 Jobcenter ✅ · Wohngeld ✅"
    elif jc and not wg:
        badge = f"🏛 Jobcenter ✅ ({jc_limit:.0f}€) · Wohngeld ❌"
    elif not jc and wg:
        badge = f"🏛 Jobcenter ❌ · Wohngeld ✅ ({wg_limit:.0f}€)"
    else:
        badge = f"🏛 Jobcenter ❌ ({jc_limit:.0f}€ max) · Wohngeld ❌"

    return jc, wg, badge
