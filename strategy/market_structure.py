"""Market structure analysis (HH / HL / LH / LL, BOS, MSS).

All functions accept the current processing ``index`` and only inspect candles
up to and including it, preserving chronological determinism (no look-ahead).

Definitions used
----------------
* Higher High (HH): last swing high > previous swing high
* Higher Low  (HL): last swing low  > previous swing low  -> bullish structure
* Lower High  (LH): last swing high < previous swing high
* Lower Low   (LL): last swing low  < previous swing low  -> bearish structure
* BOS (Bullish): price closes above the most recent swing high (trend
  continuation to the upside)
* BOS (Bearish): price closes below the most recent swing low
* MSS (Bullish): in a bearish/neutral context, price closes above the most
  recent internal swing high (structural shift)
* MSS (Bearish): in a bullish/neutral context, price closes below the most
  recent internal swing low
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple

from models.candle import Candle
from models.setup import SwingPoint
from strategy.swing_detection import get_structural_swings


class StructureTrend(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass
class StructureResult:
    trend: StructureTrend
    hh: bool = False
    hl: bool = False
    lh: bool = False
    ll: bool = False
    bos_bullish: bool = False
    bos_bearish: bool = False
    mss_bullish: bool = False
    mss_bearish: bool = False
    last_swing_high: Optional[SwingPoint] = None
    last_swing_low: Optional[SwingPoint] = None


def _last_before(points: List[SwingPoint], index: int) -> Optional[SwingPoint]:
    for p in reversed(points):
        if p.index <= index:
            return p
    return None


def classify_structure(
    highs: List[SwingPoint], lows: List[SwingPoint]
) -> Tuple[StructureTrend, dict]:
    """Return the prevailing trend from the last two swing highs/lows."""
    res = {
        "hh": False,
        "hl": False,
        "lh": False,
        "ll": False,
    }
    if len(highs) >= 2 and len(lows) >= 2:
        res["hh"] = highs[-1].price > highs[-2].price
        res["hl"] = lows[-1].price > lows[-2].price
        res["lh"] = highs[-1].price < highs[-2].price
        res["ll"] = lows[-1].price < lows[-2].price

    if res["hh"] and res["hl"]:
        trend = StructureTrend.BULLISH
    elif res["lh"] and res["ll"]:
        trend = StructureTrend.BEARISH
    else:
        trend = StructureTrend.NEUTRAL
    return trend, res


def analyze_structure(
    candles: List[Candle],
    index: int | None = None,
    left: int = 2,
    right: int = 2,
    prior_trend: Optional[StructureTrend] = None,
) -> StructureResult:
    """Analyze market structure up to ``index``.

    ``prior_trend`` lets the caller supply a higher-timeframe bias so that MSS
    is evaluated relative to the broader context.
    """
    n = len(candles)
    if index is None:
        index = n - 1
    index = min(index, n - 1)
    if index < 1:
        return StructureResult(trend=StructureTrend.NEUTRAL)

    highs, lows = get_structural_swings(candles, index=index, left=left, right=right)
    trend, flags = classify_structure(highs, lows)

    sh = _last_before(highs, index)
    sl = _last_before(lows, index)

    result = StructureResult(
        trend=trend,
        hh=flags["hh"],
        hl=flags["hl"],
        lh=flags["lh"],
        ll=flags["ll"],
        last_swing_high=sh,
        last_swing_low=sl,
    )

    close = candles[index].close
    if sh is not None:
        if close > sh.price:
            result.bos_bullish = True
            if trend in (StructureTrend.BEARISH, StructureTrend.NEUTRAL):
                result.mss_bullish = True
    if sl is not None:
        if close < sl.price:
            result.bos_bearish = True
            if trend in (StructureTrend.BULLISH, StructureTrend.NEUTRAL):
                result.mss_bearish = True

    # If a higher-timeframe bias is supplied, MSS is also true when the close
    # breaks the internal swing against that bias.
    if prior_trend == StructureTrend.BEARISH and sh is not None and close > sh.price:
        result.mss_bullish = True
    if prior_trend == StructureTrend.BULLISH and sl is not None and close < sl.price:
        result.mss_bearish = True

    return result
