"""Unit tests for Fair Value Gap detection and scoring."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.candle import Candle
from strategy.fair_value_gap import detect_fvg_at, score_fvg, find_relevant_fvg, is_mitigated, FvgContext


def _c(i, o, h, l, c):
    return Candle(timestamp=1000 + i * 1000, open=o, high=h, low=l, close=c, volume=1.0)


def test_bullish_fvg_detected():
    # candle[i-2].high < candle[i].low  (i = 2 here)
    data = [_c(0, 100, 101, 99, 100), _c(1, 100, 102, 99, 101), _c(2, 103, 104, 102, 103)]
    fvg = detect_fvg_at(data, 2)
    assert fvg is not None and fvg.fvg_type == "BULLISH"
    assert fvg.lower == 101 and fvg.upper == 102


def test_bearish_fvg_detected():
    # candle[i-2].low > candle[i].high  (i = 2 here)
    data = [_c(0, 100, 101, 99, 100), _c(1, 100, 102, 99, 101), _c(2, 99, 98, 97, 98)]
    fvg = detect_fvg_at(data, 2)
    assert fvg is not None and fvg.fvg_type == "BEARISH"
    # bearish FVG zone is (candle[i].high, candle[i-2].low) -> lower=98, upper=99
    assert fvg.lower == 98 and fvg.upper == 99, (fvg.lower, fvg.upper)


def test_no_fvg_when_overlapping():
    data = [_c(0, 100, 103, 99, 100), _c(1, 100, 102, 99, 101), _c(2, 100, 103, 99, 100)]
    fvg = detect_fvg_at(data, 2)
    assert fvg is None


def test_scoring_accumulates():
    fvg = detect_fvg_at(
        [_c(0, 100, 101, 99, 100), _c(1, 100, 102, 99, 101), _c(2, 103, 104, 102, 103)], 2
    )
    ctx = FvgContext(mss_confirmed=True, displacement_strong=True, near_order_block=True, htf_aligned=True)
    score = score_fvg(fvg, ctx)
    assert score == 10  # 3+3+2+2
    assert fvg.status == "VALID"


def test_scoring_below_threshold():
    fvg = detect_fvg_at(
        [_c(0, 100, 101, 99, 100), _c(1, 100, 102, 99, 101), _c(2, 103, 104, 102, 103)], 2
    )
    ctx = FvgContext()  # all False
    score = score_fvg(fvg, ctx)
    assert score == 0
    assert fvg.status == "OPEN"  # below min valid score of 7


def test_mitigation_detection():
    data = [
        _c(0, 100, 101, 99, 100),
        _c(1, 100, 102, 99, 101),
        _c(2, 103, 104, 102, 103),  # FVG (101, 102)
        _c(3, 103, 104, 100.5, 101),  # trades into the gap
    ]
    fvg = detect_fvg_at(data, 2)
    assert is_mitigated(fvg, data, 3)


def test_fvg_boundary_touch_is_not_mitigation():
    data = [
        _c(0, 100, 101, 99, 100),
        _c(1, 100, 102, 99, 101),
        _c(2, 103, 104, 102, 103),  # FVG (101, 102)
        _c(3, 103, 104, 102, 103),  # touches the lower boundary only
    ]
    fvg = detect_fvg_at(data, 2)
    assert not is_mitigated(fvg, data, 3)


def test_find_relevant_fvg_requires_direction():
    data = [
        _c(0, 100, 101, 99, 100),
        _c(1, 100, 102, 99, 101),
        _c(2, 103, 104, 102, 103),  # bullish fvg
    ]
    ctx = FvgContext(mss_confirmed=True, displacement_strong=True, htf_aligned=True)
    fvg = find_relevant_fvg(data, 2, "BULLISH", ctx, timeframe="15m")
    assert fvg is not None and fvg.score >= 7
    # A bearish request should not pick the bullish gap.
    bear = find_relevant_fvg(data, 2, "BEARISH", ctx, timeframe="15m")
    assert bear is None
