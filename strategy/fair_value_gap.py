"""Fair Value Gap (FVG) detection and scoring.

A Fair Value Gap is a three-candle imbalance:

* Bullish FVG: candle[i-2].high < candle[i].low  -> gap between them
* Bearish FVG: candle[i-2].low  > candle[i].high -> gap between them

Scoring (per spec)::
    After MSS         +3
    Strong displacement +3
    Near Order Block   +2
    HTF alignment      +2
    Minimum valid FVG score: 7

A detected FVG records its boundaries, creation candle, timeframe, score, status
and whether it has been mitigated (price later traded back into the gap).
"""
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
    """Detect an FVG whose creation completes at candle ``i``."""
    if i < 2 or i >= len(candles):
        return None
    c1 = candles[i - 2]
    c3 = candles[i]
    if c1.high < c3.low:
        # Bullish gap: zone between c1.high (lower) and c3.low (upper).
        return FVG(
            fvg_type="BULLISH",
            lower=c1.high,
            upper=c3.low,
            creation_index=i,
            timeframe="",
        )
    if c1.low > c3.high:
        return FVG(
            fvg_type="BEARISH",
            lower=c3.high,
            upper=c1.low,
            creation_index=i,
            timeframe="",
        )
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
    """Return True if any candle after ``from_index`` trades into the gap."""
    for j in range(from_index, len(candles)):
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
) -> Optional[FVG]:
    """Find the best-scoring FVG near the MSS created in the setup direction.

    Searches within ``window`` candles after the MSS for an FVG matching the
    direction, scores it, and rejects mitigated or sub-threshold gaps.
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
        if fvg.score >= 7 and (best is None or fvg.score > best.score):
            best = fvg
    return best
