"""Smart Money Confidence Score.

Transparent, additive scoring model (maximum 24 points). A signal is only
generated when the total score >= 16 (configurable). The breakdown is exposed
so every point is auditable.

    HTF Bias          +2
    Liquidity         +3
    Sweep             +3
    Displacement      +2
    MSS               +3
    FVG               +2
    Order Block       +2
    Premium/Discount  +2
    Liquidity Target  +2
    --------------------
    TOTAL            24
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from models.signal import Confidence

MAX_SCORE = 24

_SCORE_MAP = [
    ("HTF Bias", 2),
    ("Liquidity", 3),
    ("Sweep", 3),
    ("Displacement", 2),
    ("MSS", 3),
    ("FVG", 2),
    ("Order Block", 2),
    ("Premium/Discount", 2),
    ("Liquidity Target", 2),
]


@dataclass
class ScoreBreakdown:
    points: Dict[str, int] = field(default_factory=dict)
    total: int = 0

    def to_dict(self) -> Dict[str, int]:
        return dict(self.points)


def score_setup(flags: Dict[str, bool]) -> ScoreBreakdown:
    """Compute the Smart Money score from a dict of boolean conditions."""
    breakdown = ScoreBreakdown()
    for name, value in _SCORE_MAP:
        earned = value if flags.get(name.replace("/", " "), False) else 0
        breakdown.points[name] = earned
    breakdown.total = sum(breakdown.points.values())
    return breakdown


def confidence_from_score(score: int) -> Confidence:
    if score >= 21:
        return Confidence.HIGH
    if score >= 18:
        return Confidence.MEDIUM
    if score >= 16:
        return Confidence.LOW
    return Confidence.LOW
