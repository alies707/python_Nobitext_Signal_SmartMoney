"""Premium / Discount / Equilibrium analysis.

Given a dealing range (``range_high``, ``range_low``) and a reference entry, the
price is classified as:

* DISCOUNT   : entry in the lower half (toward the low)
* PREMIUM    : entry in the upper half (toward the high)
* EQUILIBRIUM: within a small band around the 50% level

For Smart Money entries:
* LONG setups should enter at DISCOUNT (or at least at/below equilibrium)
* SHORT setups should enter at PREMIUM (or at least at/above equilibrium)
"""
from __future__ import annotations

from typing import Optional, Tuple

from models.setup import ZoneType


def compute_equilibrium(range_high: float, range_low: float) -> float:
    return (range_high + range_low) / 2.0


def classify_zone(
    entry: float,
    range_high: float,
    range_low: float,
    band_pct: float = 0.05,
) -> ZoneType:
    """Classify ``entry`` relative to the dealing range."""
    if range_high <= range_low:
        return ZoneType.EQUILIBRIUM
    eq = compute_equilibrium(range_high, range_low)
    band = (range_high - range_low) * band_pct
    if entry <= eq - band:
        return ZoneType.DISCOUNT
    if entry >= eq + band:
        return ZoneType.PREMIUM
    return ZoneType.EQUILIBRIUM


def is_favorable(entry: float, direction: str, range_high: float, range_low: float) -> bool:
    """Return True when the entry is in the preferred zone for the direction."""
    zone = classify_zone(entry, range_high, range_low)
    if direction == "BULLISH" or direction == "LONG":
        return zone in (ZoneType.DISCOUNT, ZoneType.EQUILIBRIUM)
    if direction == "BEARISH" or direction == "SHORT":
        return zone in (ZoneType.PREMIUM, ZoneType.EQUILIBRIUM)
    return False


def favorable_zone_bounds(
    direction: str, range_high: float, range_low: float
) -> Tuple[float, float]:
    """Return the (low, high) bounds of the favorable entry zone."""
    eq = compute_equilibrium(range_high, range_low)
    if direction in ("BULLISH", "LONG"):
        return range_low, eq
    if direction in ("BEARISH", "SHORT"):
        return eq, range_high
    return range_low, range_high
