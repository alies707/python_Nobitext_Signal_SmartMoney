"""Shared technical helpers.

Only genuinely required indicators live here. Per the project specification,
classic indicators (RSI/MACD/EMA/SMA/...) must NOT replace the Smart Money
logic; ATR is the single indicator explicitly permitted (for displacement and
stop-loss sizing).
"""
from __future__ import annotations

from typing import List

from models.candle import Candle


def compute_atr(candles: List[Candle], period: int = 14, index: int | None = None) -> float:
    """Compute the Average True Range at ``index`` (default: last candle).

    The ATR is computed using only candles up to and including ``index`` so the
    result never depends on future data (no look-ahead bias).
    """
    if index is None:
        index = len(candles) - 1
    if index < 1:
        # Not enough history; fall back to the single-candle range.
        if 0 <= index < len(candles):
            return max(candles[index].range, 1e-12)
        return 0.0

    start = max(1, index - period + 1)
    tr_values: List[float] = []
    for i in range(start, index + 1):
        c = candles[i]
        prev_close = candles[i - 1].close
        tr = max(
            c.high - c.low,
            abs(c.high - prev_close),
            abs(c.low - prev_close),
        )
        tr_values.append(tr)
        if len(tr_values) >= period:
            break

    if not tr_values:
        return max(candles[index].range, 1e-12)
    return sum(tr_values) / len(tr_values)


def average_volume(candles: List[Candle], period: int = 20, index: int | None = None) -> float:
    """Average volume over the ``period`` candles ending at ``index``."""
    if index is None:
        index = len(candles) - 1
    if index < 0:
        return 0.0
    start = max(0, index - period + 1)
    window = candles[start : index + 1]
    if not window:
        return 0.0
    return sum(c.volume for c in window) / len(window)
