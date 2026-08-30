"""Regression tests for Order Block freshness and causal validation."""
from models.candle import Candle
from strategy.order_block import detect_order_block


def _c(o, h, l, close, i):
    return Candle(timestamp=1_700_000_000_000 + i * 900_000, open=o, high=h, low=l, close=close, volume=1.0)


def test_bullish_ob_must_be_recent_and_followed_by_directional_break():
    candles = [
        _c(100, 101, 99, 100, 0),
        _c(100, 101, 98, 99, 1),
        _c(99, 100, 98, 99.5, 2),
        _c(99.5, 101.5, 99.4, 101.2, 3),
        _c(101.2, 104, 101, 103.5, 4),
    ]
    ob = detect_order_block(candles, 4, "BULLISH", "15m")
    assert ob is not None
    assert ob.validated is True
    assert ob.creation_index == 1


def test_old_unrelated_opposing_candle_is_not_used_as_ob():
    candles = [
        _c(100, 101, 99, 99.5, 0),
        _c(99.5, 100, 98, 98.5, 1),
        _c(98.5, 99, 97, 97.5, 2),
        _c(97.5, 98, 96, 96.5, 3),
        _c(96.5, 97, 95, 96, 4),
        _c(96, 99, 95.8, 98.5, 5),
    ]
    ob = detect_order_block(candles, 5, "BULLISH", "15m")
    assert ob is None
