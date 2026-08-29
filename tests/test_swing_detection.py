"""Unit tests for deterministic swing detection."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.candle import Candle
from strategy.swing_detection import detect_swings, get_structural_swings


def _c(i, o, h, l, c):
    return Candle(timestamp=1000 + i * 1000, open=o, high=h, low=l, close=c, volume=1.0)


def test_swing_high_detected():
    # Peak at index 3 (strictly higher than 2 on each side).
    data = [
        _c(0, 100, 101, 99, 100),
        _c(1, 100, 103, 99, 102),
        _c(2, 102, 104, 101, 103),
        _c(3, 103, 110, 102, 108),  # peak
        _c(4, 108, 109, 107, 106),
        _c(5, 106, 107, 104, 105),
    ]
    highs, lows = get_structural_swings(data, index=5)
    assert any(s.index == 3 and s.kind == "HIGH" for s in highs)


def test_swing_low_detected():
    data = [
        _c(0, 100, 101, 99, 100),
        _c(1, 100, 103, 99, 102),
        _c(2, 102, 104, 101, 103),
        _c(3, 103, 104, 95, 98),  # trough
        _c(4, 98, 109, 97, 106),
        _c(5, 106, 107, 104, 105),
    ]
    highs, lows = get_structural_swings(data, index=5)
    assert any(s.index == 3 and s.kind == "LOW" for s in lows)


def test_no_swings_with_insufficient_data():
    data = [_c(0, 100, 101, 99, 100), _c(1, 100, 102, 99, 101)]
    swings = detect_swings(data, index=1)
    assert swings == []


def test_look_ahead_safety():
    # A swing at index 3 needs indices 4 and 5 to confirm the right window.
    data = [
        _c(0, 100, 101, 99, 100),
        _c(1, 100, 103, 99, 102),
        _c(2, 102, 104, 101, 103),
        _c(3, 103, 110, 102, 108),
        _c(4, 108, 109, 107, 106),
        _c(5, 106, 107, 104, 105),
        _c(6, 105, 106, 103, 104),
        _c(7, 104, 105, 102, 103),
    ]
    highs, _ = get_structural_swings(data, index=4)
    assert not any(s.index == 3 for s in highs)  # not confirmed yet (needs index 5)
    highs, _ = get_structural_swings(data, index=5)
    assert any(s.index == 3 for s in highs)      # confirmed once index 5 exists


def test_equal_highs_not_double_counted_as_single_swing():
    data = [
        _c(0, 100, 101, 99, 100),
        _c(1, 100, 103, 99, 102),
        _c(2, 102, 104, 101, 103),
        _c(3, 103, 110, 102, 108),  # peak A
        _c(4, 108, 105, 104, 106),  # dip between peaks
        _c(5, 106, 107, 104, 105),
        _c(6, 105, 106, 103, 104),
        _c(7, 104, 105, 102, 103),
        _c(8, 103, 110, 102, 108),  # peak B (equal to A)
        _c(9, 108, 109, 107, 106),
        _c(10, 106, 107, 104, 105),
    ]
    highs, _ = get_structural_swings(data, index=10)
    # Two separated equal peaks both qualify as swing highs.
    peaks = [s.index for s in highs if s.kind == "HIGH"]
    assert 3 in peaks and 8 in peaks
