"""Central configuration for the Smart Money Trading Engine.

All configuration is loaded from environment variables (via a local .env file
when present). No secrets are hardcoded. The configuration object is intended
to be dependency-injected into the engine components so that the strategy logic
remains fully independent of any UI or framework.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

try:  # pragma: no cover - import path differs between run contexts
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*_a, **_k):  # type: ignore
        return False


load_dotenv()


def _env_str(key: str, default: str) -> str:
    val = os.getenv(key)
    return val if val is not None and val != "" else default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _env_list(key: str, default: Optional[List[str]]) -> List[str]:
    val = os.getenv(key)
    if not val:
        return list(default) if default else []
    return [item.strip() for item in val.split(",") if item.strip()]


@dataclass
class Config:
    """Runtime configuration container.

    The dataclass is deliberately flat and serializable so that the engine can
    be reconfigured, logged and unit tested without touching the environment.
    """

    # Exchange
    nobitex_api_key: str = field(default_factory=lambda: _env_str("NOBITEX_API_KEY", ""))
    nobitex_api_url: str = field(default_factory=lambda: _env_str("NOBITEX_API_URL", "https://apiv2.nobitex.ir"))

    # Engine
    default_timeframe: str = field(default_factory=lambda: _env_str("DEFAULT_TIMEFRAME", "15m"))
    scan_interval: int = field(default_factory=lambda: _env_int("SCAN_INTERVAL", 60))
    top_markets_count: int = 10
    watchlist: List[str] = field(
        default_factory=lambda: _env_list("WATCHLIST", [])
    )

    # Risk
    risk_per_trade: float = field(default_factory=lambda: _env_float("RISK_PER_TRADE", 0.005))
    max_daily_loss: float = field(default_factory=lambda: _env_float("MAX_DAILY_LOSS", 0.02))
    max_open_positions: int = field(default_factory=lambda: _env_int("MAX_OPEN_POSITIONS", 3))
    max_correlated_exposure: float = field(default_factory=lambda: _env_float("MAX_CORRELATED_EXPOSURE", 0.015))

    # Strategy thresholds
    min_smart_money_score: int = field(default_factory=lambda: _env_int("MIN_SMART_MONEY_SCORE", 16))
    min_risk_reward: float = field(default_factory=lambda: _env_float("MIN_RISK_REWARD", 2.0))
    atr_multiplier: float = field(default_factory=lambda: _env_float("ATR_MULTIPLIER", 0.2))

    # Backtest
    initial_capital: float = field(default_factory=lambda: _env_float("INITIAL_CAPITAL", 100_000_000))
    fee_rate: float = field(default_factory=lambda: _env_float("FEE_RATE", 0.0005))
    slippage: float = field(default_factory=lambda: _env_float("SLIPPAGE", 0.0002))

    # Supported timeframes (high -> low)
    htf_timeframes: List[str] = field(default_factory=lambda: ["1D", "4H"])
    supported_timeframes: List[str] = field(
        default_factory=lambda: ["1m", "5m", "15m", "1H", "4H", "1D"]
    )

    # Market ranking weights (must sum to 1.0 logically, but kept as given)
    rank_volume_weight: float = 0.40
    rank_liquidity_weight: float = 0.30
    rank_spread_weight: float = 0.20
    rank_activity_weight: float = 0.10

    def validate(self) -> List[str]:
        """Return a list of configuration problems (empty when valid)."""
        problems: List[str] = []
        if self.risk_per_trade <= 0 or self.risk_per_trade >= 1:
            problems.append("RISK_PER_TRADE must be between 0 and 1")
        if self.max_daily_loss <= 0 or self.max_daily_loss >= 1:
            problems.append("MAX_DAILY_LOSS must be between 0 and 1")
        if self.min_risk_reward < 1:
            problems.append("MIN_RISK_REWARD must be >= 1")
        if self.atr_multiplier <= 0:
            problems.append("ATR_MULTIPLIER must be > 0")
        if self.default_timeframe not in self.supported_timeframes:
            problems.append("DEFAULT_TIMEFRAME is not a supported timeframe")
        return problems


def load_config() -> Config:
    """Build a Config object from the current environment."""
    return Config()
