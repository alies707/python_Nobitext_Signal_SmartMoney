"""Time-series validation helpers for Trend/Momentum/Pullback Strategy V2."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from config import Config
from models.candle import Candle
from strategy.trend_momentum_pullback import StrategyConfig, TrendMomentumPullbackStrategy
from backtest.performance_v2 import PerformanceV2, compute_performance_v2
from backtest.trend_pullback import TrendPullbackBacktester, V2BacktestResult


@dataclass(frozen=True)
class ValidationSplit:
    cutoff_timestamp: int
    in_sample: tuple[Candle, ...]
    out_of_sample: tuple[Candle, ...]
    in_sample_htf: tuple[Candle, ...]
    out_of_sample_htf: tuple[Candle, ...]


@dataclass(frozen=True)
class ValidationResult:
    split: ValidationSplit
    in_sample_result: V2BacktestResult
    out_of_sample_result: V2BacktestResult
    in_sample_performance: PerformanceV2
    out_of_sample_performance: PerformanceV2

    @property
    def oos_passes_preliminary(self) -> bool:
        p = self.out_of_sample_performance
        return p.total_trades >= 10 and p.total_pnl > 0 and p.profit_factor > 1.0


def time_split(
    entry_candles: Sequence[Candle],
    htf_candles: Sequence[Candle],
    oos_fraction: float = 0.30,
) -> ValidationSplit:
    if not 0.10 <= oos_fraction <= 0.50:
        raise ValueError("oos_fraction must be between 0.10 and 0.50")
    if len(entry_candles) < 10 or len(htf_candles) < 2:
        raise ValueError("insufficient candles for validation split")
    if any(entry_candles[i].timestamp >= entry_candles[i + 1].timestamp for i in range(len(entry_candles) - 1)):
        raise ValueError("entry candles must be strictly increasing")
    if any(htf_candles[i].timestamp >= htf_candles[i + 1].timestamp for i in range(len(htf_candles) - 1)):
        raise ValueError("HTF candles must be strictly increasing")

    split_index = int(len(entry_candles) * (1.0 - oos_fraction))
    split_index = min(max(split_index, 1), len(entry_candles) - 1)
    cutoff = entry_candles[split_index].timestamp

    is_entry = tuple(entry_candles[:split_index])
    oos_entry = tuple(entry_candles[split_index:])
    is_htf = tuple(h for h in htf_candles if h.timestamp < cutoff)
    oos_htf = tuple(h for h in htf_candles if h.timestamp >= cutoff)

    if not is_htf or not oos_htf:
        raise ValueError("time split does not contain HTF data on both sides")
    if is_entry[-1].timestamp >= oos_entry[0].timestamp:
        raise AssertionError("in-sample and out-of-sample overlap")
    if is_htf[-1].timestamp >= oos_htf[0].timestamp:
        raise AssertionError("HTF in-sample and out-of-sample overlap")

    return ValidationSplit(cutoff, is_entry, oos_entry, is_htf, oos_htf)


def validate_v2(
    entry_candles: Sequence[Candle],
    htf_candles: Sequence[Candle],
    config: Config,
    strategy_config: StrategyConfig | None = None,
    oos_fraction: float = 0.30,
) -> ValidationResult:
    split = time_split(entry_candles, htf_candles, oos_fraction=oos_fraction)
    # Same frozen strategy configuration is used on both sides. No fitting/tuning
    # occurs in this stage, so OOS remains genuinely unseen.
    strategy_cfg = strategy_config or StrategyConfig()
    is_strategy = TrendMomentumPullbackStrategy(strategy_cfg)
    oos_strategy = TrendMomentumPullbackStrategy(strategy_cfg)

    is_result = TrendPullbackBacktester(is_strategy, config).run(
        split.in_sample,
        split.in_sample_htf,
        "VALIDATION",
        initial_equity=config.initial_capital,
    )
    oos_result = TrendPullbackBacktester(oos_strategy, config).run(
        split.out_of_sample,
        split.out_of_sample_htf,
        "VALIDATION",
        initial_equity=config.initial_capital,
    )
    return ValidationResult(
        split=split,
        in_sample_result=is_result,
        out_of_sample_result=oos_result,
        in_sample_performance=compute_performance_v2(is_result),
        out_of_sample_performance=compute_performance_v2(oos_result),
    )
