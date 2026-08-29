"""Market Structure Shift (MSS) detection.

Per the specification, a true MSS requires the *combination* of:

* a liquidity sweep (sell-side for bullish, buy-side for bearish),
* a displacement impulse in the same direction,
* a break of the internal swing structure (BOS/MSS) in that direction.

All three must align at (or immediately around) the MSS candle. This prevents
labeling ordinary price wiggles as MSS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from models.candle import Candle
from models.setup import LiquidityLevel
from strategy.displacement import detect_displacement
from strategy.liquidity_sweep import detect_sweep_before
from strategy.market_structure import analyze_structure


@dataclass
class MssResult:
    confirmed: bool
    direction: Optional[str] = None  # "BULLISH" / "BEARISH"
    index: Optional[int] = None
    sweep_index: Optional[int] = None
    displacement_index: Optional[int] = None
    swept_level: Optional[LiquidityLevel] = None


def detect_mss(
    candles: List[Candle],
    index: int | None = None,
    levels: Optional[List[LiquidityLevel]] = None,
    atr_period: int = 14,
    vol_period: int = 20,
    max_gap: int = 8,
) -> MssResult:
    """Detect a fully-formed MSS ending at ``index``."""
    n = len(candles)
    if index is None:
        index = n - 1
    index = min(index, n - 1)
    if index < 1:
        return MssResult(confirmed=False)

    disp = detect_displacement(candles, index=index, atr_period=atr_period, vol_period=vol_period)
    if not disp.confirmed:
        return MssResult(confirmed=False)

    direction = disp.direction
    expected_sweep_side = "SELL-SIDE" if direction == "BULLISH" else "BUY-SIDE"
    sweep = detect_sweep_before(
        candles, index, levels or [], expected_direction=direction, max_gap=max_gap
    )
    if not sweep.confirmed:
        return MssResult(confirmed=False)

    structure = analyze_structure(candles, index=index)
    structure_break = (direction == "BULLISH" and structure.bos_bullish) or (
        direction == "BEARISH" and structure.bos_bearish
    )
    if not structure_break:
        return MssResult(confirmed=False)

    return MssResult(
        confirmed=True,
        direction=direction,
        index=index,
        sweep_index=sweep.sweep_index,
        displacement_index=disp.index,
        swept_level=sweep.level,
    )
