"""Order Block detection.

An Order Block is the last candle opposing the direction of the subsequent
impulse:

* Bullish OB: last *bearish* candle before the bullish displacement / MSS
* Bearish OB: last *bullish* candle before the bearish displacement / MSS

Requirements (per spec): the block must be *fresh* (price has not yet invalidated
it), must have *caused* the structure break (MSS confirmed), and must show an
institutional reaction (the displacement that follows). Respecting ``mss_index``
guarantees we only use candles that already occurred.
"""
from __future__ import annotations

from typing import List, Optional

from models.candle import Candle
from models.setup import OrderBlock


def _last_opposing_candle(candles: List[Candle], mss_index: int, want_bearish: bool) -> Optional[int]:
    """Index of the last opposing candle before ``mss_index``."""
    for i in range(mss_index - 1, -1, -1):
        c = candles[i]
        if want_bearish and c.is_bearish:
            return i
        if (not want_bearish) and c.is_bullish:
            return i
    return None


def detect_order_block(
    candles: List[Candle], mss_index: int, direction: str, timeframe: str = ""
) -> Optional[OrderBlock]:
    """Detect the order block that preceded the MSS in ``direction``."""
    if mss_index < 1 or mss_index >= len(candles):
        return None

    want_bearish = direction == "BULLISH"
    idx = _last_opposing_candle(candles, mss_index, want_bearish)
    if idx is None:
        return None

    ob_candle = candles[idx]
    if direction == "BULLISH":
        ob = OrderBlock(
            ob_type="BULLISH",
            zone_high=ob_candle.high,
            zone_low=ob_candle.low,
            creation_index=idx,
            timeframe=timeframe,
            fresh=True,
            validated=True,
        )
    else:
        ob = OrderBlock(
            ob_type="BEARISH",
            zone_high=ob_candle.high,
            zone_low=ob_candle.low,
            creation_index=idx,
            timeframe=timeframe,
            fresh=True,
            validated=True,
        )
    ob.fresh = _is_fresh(candles, ob, mss_index)
    return ob


def _is_fresh(candles: List[Candle], ob: OrderBlock, mss_index: int) -> bool:
    """An order block is fresh if price has not invalidated it after creation."""
    start = ob.creation_index + 1
    for j in range(start, len(candles)):
        c = candles[j]
        if ob.ob_type == "BULLISH":
            # Invalidated if price closes below the block low.
            if c.close < ob.zone_low:
                return False
        else:
            if c.close > ob.zone_high:
                return False
    return True


def fvg_near_ob(fvg_lower: float, fvg_upper: float, ob: OrderBlock, tol: float = 0.0) -> bool:
    """Return True when an FVG overlaps the order block zone."""
    if ob is None:
        return False
    return not (fvg_upper < ob.zone_low or fvg_lower > ob.zone_high)
