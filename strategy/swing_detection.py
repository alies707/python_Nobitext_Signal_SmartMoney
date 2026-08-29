"""Deterministic swing-point detection.

A swing high/low is confirmed only once enough subsequent candles exist to
satisfy the definition. This makes the detector safe to use in backtests:
callers pass the current processing index and only already-confirmed swings
are returned, so no future candle is ever used for a decision made at ``index``.
"""
from __future__ import annotations

from typing import List, Tuple

from models.candle import Candle
from models.setup import SwingPoint


def detect_swings(
    candles: List[Candle],
    left: int = 2,
    right: int = 2,
    index: int | None = None,
) -> List[SwingPoint]:
    """Return confirmed swing points up to (and including) ``index``.

    A swing at position ``i`` is only considered confirmed if both the left and
    right comparison windows are fully available within ``[0, index]``.
    """
    n = len(candles)
    if index is None:
        index = n - 1
    index = min(index, n - 1)
    if index < 0:
        return []

    swings: List[SwingPoint] = []
    last_high: SwingPoint | None = None
    last_low: SwingPoint | None = None

    for i in range(left, index - right + 1):
        c = candles[i]
        is_high = True
        is_low = True
        for k in range(1, left + 1):
            if candles[i - k].high >= c.high:
                is_high = False
            if candles[i - k].low <= c.low:
                is_low = False
        for k in range(1, right + 1):
            if candles[i + k].high >= c.high:
                is_high = False
            if candles[i + k].low <= c.low:
                is_low = False

        if is_high:
            sp = SwingPoint(index=i, price=c.high, kind="HIGH", timestamp=c.timestamp)
            swings.append(sp)
            last_high = sp
        elif is_low:
            sp = SwingPoint(index=i, price=c.low, kind="LOW", timestamp=c.timestamp)
            swings.append(sp)
            last_low = sp

    return swings


def get_structural_swings(
    candles: List[Candle], index: int | None = None, left: int = 2, right: int = 2
) -> Tuple[List[SwingPoint], List[SwingPoint]]:
    """Split confirmed swings into highs and lows for convenience."""
    swings = detect_swings(candles, left=left, right=right, index=index)
    highs = [s for s in swings if s.kind == "HIGH"]
    lows = [s for s in swings if s.kind == "LOW"]
    return highs, lows
