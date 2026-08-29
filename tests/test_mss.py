"""Unit tests for MSS detection."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.helpers import make_bars
from strategy.mss import detect_mss
from strategy.liquidity import detect_liquidity


BULLISH_SPECS = [
    (100,100,1,1,1), (100,110,1,1,1), (110,130,1,1,1), (130,150,1,1,1),
    (150,165,1,1,1), (165,172,1,1,1), (172,178,1,1,1), (178,180,1,1,1),
    (178,176,2,1,1), (176,172,1,1,1), (172,168,1,1,1), (168,172,1,1,1),
    (172,180,1,1,1), (180,174,0,1,1), (174,150,1,1,1), (150,120,0,0,1),
    (121,128,1,0,1), (128,132,1,1,1), (132,135,1,1,1), (133,128,1,1,1),
    (128,124,1,1,1), (124,122,1,1,1), (122,121,1,1,1), (121,121,1,1,1),
    (122,121,3,3,50), (121,140,1,1,60), (140,149,1,1,1), (149,150,1,1,1),
    (150,151,1,1,1), (151,152,1,1,1),
]


def _bearish_mirror(specs, center=150.0, offset=200.0):
    # Invert the bullish shape around ``center`` for price levels (open->open,
    # close->close; wicks swap), then shift up by a constant ``offset`` so all
    # prices stay positive. A constant offset preserves every relative
    # relationship, so the resulting series is a clean bearish twin.
    return [(offset + center - o, offset + center - c, wd, wu, v) for (o, c, wu, wd, v) in specs]


def test_bullish_mss_detected():
    data = make_bars(BULLISH_SPECS)
    levels = detect_liquidity(data, index=25, timeframe="15m")
    res = detect_mss(data, index=25, levels=levels)
    assert res.confirmed
    assert res.direction == "BULLISH"
    assert res.sweep_index is not None


def test_no_mss_without_displacement():
    data = make_bars(BULLISH_SPECS)
    # Replace the displacement candle with a weak one.
    bad = make_bars(BULLISH_SPECS)
    from models.candle import Candle
    bad[25] = Candle(timestamp=bad[25].timestamp, open=121, high=123, low=120, close=122, volume=1.0)
    levels = detect_liquidity(bad, index=25, timeframe="15m")
    res = detect_mss(bad, index=25, levels=levels)
    assert not res.confirmed


def test_no_mss_without_sweep():
    data = make_bars(BULLISH_SPECS)
    bad = make_bars(BULLISH_SPECS)
    from models.candle import Candle
    # Remove BOTH sweep wicks (indices 23 and 24), lows stay >= 120 so the
    # 120 SELL-SIDE liquidity is never taken.
    bad[23] = Candle(timestamp=bad[23].timestamp, open=122, high=125, low=121, close=124, volume=50.0)
    bad[24] = Candle(timestamp=bad[24].timestamp, open=122, high=125, low=121, close=124, volume=50.0)
    levels = detect_liquidity(bad, index=25, timeframe="15m")
    res = detect_mss(bad, index=25, levels=levels)
    assert not res.confirmed


def test_bearish_mss_detected():
    data = make_bars(_bearish_mirror(BULLISH_SPECS))
    levels = detect_liquidity(data, index=25, timeframe="15m")
    res = detect_mss(data, index=25, levels=levels)
    assert res.confirmed
    assert res.direction == "BEARISH"
