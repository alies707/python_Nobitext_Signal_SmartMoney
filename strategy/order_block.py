"""Validated Order Block detection for the Smart Money strategy."""
from __future__ import annotations

from typing import List, Optional

from models.candle import Candle
from models.setup import OrderBlock

MAX_OB_LOOKBACK = 12


def _last_opposing_candle(candles: List[Candle], mss_index: int, want_bearish: bool) -> Optional[int]:
    """Find a recent opposing candle that plausibly initiated the MSS leg.

    A distant opposing candle is not accepted merely because it is the last one
    of its color. The candidate must be close to the MSS and be followed by a
    directional reaction before the MSS candle.
    """
    start = max(0, mss_index - MAX_OB_LOOKBACK)
    for i in range(mss_index - 1, start - 1, -1):
        c = candles[i]
        if want_bearish and not c.is_bearish:
            continue
        if not want_bearish and not c.is_bullish:
            continue

        reaction_found = False
        for j in range(i + 1, mss_index + 1):
            r = candles[j]
            if want_bearish and r.close > c.high:
                reaction_found = True
                break
            if not want_bearish and r.close < c.low:
                reaction_found = True
                break
        if reaction_found:
            return i
    return None


def detect_order_block(candles: List[Candle], mss_index: int, direction: str, timeframe: str = "") -> Optional[OrderBlock]:
    """Detect a recent, fresh and structure-relevant Order Block before MSS."""
    if mss_index < 1 or mss_index >= len(candles):
        return None

    want_bearish = direction == "BULLISH"
    idx = _last_opposing_candle(candles, mss_index, want_bearish)
    if idx is None:
        return None

    ob_candle = candles[idx]
    ob_type = "BULLISH" if direction == "BULLISH" else "BEARISH"
    ob = OrderBlock(
        ob_type=ob_type,
        zone_high=ob_candle.high,
        zone_low=ob_candle.low,
        creation_index=idx,
        timeframe=timeframe,
        fresh=True,
        validated=True,
    )
    ob.fresh = _is_fresh(candles, ob, mss_index)
    ob.validated = ob.fresh and _has_directional_break(candles, ob, idx, mss_index)
    if not ob.fresh or not ob.validated:
        return None
    return ob


def _has_directional_break(candles: List[Candle], ob: OrderBlock, start: int, mss_index: int) -> bool:
    """Require price to leave the OB decisively before the MSS is confirmed."""
    for j in range(start + 1, mss_index + 1):
        c = candles[j]
        if ob.ob_type == "BULLISH" and c.close > ob.zone_high:
            return True
        if ob.ob_type == "BEARISH" and c.close < ob.zone_low:
            return True
    return False


def _is_fresh(candles: List[Candle], ob: OrderBlock, mss_index: int) -> bool:
    """An OB is fresh when no post-creation candle closes through its invalidation edge."""
    for j in range(ob.creation_index + 1, mss_index + 1):
        c = candles[j]
        if ob.ob_type == "BULLISH" and c.close < ob.zone_low:
            return False
        if ob.ob_type == "BEARISH" and c.close > ob.zone_high:
            return False
    return True


def fvg_near_ob(fvg_lower: float, fvg_upper: float, ob: OrderBlock, tol: float = 0.0) -> bool:
    """Return True when an FVG overlaps or touches the order-block zone."""
    if ob is None:
        return False
    return not (fvg_upper < ob.zone_low - tol or fvg_lower > ob.zone_high + tol)
