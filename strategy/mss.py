"""Market Structure Shift (MSS) detection."""
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
    direction: Optional[str] = None
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
    """Detect MSS from sweep + displacement + internal structure break.

    The structure break uses a tighter 1/1 swing definition than the external
    market-structure detector. This prevents a large historical swing from being
    mislabeled as the internal MSS trigger.
    """
    if not candles:
        return MssResult(False)
    n = len(candles)
    if index is None:
        index = n - 1
    index = min(index, n - 1)
    if index < max(3, atr_period):
        return MssResult(False)

    disp = detect_displacement(
        candles, index=index, atr_period=atr_period, vol_period=vol_period
    )
    if not disp.confirmed or disp.direction is None:
        return MssResult(False)

    direction = disp.direction
    expected_sweep_side = "SELL-SIDE" if direction == "BULLISH" else "BUY-SIDE"
    sweep = detect_sweep_before(
        candles, index, levels or [], expected_direction=direction, max_gap=max_gap
    )
    if not sweep.confirmed or sweep.level is None or sweep.level.level_type != expected_sweep_side:
        return MssResult(False)

    # Internal structure uses a tighter swing model. The break must be against
    # the local swing immediately preceding the displacement leg.
    internal = analyze_structure(candles, index=index, left=1, right=1)
    structure_break = (
        direction == "BULLISH" and internal.bos_bullish
    ) or (
        direction == "BEARISH" and internal.bos_bearish
    )
    if not structure_break:
        return MssResult(False)

    return MssResult(
        confirmed=True,
        direction=direction,
        index=index,
        sweep_index=sweep.sweep_index,
        displacement_index=disp.index,
        swept_level=sweep.level,
    )
