"""Unit tests for liquidity sweep detection."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.candle import Candle
from strategy.liquidity_sweep import detect_sweep, detect_sweep_before, SweepResult
from models.setup import LiquidityLevel


def _c(i, o, h, l, c):
    return Candle(timestamp=1000 + i * 1000, open=o, high=h, low=l, close=c, volume=1.0)


def test_bullish_sweep():
    sell_side = LiquidityLevel(
        price=100, level_type="SELL-SIDE", liquidity_class="EXTERNAL",
        score=5, strength=1.0, tests=1, timeframe="15m", created_at=0,
    )
    # Candle dips below 100 then closes above it.
    candle = _c(0, 101, 102, 99, 101.5)
    res = detect_sweep([candle], index=0, levels=[sell_side])
    assert res.confirmed and res.direction == "BULLISH"


def test_bearish_sweep():
    buy_side = LiquidityLevel(
        price=200, level_type="BUY-SIDE", liquidity_class="EXTERNAL",
        score=5, strength=1.0, tests=1, timeframe="15m", created_at=0,
    )
    candle = _c(0, 199, 201, 198, 199.5)
    res = detect_sweep([candle], index=0, levels=[buy_side])
    assert res.confirmed and res.direction == "BEARISH"


def test_no_sweep_when_not_closed_through():
    sell_side = LiquidityLevel(
        price=100, level_type="SELL-SIDE", liquidity_class="EXTERNAL",
        score=5, strength=1.0, tests=1, timeframe="15m", created_at=0,
    )
    # Dips below but closes back below the level (no rejection).
    candle = _c(0, 101, 102, 99, 99.5)
    res = detect_sweep([candle], index=0, levels=[sell_side])
    assert not res.confirmed


def test_sweep_before_respects_gap_limit():
    sell_side = LiquidityLevel(
        price=100, level_type="SELL-SIDE", liquidity_class="EXTERNAL",
        score=5, strength=1.0, tests=1, timeframe="15m", created_at=0,
    )
    candles = [_c(i, 101, 102, 100.5, 101) for i in range(20)]
    # Put a valid sweep 11 candles before the MSS index 19 (gap > 8).
    candles[8] = _c(8, 101, 102, 99, 101.5)
    res = detect_sweep_before(candles, mss_index=19, levels=[sell_side],
                              expected_direction="BULLISH", max_gap=8)
    assert not res.confirmed  # 11 > 8 gap -> rejected


def test_sweep_before_found_within_gap():
    sell_side = LiquidityLevel(
        price=100, level_type="SELL-SIDE", liquidity_class="EXTERNAL",
        score=5, strength=1.0, tests=1, timeframe="15m", created_at=0,
    )
    candles = [_c(i, 101, 102, 100.5, 101) for i in range(20)]
    candles[15] = _c(15, 101, 102, 99, 101.5)  # within 8 of index 19
    res = detect_sweep_before(candles, mss_index=19, levels=[sell_side],
                              expected_direction="BULLISH", max_gap=8)
    assert res.confirmed and res.sweep_index == 15


def test_wrong_side_not_swept():
    buy_side = LiquidityLevel(
        price=200, level_type="BUY-SIDE", liquidity_class="EXTERNAL",
        score=5, strength=1.0, tests=1, timeframe="15m", created_at=0,
    )
    # A bullish-style sweep should not match a BUY-SIDE level.
    candles = [_c(i, 101, 102, 100.5, 101) for i in range(20)]
    candles[15] = _c(15, 101, 102, 99, 101.5)
    res = detect_sweep_before(candles, mss_index=19, levels=[buy_side],
                              expected_direction="BULLISH", max_gap=8)
    assert not res.confirmed
