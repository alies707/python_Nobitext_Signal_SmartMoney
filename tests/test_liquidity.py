"""Unit tests for liquidity detection and scoring."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.candle import Candle
from strategy.liquidity import detect_liquidity, best_liquidity


def _c(i, o, h, l, c):
    return Candle(timestamp=1_600_000_000_000 + i * 86_400_000, open=o, high=h, low=l, close=c, volume=1.0)


def test_no_liquidity_on_tiny_series():
    data = [_c(0, 100, 101, 99, 100), _c(1, 100, 103, 99, 102)]
    levels = detect_liquidity(data, index=1, timeframe="15m")
    assert levels == []


def test_swing_liquidity_created():
    # A clear swing high and low.
    data = [
        _c(0, 100, 101, 99, 100),
        _c(1, 100, 103, 99, 102),
        _c(2, 102, 104, 101, 103),
        _c(3, 103, 110, 102, 108),
        _c(4, 108, 109, 107, 106),
        _c(5, 106, 107, 104, 105),
    ]
    levels = detect_liquidity(data, index=5, timeframe="15m")
    # Expect at least one BUY-SIDE (swing high) and one SELL-SIDE (swing low).
    types = {(l.level_type, l.score) for l in levels}
    assert any(t[0] == "BUY-SIDE" for t in types)
    assert any(t[0] == "SELL-SIDE" for t in types)


def test_equal_highs_accumulate_score():
    # Two equal swing highs should merge and accumulate a higher score.
    data = [
        _c(0, 100, 101, 99, 100),
        _c(1, 100, 103, 99, 102),
        _c(2, 102, 104, 101, 103),
        _c(3, 103, 110, 102, 108),  # peak A
        _c(4, 108, 109, 107, 106),
        _c(5, 106, 107, 104, 105),
        _c(6, 105, 106, 103, 104),
        _c(7, 104, 105, 102, 103),
        _c(8, 103, 110, 102, 108),  # peak B (equal to A)
        _c(9, 108, 109, 107, 106),
        _c(10, 106, 107, 104, 105),
    ]
    levels = detect_liquidity(data, index=10, timeframe="15m")
    buy = [l for l in levels if l.level_type == "BUY-SIDE"]
    # The merged equal-high level should score higher than a single swing high.
    best = max(buy, key=lambda x: x.score)
    assert best.score >= 5  # 3 (major swing) + 2 (equal) at least


def test_best_liquidity_requires_score_4():
    data = [
        _c(0, 100, 101, 99, 100),
        _c(1, 100, 103, 99, 102),
        _c(2, 102, 104, 101, 103),
        _c(3, 103, 110, 102, 108),  # single swing high, score 3
        _c(4, 108, 109, 107, 106),
        _c(5, 106, 107, 104, 105),
    ]
    levels = detect_liquidity(data, index=5, timeframe="15m")
    # Single swing high/low only -> no level reaches score 4.
    assert best_liquidity(levels) is None or best_liquidity(levels).score >= 4
