"""Liquidity sweep detection.

A liquidity sweep is a deliberate penetration of a liquidity pool followed by a
rejection (close back through the level):

* Bullish (sell-side) sweep: ``low < level`` AND ``close > level``
* Bearish (buy-side) sweep: ``high > level`` AND ``close < level``

Per specification, a sweep is only relevant to a setup when it occurs no more
than 8 candles before the Market Structure Shift that follows it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from models.candle import Candle
from models.setup import LiquidityLevel
from strategy.liquidity import best_liquidity


@dataclass
class SweepResult:
    confirmed: bool
    sweep_index: Optional[int] = None
    level: Optional[LiquidityLevel] = None
    direction: Optional[str] = None


def _check_candle(candle: Candle, level: LiquidityLevel) -> Optional[str]:
    """Return 'BULLISH'/'BEARISH' if the candle sweeps ``level``, else None.

    A sweep must reclaim the level:
    * SELL-SIDE liquidity is swept by a dip below followed by a close back above
      (a bullish rejection),
    * BUY-SIDE liquidity is swept by a spike above followed by a close back below
      (a bearish rejection).
    """
    if level.level_type == "SELL-SIDE":
        if candle.low < level.price and candle.close > level.price:
            return "BULLISH"
    elif level.level_type == "BUY-SIDE":
        if candle.high > level.price and candle.close < level.price:
            return "BEARISH"
    return None


def detect_sweep(
    candles: List[Candle], index: int | None = None, levels: Optional[List[LiquidityLevel]] = None
) -> SweepResult:
    """Detect a sweep on the candle at ``index`` across the supplied levels."""
    if index is None:
        index = len(candles) - 1
    if index < 0 or not candles:
        return SweepResult(confirmed=False)
    candle = candles[index]
    levels = levels or []
    for level in levels:
        direction = _check_candle(candle, level)
        if direction:
            return SweepResult(confirmed=True, sweep_index=index, level=level, direction=direction)
    return SweepResult(confirmed=False)


def detect_sweep_before(
    candles: List[Candle],
    mss_index: int,
    levels: List[LiquidityLevel],
    expected_direction: str = "BULLISH",
    max_gap: int = 8,
) -> SweepResult:
    """Search backward from ``mss_index`` for a sweep of the given direction.

    ``expected_direction`` is the direction of the setup (BULLISH setup sweeps
    sell-side liquidity). The sweep must be within ``max_gap`` candles of the
    MSS, otherwise it is considered stale and rejected.
    """
    if mss_index < 1 or not levels:
        return SweepResult(confirmed=False)

    start = max(0, mss_index - max_gap)
    # A bullish setup sweeps SELL-SIDE liquidity; a bearish setup sweeps
    # BUY-SIDE liquidity. Restrict candidate levels to the correct side.
    required_side = "SELL-SIDE" if expected_direction == "BULLISH" else "BUY-SIDE"
    # Iterate from closest to MSS first so we capture the most relevant sweep.
    for i in range(mss_index, start - 1, -1):
        candle = candles[i]
        for level in levels:
            if level.level_type != required_side:
                continue
            direction = _check_candle(candle, level)
            if direction and direction == expected_direction:
                return SweepResult(confirmed=True, sweep_index=i, level=level, direction=direction)
    return SweepResult(confirmed=False)


def best_sweep_side(levels: List[LiquidityLevel]) -> Optional[str]:
    """Given tradable levels, return the dominant side to be swept."""
    sell = [l for l in levels if l.level_type == "SELL-SIDE" and l.score >= 4]
    buy = [l for l in levels if l.level_type == "BUY-SIDE" and l.score >= 4]
    if not sell and not buy:
        return None
    if len(sell) >= len(buy):
        return "SELL-SIDE"
    return "BUY-SIDE"
