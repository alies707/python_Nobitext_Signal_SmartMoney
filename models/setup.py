"""Direction and setup/signal data models.

These dataclasses are pure data containers. They contain no strategy logic so
that they can be freely serialized, passed to a terminal formatter, a future
Flask API, a Telegram bot, etc. without modification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


class Bias(str, Enum):
    LONG_BIAS = "LONG_BIAS"
    SHORT_BIAS = "SHORT_BIAS"
    NO_BIAS = "NO_BIAS"


class ZoneType(str, Enum):
    PREMIUM = "PREMIUM"
    EQUILIBRIUM = "EQUILIBRIUM"
    DISCOUNT = "DISCOUNT"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class LiquidityLevel:
    """A detected liquidity level (external or internal)."""

    price: float
    level_type: str  # e.g. "BUY-SIDE", "SELL-SIDE", "EQUAL_HIGH" ...
    liquidity_class: str  # "EXTERNAL" or "INTERNAL"
    score: int
    strength: float
    tests: int
    timeframe: str
    created_at: int
    # Optional: the index in the candle series where it was detected
    candle_index: Optional[int] = None


@dataclass
class FVG:
    fvg_type: str  # "BULLISH" / "BEARISH"
    upper: float
    lower: float
    creation_index: int
    timeframe: str
    score: int = 0
    status: str = "OPEN"  # OPEN / MITIGATED / INVALID
    mitigated: bool = False

    @property
    def size(self) -> float:
        return self.upper - self.lower


@dataclass
class OrderBlock:
    ob_type: str  # "BULLISH" / "BEARISH"
    zone_high: float
    zone_low: float
    creation_index: int
    timeframe: str
    fresh: bool = True
    validated: bool = False


@dataclass
class SwingPoint:
    index: int
    price: float
    kind: str  # "HIGH" / "LOW"
    timestamp: int


@dataclass
class Setup:
    """A complete Smart Money setup derived from analysis.

    The setup aggregates every detected condition. It is the bridge between the
    strategy modules and the signal engine.
    """

    symbol: str
    direction: Direction = Direction.NONE
    bias: Bias = Bias.NO_BIAS
    htf_bias: Dict[str, str] = field(default_factory=dict)  # {timeframe: "BULLISH"}

    structure_bullish: bool = False
    bos_confirmed: bool = False
    mss_confirmed: bool = False
    mss_index: Optional[int] = None

    liquidity_levels: List[LiquidityLevel] = field(default_factory=list)
    best_liquidity: Optional[LiquidityLevel] = None
    sweep_confirmed: bool = False
    sweep_index: Optional[int] = None

    displacement_confirmed: bool = False
    displacement_index: Optional[int] = None

    fvg: Optional[FVG] = None
    order_block: Optional[OrderBlock] = None

    premium_discount_zone: Optional[ZoneType] = None
    equilibrium: Optional[float] = None

    entry: Optional[float] = None
    entry_zone_high: Optional[float] = None
    entry_zone_low: Optional[float] = None
    entry_reason: str = ""

    stop_loss: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None

    risk_reward: float = 0.0
    smart_money_score: int = 0
    score_breakdown: Dict[str, int] = field(default_factory=dict)

    liquidity_target: bool = False

    explanation: List[str] = field(default_factory=list)
    confirmed: bool = False
