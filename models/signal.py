"""Final signal model returned by the engine.

This dataclass is pure data with no strategy logic. It is the contract between
the Strategy Engine and any presentation layer (terminal, Flask, Telegram, ...).
The engine never knows how its output will be displayed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from models.setup import Direction, Bias


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class Signal:
    """Final, serializable signal emitted by the engine."""

    symbol: str
    direction: Direction
    timestamp: int
    timeframe: str
    htf_bias: Bias

    entry: Optional[float]
    entry_zone_high: Optional[float]
    entry_zone_low: Optional[float]
    stop_loss: Optional[float]
    tp1: Optional[float]
    tp2: Optional[float]
    tp3: Optional[float]
    risk_reward: float
    smart_money_score: int
    confidence: Confidence
    liquidity_target: bool
    setup_explanation: List[str]
    score_breakdown: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction.value,
            "timestamp": self.timestamp,
            "timeframe": self.timeframe,
            "htf_bias": self.htf_bias.value,
            "entry": self.entry,
            "entry_zone_high": self.entry_zone_high,
            "entry_zone_low": self.entry_zone_low,
            "stop_loss": self.stop_loss,
            "tp1": self.tp1,
            "tp2": self.tp2,
            "tp3": self.tp3,
            "risk_reward": self.risk_reward,
            "smart_money_score": self.smart_money_score,
            "confidence": self.confidence.value,
            "liquidity_target": self.liquidity_target,
            "setup_explanation": self.setup_explanation,
            "score_breakdown": self.score_breakdown,
        }
