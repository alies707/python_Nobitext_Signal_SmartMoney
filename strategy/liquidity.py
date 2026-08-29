"""Liquidity detection engine.

Detects external and internal liquidity pools and assigns the scoring defined
in the project specification:

* Equal High/Low        +2
* Previous Day Level    +3
* Previous Week Level   +4
* Major Swing           +3
* Multiple Tests        +1 (per additional test beyond the first)

A liquidity level is considered tradable only when its score >= 4 (enforced by
the signal engine, not here, so callers can inspect raw levels).

All detection respects ``index`` so future candles are never used.
"""
from __future__ import annotations

import time as _time
from datetime import datetime, timezone
from typing import List, Optional

from models.candle import Candle
from models.setup import LiquidityLevel
from strategy.swing_detection import get_structural_swings
from utils.logger import get_logger

logger = get_logger(__name__)

DAY_MS = 86_400_000
WEEK_MS = 604_800_000
EQUAL_TOLERANCE = 0.0015  # 0.15%


def _day_key(ts_ms: int) -> str:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")


def _week_key(ts_ms: int) -> str:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _group_extremes(candles: List[Candle], index: int, key_func, label: str):
    """Return (price, strength) for previous period high/low.

    ``key_func`` maps a candle timestamp to a period key. The *previous* period
    relative to the last candle is used so the level is already formed (no
    look-ahead).
    """
    window = candles[: index + 1]
    if not window:
        return None, None
    keys = {}
    for c in window:
        keys.setdefault(key_func(c.timestamp), []).append(c)
    # The last period in the window is "current"; the one before is "previous".
    ordered = list(keys.keys())
    if len(ordered) < 2:
        return None, None
    prev_key = ordered[-2]
    prev_candles = keys[prev_key]
    high = max(c.high for c in prev_candles)
    low = min(c.low for c in prev_candles)
    return high, low


def detect_liquidity(
    candles: List[Candle],
    index: int | None = None,
    timeframe: str = "15m",
    include_external: bool = True,
) -> List[LiquidityLevel]:
    """Detect all liquidity levels available up to ``index``."""
    n = len(candles)
    if index is None:
        index = n - 1
    index = min(index, n - 1)
    if index < 2:
        return []

    levels: List[LiquidityLevel] = []
    created = candles[index].timestamp

    # ---- External: previous day / week high & low ---------------------- #
    if include_external:
        prev_day_high, prev_day_low = _group_extremes(candles, index, _day_key, "day")
        if prev_day_high is not None:
            levels.append(
                LiquidityLevel(
                    price=prev_day_high,
                    level_type="BUY-SIDE",
                    liquidity_class="EXTERNAL",
                    score=3,
                    strength=1.0,
                    tests=1,
                    timeframe=timeframe,
                    created_at=created,
                )
            )
            levels.append(
                LiquidityLevel(
                    price=prev_day_low,
                    level_type="SELL-SIDE",
                    liquidity_class="EXTERNAL",
                    score=3,
                    strength=1.0,
                    tests=1,
                    timeframe=timeframe,
                    created_at=created,
                )
            )
        prev_week_high, prev_week_low = _group_extremes(candles, index, _week_key, "week")
        if prev_week_high is not None:
            levels.append(
                LiquidityLevel(
                    price=prev_week_high,
                    level_type="BUY-SIDE",
                    liquidity_class="EXTERNAL",
                    score=4,
                    strength=1.0,
                    tests=1,
                    timeframe=timeframe,
                    created_at=created,
                )
            )
            levels.append(
                LiquidityLevel(
                    price=prev_week_low,
                    level_type="SELL-SIDE",
                    liquidity_class="EXTERNAL",
                    score=4,
                    strength=1.0,
                    tests=1,
                    timeframe=timeframe,
                    created_at=created,
                )
            )

    # ---- Major swing highs / lows (external) --------------------------- #
    highs, lows = get_structural_swings(candles, index=index)
    for s in highs:
        levels.append(
            LiquidityLevel(
                price=s.price,
                level_type="BUY-SIDE",
                liquidity_class="EXTERNAL",
                score=3,
                strength=1.0,
                tests=1,
                timeframe=timeframe,
                created_at=created,
                candle_index=s.index,
            )
        )
    for s in lows:
        levels.append(
            LiquidityLevel(
                price=s.price,
                level_type="SELL-SIDE",
                liquidity_class="EXTERNAL",
                score=3,
                strength=1.0,
                tests=1,
                timeframe=timeframe,
                created_at=created,
                candle_index=s.index,
            )
        )

    # ---- Internal: equal highs / lows ---------------------------------- #
    levels.extend(_equal_levels(highs, "BUY-SIDE", "INTERNAL", timeframe, created, True))
    levels.extend(_equal_levels(lows, "SELL-SIDE", "INTERNAL", timeframe, created, False))

    # ---- Merge duplicate prices to accumulate tests -------------------- #
    merged = _merge_levels(levels)
    return merged


def _equal_levels(swings, side, cls, timeframe, created, is_high):
    out: List[LiquidityLevel] = []
    seen: List[LiquidityLevel] = []
    for s in swings:
        matched = None
        for lv in seen:
            denom = lv.price or 1.0
            if abs(s.price - lv.price) / denom <= EQUAL_TOLERANCE:
                matched = lv
                break
        if matched is not None:
            matched.score += 2
            matched.tests += 1
            matched.strength = min(1.0, matched.strength + 0.2)
        else:
            lv = LiquidityLevel(
                price=s.price,
                level_type=side,
                liquidity_class=cls,
                score=2,
                strength=0.5,
                tests=1,
                timeframe=timeframe,
                created_at=created,
                candle_index=s.index,
            )
            seen.append(lv)
            out.append(lv)
    return out


def _merge_levels(levels: List[LiquidityLevel]) -> List[LiquidityLevel]:
    """Merge levels at (almost) identical prices, summing scores/tests."""
    merged: List[LiquidityLevel] = []
    for lv in levels:
        found = None
        for m in merged:
            denom = m.price or 1.0
            if abs(lv.price - m.price) / denom <= EQUAL_TOLERANCE:
                found = m
                break
        if found is not None:
            found.score += lv.score
            found.tests += lv.tests - 1
            found.strength = min(1.0, found.strength + 0.1)
        else:
            merged.append(lv)
    return merged


def best_liquidity(levels: List[LiquidityLevel], side: Optional[str] = None) -> Optional[LiquidityLevel]:
    """Return the highest-scoring (tradable) liquidity level, optionally filtered by side."""
    candidates = [l for l in levels if l.score >= 4]
    if side:
        candidates = [l for l in candidates if l.level_type == side]
    if not candidates:
        return None
    return max(candidates, key=lambda x: (x.score, x.strength))
