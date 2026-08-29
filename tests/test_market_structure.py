"""Unit tests for market structure analysis (HH/HL/LH/LL, BOS, MSS)."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.candle import Candle
from strategy.market_structure import analyze_structure, StructureTrend


def _c(i, o, h, l, c):
    return Candle(timestamp=1000 + i * 1000, open=o, high=h, low=l, close=c, volume=1.0)


def _bullish_series():
    # Two neutral candles first, then a clean HH/HL zig-zag with swing points
    # starting at index >= 2 (required because swing detection needs a left
    # window of 2 bars).
    return [
        _c(0, 100, 101, 99, 100),
        _c(1, 100, 102, 99, 101),
        _c(2, 100, 101, 99, 100),
        _c(3, 100, 102, 98, 101),   # swing low 98
        _c(4, 101, 104, 100, 103),
        _c(5, 103, 110, 104, 108),  # swing high 110
        _c(6, 108, 109, 104, 105),
        _c(7, 105, 107, 103, 106),  # swing low 103
        _c(8, 106, 108, 104, 107),
        _c(9, 107, 116, 108, 112),  # swing high 116 (HH)
        _c(10, 112, 114, 108, 110),
        _c(11, 110, 115, 107, 113),  # swing low 107 (HL)
    ]


def _bearish_series():
    # Bearish twin of the bullish series: invert each candle around a center
    # and shift up by a constant offset so prices stay positive. The constant
    # offset preserves every relative relationship, so the resulting series is
    # a clean LH/LL (bearish) zig-zag.
    center, offset = 150.0, 200.0
    out = []
    for i, c in enumerate(_bullish_series()):
        out.append(_c(
            i,
            offset + center - c.close,
            offset + center - c.low,
            offset + center - c.high,
            offset + center - c.open,
        ))
    return out


def test_bullish_structure():
    data = _bullish_series()
    res = analyze_structure(data, index=11)
    assert res.trend == StructureTrend.BULLISH
    assert res.hh and res.hl


def test_bearish_structure():
    data = _bearish_series()
    res = analyze_structure(data, index=11)
    assert res.trend == StructureTrend.BEARISH
    assert res.lh and res.ll


def test_bos_bullish_on_close_above_swing_high():
    data = _bullish_series() + [_c(12, 114, 118, 113, 117)]
    res = analyze_structure(data, index=12)
    assert res.bos_bullish


def test_no_structure_on_empty():
    res = analyze_structure([], index=0)
    assert res.trend == StructureTrend.NEUTRAL
