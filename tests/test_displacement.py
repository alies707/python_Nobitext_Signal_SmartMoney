"""Unit tests for displacement detection."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.candle import Candle
from strategy.displacement import detect_displacement


def _c(i, o, h, l, c, v=1.0):
    return Candle(timestamp=1000 + i * 1000, open=o, high=h, low=l, close=c, volume=v)


def _base(n=25, v=1.0):
    # Calm series so ATR and volume averages are well-defined.
    out = []
    for i in range(n):
        out.append(_c(i, 100 + i, 101 + i, 99 + i, 100 + i, v))
    return out


def test_bullish_displacement():
    data = _base()
    # Strong bullish candle with close in upper 25%, big body, high volume.
    data.append(_c(25, 125, 160, 124, 158, 100.0))
    res = detect_displacement(data, index=25)
    assert res.confirmed and res.direction == "BULLISH"


def test_bearish_displacement():
    data = _base()
    data.append(_c(25, 125, 126, 90, 92, 100.0))  # big bearish body, low close
    res = detect_displacement(data, index=25)
    assert res.confirmed and res.direction == "BEARISH"


def test_no_displacement_insufficient_volume():
    data = _base()
    data.append(_c(25, 125, 160, 124, 158, 1.0))  # big body but normal volume
    res = detect_displacement(data, index=25)
    assert not res.confirmed


def test_no_displacement_close_not_upper_quartile():
    data = _base()
    # Body big and high volume, but close in the middle of the range.
    data.append(_c(25, 100, 160, 99, 130, 100.0))
    res = detect_displacement(data, index=25)
    assert not res.confirmed


def test_handles_zero_range():
    data = _base()
    data.append(_c(25, 100, 100, 100, 100, 100.0))  # zero range
    res = detect_displacement(data, index=25)
    assert not res.confirmed


def test_insufficient_history_returns_false():
    data = [_c(0, 100, 101, 99, 100), _c(1, 100, 102, 99, 101)]
    res = detect_displacement(data, index=1)
    assert not res.confirmed
