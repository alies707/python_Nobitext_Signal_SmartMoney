"""Displacement detection.

Displacement is the institutional "impulse" candle that confirms intent.

Bullish displacement
--------------------
* body size >= ATR * 0.6
* close occurs in the upper 25% of the candle range
* volume > average volume of the previous 20 candles

Bearish displacement reverses the conditions.

The function safely handles zero range, missing volume, missing ATR and
insufficient history by returning ``confirmed=False`` rather than emitting a
false signal.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from models.candle import Candle
from strategy.indicators import average_volume, compute_atr


@dataclass
class DisplacementResult:
    confirmed: bool
    direction: Optional[str] = None  # "BULLISH" / "BEARISH"
    index: Optional[int] = None
    body_ratio: float = 0.0
    atr: float = 0.0
    volume_ratio: float = 0.0


def detect_displacement(
    candles: List[Candle],
    index: int | None = None,
    atr_period: int = 14,
    vol_period: int = 20,
    atr_mult: float = 0.6,
) -> DisplacementResult:
    n = len(candles)
    if index is None:
        index = n - 1
    index = min(index, n - 1)

    empty = DisplacementResult(confirmed=False, index=index if 0 <= index < n else None)

    if index < 1:
        return empty
    # Require enough history for ATR and volume averages.
    if index < max(atr_period, vol_period):
        return empty

    candle = candles[index]
    rng = candle.range
    if rng <= 0:
        return empty

    atr = compute_atr(candles, period=atr_period, index=index)
    if atr <= 0:
        return empty

    body = candle.body
    body_ratio = body / rng
    required_body = atr * atr_mult
    if body < required_body:
        return DisplacementResult(confirmed=False, index=index, body_ratio=body_ratio, atr=atr)

    # Position of close within the range (0 = at low, 1 = at high).
    close_pos = (candle.close - candle.low) / rng

    vol = candle.volume
    avg_vol = average_volume(candles, period=vol_period, index=index)
    volume_ratio = (vol / avg_vol) if avg_vol > 0 else 0.0

    is_bull = candle.is_bullish
    is_bear = candle.is_bearish

    if is_bull and close_pos >= 0.75 and volume_ratio > 1.0:
        return DisplacementResult(
            confirmed=True, direction="BULLISH", index=index,
            body_ratio=body_ratio, atr=atr, volume_ratio=volume_ratio,
        )
    if is_bear and close_pos <= 0.25 and volume_ratio > 1.0:
        return DisplacementResult(
            confirmed=True, direction="BEARISH", index=index,
            body_ratio=body_ratio, atr=atr, volume_ratio=volume_ratio,
        )
    return DisplacementResult(
        confirmed=False, index=index, body_ratio=body_ratio, atr=atr, volume_ratio=volume_ratio
    )
