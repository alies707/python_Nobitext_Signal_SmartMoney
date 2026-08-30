"""Robust time-series validation for Trend/Momentum/Pullback Strategy V2."""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Sequence

from backtest.performance_v2 import PerformanceV2, compute_performance_v2
from backtest.trend_pullback import TrendPullbackBacktester
from config import Config
from models.candle import Candle
from strategy.trend_momentum_pullback import StrategyConfig, TrendMomentumPullbackStrategy


@dataclass(frozen=True)
class ValidationSplit:
    cutoff_timestamp: int
    in_sample: tuple[Candle, ...]
    out_of_sample: tuple[Candle, ...]
    in_sample_htf: tuple[Candle, ...]
    out_of_sample_htf: tuple[Candle, ...]


@dataclass(frozen=True)
class ValidationFold:
    fold_id: int
    split: ValidationSplit
    in_sample_performance: PerformanceV2
    out_of_sample_performance: PerformanceV2

    @property
    def oos_pf_retention_pct(self) -> float:
        is_pf = self.in_sample_performance.profit_factor
        oos_pf = self.out_of_sample_performance.profit_factor
        if is_pf in (0.0, float("inf")):
            return 0.0
        return oos_pf / is_pf * 100.0


@dataclass(frozen=True)
class RobustValidation:
    folds: tuple[ValidationFold, ...]
    min_trades_per_fold: int = 20

    @property
    def total_oos_trades(self) -> int:
        return sum(f.out_of_sample_performance.total_trades for f in self.folds)

    @property
    def positive_oos_folds(self) -> int:
        return sum(
            f.out_of_sample_performance.total_pnl > 0
            and f.out_of_sample_performance.profit_factor > 1.0
            for f in self.folds
        )

    @property
    def folds_with_sufficient_sample(self) -> int:
        return sum(
            f.out_of_sample_performance.total_trades >= self.min_trades_per_fold
            for f in self.folds
        )

    @property
    def median_oos_profit_factor(self) -> float:
        values = [f.out_of_sample_performance.profit_factor for f in self.folds]
        finite = [v for v in values if v != float("inf")]
        return median(finite) if finite else float("inf")

    @property
    def median_pf_retention_pct(self) -> float:
        values = [f.oos_pf_retention_pct for f in self.folds]
        return median(values) if values else 0.0

    @property
    def oos_initial_equity(self) -> float:
        return self.folds[0].out_of_sample_performance.initial_capital if self.folds else 0.0

    @property
    def oos_final_equity(self) -> float:
        if not self.folds:
            return 0.0
        last = self.folds[-1].out_of_sample_performance
        return last.initial_capital + last.total_pnl

    @property
    def aggregate_oos_pnl(self) -> float:
        return self.oos_final_equity - self.oos_initial_equity

    @property
    def aggregate_oos_return_pct(self) -> float:
        start = self.oos_initial_equity
        return ((self.oos_final_equity - start) / start * 100.0) if start else 0.0

    @property
    def worst_oos_profit_factor(self) -> float:
        return min(f.out_of_sample_performance.profit_factor for f in self.folds)

    @property
    def passes_preliminary_robustness(self) -> bool:
        return (
            len(self.folds) >= 3
            and self.total_oos_trades >= self.min_trades_per_fold * len(self.folds)
            and self.folds_with_sufficient_sample == len(self.folds)
            and self.positive_oos_folds == len(self.folds)
            and self.aggregate_oos_pnl > 0
            and self.median_oos_profit_factor > 1.05
            and self.median_pf_retention_pct >= 50.0
        )


def _validate_series(entry_candles: Sequence[Candle], htf_candles: Sequence[Candle]) -> None:
    if len(entry_candles) < 20 or len(htf_candles) < 2:
        raise ValueError("insufficient candles for validation")
    if any(entry_candles[i].timestamp >= entry_candles[i + 1].timestamp for i in range(len(entry_candles) - 1)):
        raise ValueError("entry candles must be strictly increasing")
    if any(htf_candles[i].timestamp >= htf_candles[i + 1].timestamp for i in range(len(htf_candles) - 1)):
        raise ValueError("HTF candles must be strictly increasing")


def time_split(entry_candles: Sequence[Candle], htf_candles: Sequence[Candle], oos_fraction: float = 0.30) -> ValidationSplit:
    if not 0.10 <= oos_fraction <= 0.50:
        raise ValueError("oos_fraction must be between 0.10 and 0.50")
    _validate_series(entry_candles, htf_candles)
    split_index = min(max(int(len(entry_candles) * (1.0 - oos_fraction)), 1), len(entry_candles) - 1)
    cutoff = entry_candles[split_index].timestamp
    is_entry = tuple(entry_candles[:split_index])
    oos_entry = tuple(entry_candles[split_index:])
    is_htf = tuple(h for h in htf_candles if h.timestamp < cutoff)
    oos_htf = tuple(htf_candles)
    if not is_htf:
        raise ValueError("time split does not contain sufficient HTF history")
    if is_entry[-1].timestamp >= oos_entry[0].timestamp:
        raise AssertionError("in-sample and out-of-sample entry data overlap")
    return ValidationSplit(cutoff, is_entry, oos_entry, is_htf, oos_htf)


def expanding_walk_forward_splits(entry_candles: Sequence[Candle], htf_candles: Sequence[Candle], n_folds: int = 3, oos_fraction: float = 0.20) -> tuple[ValidationSplit, ...]:
    if n_folds < 2:
        raise ValueError("n_folds must be at least 2")
    if not 0.10 <= oos_fraction <= 0.30:
        raise ValueError("oos_fraction must be between 0.10 and 0.30")
    _validate_series(entry_candles, htf_candles)
    fold_size = int(len(entry_candles) * oos_fraction)
    if fold_size < 1:
        raise ValueError("OOS fold contains no entry candles")
    train_fraction = 1.0 - n_folds * oos_fraction
    if train_fraction < 0.20:
        raise ValueError("not enough history for requested fold layout")
    first_train = int(len(entry_candles) * train_fraction)
    splits: list[ValidationSplit] = []
    for fold_id in range(n_folds):
        train_end = first_train + fold_id * fold_size
        test_end = train_end + fold_size
        if test_end > len(entry_candles):
            break
        is_entry = tuple(entry_candles[:train_end])
        oos_entry = tuple(entry_candles[train_end:test_end])
        cutoff = oos_entry[0].timestamp
        is_htf = tuple(h for h in htf_candles if h.timestamp < cutoff)
        if not is_entry or not oos_entry or not is_htf:
            continue
        splits.append(ValidationSplit(cutoff, is_entry, oos_entry, is_htf, tuple(htf_candles)))
    if len(splits) != n_folds:
        raise ValueError("could not construct the requested number of OOS folds")
    return tuple(splits)


def validate_v2(entry_candles: Sequence[Candle], htf_candles: Sequence[Candle], config: Config, strategy_config: StrategyConfig | None = None, oos_fraction: float = 0.30) -> ValidationFold:
    split = time_split(entry_candles, htf_candles, oos_fraction=oos_fraction)
    strategy_cfg = strategy_config or StrategyConfig()
    is_result = TrendPullbackBacktester(TrendMomentumPullbackStrategy(strategy_cfg), config).run(split.in_sample, split.in_sample_htf, "VALIDATION", initial_equity=config.initial_capital)
    oos_result = TrendPullbackBacktester(TrendMomentumPullbackStrategy(strategy_cfg), config).run(split.out_of_sample, split.out_of_sample_htf, "VALIDATION", initial_equity=config.initial_capital)
    return ValidationFold(1, split, compute_performance_v2(is_result), compute_performance_v2(oos_result))


def robust_validate_v2(entry_candles: Sequence[Candle], htf_candles: Sequence[Candle], config: Config, strategy_config: StrategyConfig | None = None, n_folds: int = 3, oos_fraction: float = 0.20, min_trades_per_fold: int = 20) -> RobustValidation:
    if min_trades_per_fold < 1:
        raise ValueError("min_trades_per_fold must be positive")
    splits = expanding_walk_forward_splits(entry_candles, htf_candles, n_folds, oos_fraction)
    strategy_cfg = strategy_config or StrategyConfig()
    folds: list[ValidationFold] = []
    oos_equity = config.initial_capital
    for fold_id, split in enumerate(splits, start=1):
        is_result = TrendPullbackBacktester(TrendMomentumPullbackStrategy(strategy_cfg), config).run(split.in_sample, split.in_sample_htf, "VALIDATION", initial_equity=config.initial_capital)
        oos_result = TrendPullbackBacktester(TrendMomentumPullbackStrategy(strategy_cfg), config).run(split.out_of_sample, split.out_of_sample_htf, "VALIDATION", initial_equity=oos_equity)
        oos_equity = oos_result.final_equity
        folds.append(ValidationFold(fold_id, split, compute_performance_v2(is_result), compute_performance_v2(oos_result)))
    return RobustValidation(tuple(folds), min_trades_per_fold=min_trades_per_fold)
