"""Fair Value Gap detection, lifecycle tracking and scoring."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from models.candle import Candle
from models.setup import FVG


@dataclass
class FvgContext:
    mss_confirmed: bool = False
    displacement_strong: bool = False
    near_order_block: bool = False
    htf_aligned: bool = False


def detect_fvg_at(candles: List[Candle], i: int) -> Optional[FVG]:
    if i < 2 or i >= len(candles):
        return None
    c1, c3 = candles[i - 2], candles[i]
    if c1.high < c3.low:
        return FVG("BULLISH", c3.low, c1.high, i, "")
    if c1.low > c3.high:
        return FVG("BEARISH", c1.low, c3.high, i, "")
    return None


def score_fvg(fvg: FVG, ctx: FvgContext) -> int:
    score = 0
    if ctx.mss_confirmed:
        score += 3
    if ctx.displacement_strong:
        score += 3
    if ctx.near_order_block:
        score += 2
    if ctx.htf_aligned:
        score += 2
    fvg.score = score
    fvg.status = "VALID" if score >= 7 else "OPEN"
    return score


def is_mitigated(fvg: FVG, candles: List[Candle], from_index: int) -> bool:
    """A gap is mitigated when later price trades back into its zone."""
    for j in range(max(0, from_index), len(candles)):
        c = candles[j]
        if c.low <= fvg.upper and c.high >= fvg.lower:
            return True
    return False


def find_relevant_fvg(
    candles: List[Candle],
    mss_index: int,
    direction: str,
    ctx: FvgContext,
    window: int = 6,
    timeframe: str = "",
    require_score: bool = False,
) -> Optional[FVG]:
    """Find the best unmitigated FVG in the setup direction.

    By default selection happens before final OB confluence is known. Callers
    that already have a complete context can set ``require_score=True``.
    """
    best: Optional[FVG] = None
    start = max(2, mss_index)
    end = min(len(candles), mss_index + window + 1)
    for i in range(start, end):
        fvg = detect_fvg_at(candles, i)
        if fvg is None:
            continue
        if direction == "BULLISH" and fvg.fvg_type != "BULLISH":
            continue
        if direction == "BEARISH" and fvg.fvg_type != "BEARISH":
            continue
        fvg.timeframe = timeframe
        score_fvg(fvg, ctx)
        fvg.mitigated = is_mitigated(fvg, candles, i + 1)
        if fvg.mitigated:
            fvg.status = "MITIGATED"
            continue
        if require_score and fvg.score < 7:
            continue
        if best is None or (fvg.score, -fvg.creation_index) > (best.score, -best.creation_index):
            best = fvg
    return best
