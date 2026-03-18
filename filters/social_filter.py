"""
Jobcenter (KdU) + Wohngeld filter for Berlin.

Sources:
- KdU: SenSoIaS Berlin AV Wohnen 2024
- Wohngeld: §12 WoGG, Berlin = Mietenstufe VI (2023+)
"""
import logging

logger = logging.getLogger(__name__)

# ── Official Berlin KdU limits (Warmmiete) ────────────────────────────────────
JOBCENTER_KDU_WARMMIETE: dict[int, float] = {
    1: 549.0,
    2: 671.0,
    3: 789.0,
    4: 911.0,
    5: 1021.0,
    6: 1131.0,
}
_JC_STEP = 110.0   # € per additional person beyond 6

# ── Max apartment size per household ─────────────────────────────────────────
JOBCENTER_SIZE_LIMITS: dict[int, int] = {
    1: 50,
    2: 60,
    3: 75,
    4: 85,
    5: 95,
    6: 105,
}
_SZ_STEP = 10   # m² per additional person beyond 6

# ── Wohngeld Berlin limits (Mietenstufe VI) ───────────────────────────────────
WOHNGELD_RENT_LIMITS: dict[int, float] = {
    1: 580.0,
    2: 680.0,
    3: 800.0,
    4: 910.0,
    5: 1030.0,
    6: 1150.0,
    7: 1270.0,
}
_WG_STEP = 120.0   # € per additional person beyond 7


def _clamp_positive(n: int) -> int:
    """Ensure household size is at least 1."""
    try:
        return max(1, int(n))
    except (TypeError, ValueError):
        return 1


def get_jobcenter_limit(household_size: int) -> float:
    """Return max Warmmiete (€) for Jobcenter KdU approval."""
    n = _clamp_positive(household_size)
    if n in JOBCENTER_KDU_WARMMIETE:
        return JOBCENTER_KDU_WARMMIETE[n]
    # Extrapolate: +110€ per person beyond 6
    base  = JOBCENTER_KDU_WARMMIETE[6]
    extra = n - 6
    return base + extra * _JC_STEP


def get_wohngeld_limit(household_size: int) -> float:
    """Return max rent (€) for Wohngeld eligibility."""
    n = _clamp_positive(household_size)
    if n in WOHNGELD_RENT_LIMITS:
        return WOHNGELD_RENT_LIMITS[n]
    # Extrapolate: +120€ per person beyond 7
    base  = WOHNGELD_RENT_LIMITS[7]
    extra = n - 7
    return base + extra * _WG_STEP


def get_size_limit(household_size: int) -> int:
    """Return max apartment size (m²) for Jobcenter approval."""
    n = _clamp_positive(household_size)
    if n in JOBCENTER_SIZE_LIMITS:
        return JOBCENTER_SIZE_LIMITS[n]
    # Extrapolate: +10m² per person beyond 6
    base  = JOBCENTER_SIZE_LIMITS[6]
    extra = n - 6
    return base + extra * _SZ_STEP


def passes_jobcenter(listing: dict, household_size: int) -> bool:
    """
    Returns True if listing qualifies for Jobcenter KdU approval.
    Checks Warmmiete ≤ limit AND size ≤ limit (only if size is known).
    price=None → benefit of the doubt → True.
    price=0 → not a real rent → False.
    """
    price     = listing.get("price")
    size      = listing.get("size_m2")
    price_lim = get_jobcenter_limit(household_size)
    size_lim  = get_size_limit(household_size)

    # price=None → unknown → pass; price=0 → not valid → fail
    if price is not None:
        if price <= 0:
            return False
        if price > price_lim:
            return False

    # Size check: only apply if size is known and positive
    if size is not None and size > 0:
        if size > size_lim:
            return False

    return True


def passes_wohngeld(listing: dict, household_size: int) -> bool:
    """
    Returns True if listing is within Wohngeld rent subsidy limits.
    price=None → True. price=0 → False.
    """
    price = listing.get("price")
    if price is None:
        return True
    if price <= 0:
        return False
    return price <= get_wohngeld_limit(household_size)


def get_social_badge(listing: dict, household_size: int) -> tuple[bool, bool, str]:
    """
    Returns (jobcenter_ok, wohngeld_ok, badge_text).
    OR logic: listing is viable if EITHER condition is met.
    """
    jc       = passes_jobcenter(listing, household_size)
    wg       = passes_wohngeld(listing, household_size)
    jc_limit = get_jobcenter_limit(household_size)
    wg_limit = get_wohngeld_limit(household_size)

    if jc and wg:
        badge = "🏛 Jobcenter ✅ · Wohngeld ✅"
    elif jc:
        badge = f"🏛 Jobcenter ✅ ({jc_limit:.0f}€) · Wohngeld ❌"
    elif wg:
        badge = f"🏛 Jobcenter ❌ · Wohngeld ✅ ({wg_limit:.0f}€)"
    else:
        badge = f"🏛 Jobcenter ❌ ({jc_limit:.0f}€ max) · Wohngeld ❌"

    return jc, wg, badge
