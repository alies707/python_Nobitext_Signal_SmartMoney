"""Chronological liquidity detection for Smart Money setups."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from models.candle import Candle
from models.setup import LiquidityLevel
from strategy.swing_detection import get_structural_swings

EQUAL_TOLERANCE = 0.0015


def _day_key(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _week_key(ts_ms: int) -> str:
    iso = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _group_extremes(candles: List[Candle], index: int, key_func):
    """Return the completed previous period high/low available at ``index``."""
    window = candles[: index + 1]
    if not window:
        return None, None
    periods = {}
    for candle in window:
        periods.setdefault(key_func(candle.timestamp), []).append(candle)
    ordered = list(periods)
    if len(ordered) < 2:
        return None, None
    previous = periods[ordered[-2]]
    return max(c.high for c in previous), min(c.low for c in previous)


def detect_liquidity(
    candles: List[Candle],
    index: int | None = None,
    timeframe: str = "15m",
    include_external: bool = True,
) -> List[LiquidityLevel]:
    """Detect liquidity levels known at ``index`` without future data."""
    n = len(candles)
    if not candles:
        return []
    if index is None:
        index = n - 1
    index = min(index, n - 1)
    if index < 2:
        return []

    levels: List[LiquidityLevel] = []
    created = candles[index].timestamp

    if include_external:
        day_high, day_low = _group_extremes(candles, index, _day_key)
        if day_high is not None:
            levels.extend([
                LiquidityLevel(day_high, "BUY-SIDE", "EXTERNAL", 3, 1.0, 1, timeframe, created),
                LiquidityLevel(day_low, "SELL-SIDE", "EXTERNAL", 3, 1.0, 1, timeframe, created),
            ])
        week_high, week_low = _group_extremes(candles, index, _week_key)
        if week_high is not None:
            levels.extend([
                LiquidityLevel(week_high, "BUY-SIDE", "EXTERNAL", 4, 1.0, 1, timeframe, created),
                LiquidityLevel(week_low, "SELL-SIDE", "EXTERNAL", 4, 1.0, 1, timeframe, created),
            ])

    highs, lows = get_structural_swings(candles, index=index)
    for swing in highs:
        levels.append(LiquidityLevel(
            swing.price, "BUY-SIDE", "EXTERNAL", 3, 1.0, 1,
            timeframe, created, swing.index,
        ))
    for swing in lows:
        levels.append(LiquidityLevel(
            swing.price, "SELL-SIDE", "EXTERNAL", 3, 1.0, 1,
            timeframe, created, swing.index,
        ))

    levels.extend(_equal_levels(highs, "BUY-SIDE", timeframe, created))
    levels.extend(_equal_levels(lows, "SELL-SIDE", timeframe, created))
    return _merge_levels(levels)


def _equal_levels(swings, side, timeframe, created):
    """Create equal-price liquidity groups while preserving side."""
    groups: List[LiquidityLevel] = []
    for swing in swings:
        match = next(
            (level for level in groups
             if abs(swing.price - level.price) / max(abs(level.price), 1e-12) <= EQUAL_TOLERANCE),
            None,
        )
        if match is None:
            groups.append(LiquidityLevel(
                swing.price, side, "INTERNAL", 2, 0.5, 1,
                timeframe, created, swing.index,
            ))
        else:
            match.score += 2
            match.tests += 1
            match.strength = min(1.0, match.strength + 0.2)
    return groups


def _merge_levels(levels: List[LiquidityLevel]) -> List[LiquidityLevel]:
    """Merge only same-side, near-identical levels.

    Buy-side and sell-side liquidity at similar prices are intentionally kept
    separate. Merging them previously could manufacture a stronger pool than
    the underlying market evidence justified.
    """
    merged: List[LiquidityLevel] = []
    for level in levels:
        match = next(
            (item for item in merged
             if item.level_type == level.level_type
             and abs(level.price - item.price) / max(abs(item.price), 1e-12) <= EQUAL_TOLERANCE),
            None,
        )
        if match is None:
            merged.append(level)
            continue
        match.score += level.score
        match.tests += max(0, level.tests - 1)
        match.strength = min(1.0, match.strength + 0.1)
        if match.candle_index is None:
            match.candle_index = level.candle_index
    return merged


def best_liquidity(
    levels: List[LiquidityLevel], side: Optional[str] = None
) -> Optional[LiquidityLevel]:
    candidates = [level for level in levels if level.score >= 4]
    if side:
        candidates = [level for level in candidates if level.level_type == side]
    if not candidates:
        return None
    return max(candidates, key=lambda x: (x.score, x.strength, x.tests))
