"""Unit tests for premium / discount classification."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy.premium_discount import (
    compute_equilibrium,
    classify_zone,
    is_favorable,
    favorable_zone_bounds,
)
from models.setup import ZoneType


def test_equilibrium_midpoint():
    assert compute_equilibrium(100, 200) == 150


def test_classify_discount():
    # entry in lower half of range [100, 200] -> discount
    assert classify_zone(120, 200, 100) == ZoneType.DISCOUNT


def test_classify_premium():
    assert classify_zone(180, 200, 100) == ZoneType.PREMIUM


def test_classify_equilibrium_band():
    assert classify_zone(150, 200, 100) == ZoneType.EQUILIBRIUM


def test_favorable_long_below_equilibrium():
    assert is_favorable(120, "BULLISH", 200, 100) is True
    assert is_favorable(180, "BULLISH", 200, 100) is False


def test_favorable_short_above_equilibrium():
    assert is_favorable(180, "BEARISH", 200, 100) is True
    assert is_favorable(120, "BEARISH", 200, 100) is False


def test_favorable_zone_bounds_long():
    lo, hi = favorable_zone_bounds("LONG", 200, 100)
    assert lo == 100 and hi == 150


def test_favorable_zone_bounds_short():
    lo, hi = favorable_zone_bounds("SHORT", 200, 100)
    assert lo == 150 and hi == 200
