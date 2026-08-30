"""Auditable Smart Money setup scoring.

The score is a confluence score, not a probability of profit. MSS is treated as
structure confirmation and therefore receives less weight than its component
evidence (sweep/displacement), reducing double-counting.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from models.signal import Confidence

_SCORE_MAP = [
    ("HTF Bias", 2),
    ("Liquidity", 3),
    ("Sweep", 3),
    ("Displacement", 3),
    ("MSS", 1),
    ("FVG", 3),
    ("Order Block", 3),
    ("Premium/Discount", 2),
    ("Liquidity Target", 2),
]
MAX_SCORE = sum(weight for _, weight in _SCORE_MAP)


@dataclass
class ScoreBreakdown:
    points: Dict[str, int] = field(default_factory=dict)
    total: int = 0

    def to_dict(self) -> Dict[str, int]:
        return dict(self.points)


def score_setup(flags: Dict[str, bool]) -> ScoreBreakdown:
    """Compute a deterministic, auditable confluence score."""
    breakdown = ScoreBreakdown()
    for name, weight in _SCORE_MAP:
        breakdown.points[name] = weight if flags.get(name.replace("/", " "), False) else 0
    breakdown.total = sum(breakdown.points.values())
    return breakdown


def confidence_from_score(score: int) -> Confidence:
    if score >= 19:
        return Confidence.HIGH
    if score >= 16:
        return Confidence.MEDIUM
    return Confidence.LOW
