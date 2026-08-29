"""Candle data model.

A single OHLCV candle. Timestamps are stored as integer epoch milliseconds to
remain deterministic and timezone-agnostic. The model is intentionally simple
and is the single source of truth shared by every layer of the engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Trend(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass(slots=True)
class Candle:
    """Immutable OHLCV candle."""

    timestamp: int  # epoch milliseconds
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def range(self) -> float:
        """Full high-low range of the candle."""
        return self.high - self.low

    @property
    def body(self) -> float:
        """Absolute body size regardless of direction."""
        return abs(self.close - self.open)

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Candle":
        return cls(
            timestamp=int(d["timestamp"]),
            open=float(d["open"]),
            high=float(d["high"]),
            low=float(d["low"]),
            close=float(d["close"]),
            volume=float(d.get("volume", 0.0)),
        )
