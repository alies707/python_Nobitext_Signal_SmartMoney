"""Unit tests for Order Block detection."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.candle import Candle
from strategy.order_block import detect_order_block, fvg_near_ob


def _c(i, o, h, l, c):
    return Candle(timestamp=1000 + i * 1000, open=o, high=h, low=l, close=c, volume=1.0)


def test_bullish_order_block_is_last_bearish_candle():
    # Last bearish candle before the bullish displacement at index 5.
    data = [
        _c(0, 100, 101, 99, 100),
        _c(1, 100, 102, 99, 101),
        _c(2, 101, 103, 100, 102),
        _c(3, 102, 104, 101, 103),
        _c(4, 103, 104, 100, 101),  # bearish -> order block
        _c(5, 101, 112, 100, 110),  # bullish displacement
        _c(6, 110, 113, 109, 111),
    ]
    ob = detect_order_block(data, 5, "BULLISH", timeframe="15m")
    assert ob is not None
    assert ob.ob_type == "BULLISH"
    assert ob.creation_index == 4


def test_bearish_order_block_is_last_bullish_candle():
    data = [
        _c(0, 200, 201, 199, 200),
        _c(1, 200, 202, 199, 201),
        _c(2, 201, 203, 200, 202),
        _c(3, 201, 203, 200, 202),  # bullish -> order block
        _c(4, 201, 202, 190, 192),  # bearish displacement
        _c(5, 192, 193, 189, 191),
    ]
    ob = detect_order_block(data, 4, "BEARISH", timeframe="15m")
    assert ob is not None
    assert ob.ob_type == "BEARISH"
    assert ob.creation_index == 3


def test_order_block_invalidated_loses_freshness():
    data = [
        _c(0, 100, 101, 99, 100),
        _c(1, 100, 102, 99, 101),
        _c(2, 101, 103, 100, 102),
        _c(3, 102, 104, 101, 103),
        _c(4, 103, 104, 95, 96),   # bearish OB at ~95-104
        _c(5, 96, 112, 95, 110),   # bullish displacement
        _c(6, 110, 113, 90, 92),    # later closes below OB low -> not fresh
    ]
    ob = detect_order_block(data, 5, "BULLISH", timeframe="15m")
    assert ob is not None
    assert ob.fresh is False


def test_fvg_near_ob_overlap():
    from models.setup import FVG
    ob = type("OB", (), {"zone_low": 100.0, "zone_high": 105.0})()
    fvg = FVG(fvg_type="BULLISH", lower=103.0, upper=108.0, creation_index=0, timeframe="15m")
    assert fvg_near_ob(fvg.lower, fvg.upper, ob) is True
    fvg2 = FVG(fvg_type="BULLISH", lower=200.0, upper=205.0, creation_index=0, timeframe="15m")
    assert fvg_near_ob(fvg2.lower, fvg2.upper, ob) is False
