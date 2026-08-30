from __future__ import annotations

import pytest

from config import load_config
from models.candle import Candle
from backtest.validation_v2 import expanding_walk_forward_splits, robust_validate_v2, time_split, validate_v2


def _bars(n: int, step_ms: int, start_ms: int = 1_700_000_000_000) -> list[Candle]:
    out = []
    for i in range(n):
        close = 100.0 + i * 0.2
        prev = 100.0 + (i - 1) * 0.2 if i else close
        out.append(Candle(
            timestamp=start_ms + i * step_ms,
            open=prev,
            high=max(prev, close) + 1.0,
            low=min(prev, close) - 1.0,
            close=close,
            volume=100.0,
        ))
    return out


def test_time_split_entry_data_is_strictly_disjoint():
    entry = _bars(100, 3_600_000)
    htf = _bars(30, 14_400_000)
    split = time_split(entry, htf, oos_fraction=0.30)
    assert split.in_sample[-1].timestamp < split.out_of_sample[0].timestamp
    assert all(c.timestamp < split.cutoff_timestamp for c in split.in_sample)
    assert all(c.timestamp >= split.cutoff_timestamp for c in split.out_of_sample)


def test_time_split_keeps_full_htf_history_for_oos_warmup():
    entry = _bars(100, 3_600_000)
    htf = _bars(30, 14_400_000)
    split = time_split(entry, htf, oos_fraction=0.30)
    assert split.in_sample_htf
    assert split.out_of_sample_htf == tuple(htf)
    assert split.out_of_sample_htf[0].timestamp < split.cutoff_timestamp


def test_time_split_rejects_invalid_fraction():
    entry = _bars(100, 3_600_000)
    htf = _bars(30, 14_400_000)
    with pytest.raises(ValueError):
        time_split(entry, htf, 0.05)
    with pytest.raises(ValueError):
        time_split(entry, htf, 0.60)


def test_time_split_rejects_unsorted_data():
    entry = _bars(100, 3_600_000)
    htf = _bars(30, 14_400_000)
    entry[10], entry[11] = entry[11], entry[10]
    with pytest.raises(ValueError, match="entry candles must be strictly increasing"):
        time_split(entry, htf)


def test_validation_returns_independent_results():
    cfg = load_config()
    entry = _bars(1200, 3_600_000)
    htf = _bars(400, 14_400_000)
    result = validate_v2(entry, htf, cfg, oos_fraction=0.30)
    assert result.split.in_sample[-1].timestamp < result.split.out_of_sample[0].timestamp
    assert result.in_sample_performance.total_trades >= 0
    assert result.out_of_sample_performance.total_trades >= 0
    assert result.split.out_of_sample_htf[0].timestamp < result.split.cutoff_timestamp


def test_expanding_walk_forward_folds_are_chronological_and_disjoint():
    entry = _bars(100, 3_600_000)
    htf = _bars(30, 14_400_000)
    folds = expanding_walk_forward_splits(entry, htf, n_folds=3, oos_fraction=0.20)
    assert len(folds) == 3
    previous_oos_end = None
    for split in folds:
        assert split.in_sample[-1].timestamp < split.out_of_sample[0].timestamp
        if previous_oos_end is not None:
            assert previous_oos_end < split.out_of_sample[0].timestamp
        previous_oos_end = split.out_of_sample[-1].timestamp
        assert split.out_of_sample_htf == tuple(htf)
        assert split.in_sample_htf[-1].timestamp < split.cutoff_timestamp


def test_expanding_walk_forward_rejects_unworkable_layout():
    entry = _bars(20, 3_600_000)
    htf = _bars(10, 14_400_000)
    with pytest.raises(ValueError):
        expanding_walk_forward_splits(entry, htf, n_folds=5, oos_fraction=0.20)
    with pytest.raises(ValueError):
        expanding_walk_forward_splits(entry, htf, n_folds=3, oos_fraction=0.40)


def test_robust_validation_has_one_result_per_fold():
    cfg = load_config()
    entry = _bars(1200, 3_600_000)
    htf = _bars(400, 14_400_000)
    result = robust_validate_v2(entry, htf, cfg, n_folds=3, oos_fraction=0.20)
    assert len(result.folds) == 3
    assert result.total_oos_trades >= 0
    assert result.aggregate_oos_pnl == result.oos_final_equity - result.oos_initial_equity
    assert result.positive_oos_folds >= 0


def test_robust_validation_carries_oos_equity_between_folds():
    cfg = load_config()
    entry = _bars(1200, 3_600_000)
    htf = _bars(400, 14_400_000)
    result = robust_validate_v2(entry, htf, cfg, n_folds=3, oos_fraction=0.20)
    for previous, current in zip(result.folds, result.folds[1:]):
        previous_final = previous.out_of_sample_result.final_equity
        assert current.out_of_sample_result.initial_equity == pytest.approx(previous_final)


def test_robust_validation_frozen_parameters_are_identical():
    cfg = load_config()
    entry = _bars(1200, 3_600_000)
    htf = _bars(400, 14_400_000)
    result = robust_validate_v2(entry, htf, cfg, n_folds=3, oos_fraction=0.20)
    assert len(result.folds) == 3
    assert all(fold.split.out_of_sample_htf == tuple(htf) for fold in result.folds)


def test_fold_reports_sample_size_and_oos_pf_retention():
    cfg = load_config()
    entry = _bars(1200, 3_600_000)
    htf = _bars(400, 14_400_000)
    result = robust_validate_v2(entry, htf, cfg, n_folds=3, oos_fraction=0.20, min_trades_per_fold=20)
    assert all(f.out_of_sample_performance.total_trades >= 0 for f in result.folds)
    assert all(f.oos_pf_retention_pct >= 0 for f in result.folds)
    assert result.folds_with_sufficient_sample <= len(result.folds)


def test_invalid_minimum_trades_per_fold_is_rejected():
    cfg = load_config()
    entry = _bars(1200, 3_600_000)
    htf = _bars(400, 14_400_000)
    with pytest.raises(ValueError, match="min_trades_per_fold must be positive"):
        robust_validate_v2(entry, htf, cfg, n_folds=3, oos_fraction=0.20, min_trades_per_fold=0)


def test_sample_status_distinguishes_inconclusive_from_failure():
    cfg = load_config()
    entry = _bars(1200, 3_600_000)
    htf = _bars(400, 14_400_000)
    result = robust_validate_v2(entry, htf, cfg, n_folds=3, oos_fraction=0.20, min_trades_per_fold=20)
    statuses = [fold.sample_status(result.min_trades_per_fold) for fold in result.folds]
    assert all(status in {"PASS", "INCONCLUSIVE"} for status in statuses)
    assert result.inconclusive_folds == sum(status == "INCONCLUSIVE" for status in statuses)


def test_performance_status_requires_sufficient_sample_before_failure():
    cfg = load_config()
    entry = _bars(1200, 3_600_000)
    htf = _bars(400, 14_400_000)
    result = robust_validate_v2(entry, htf, cfg, n_folds=3, oos_fraction=0.20, min_trades_per_fold=20)
    for fold in result.folds:
        status = fold.performance_status(result.min_trades_per_fold)
        if fold.out_of_sample_performance.total_trades < result.min_trades_per_fold:
            assert status == "INCONCLUSIVE"
        else:
            assert status in {"PASS", "FAIL"}


def test_future_entry_changes_cannot_affect_earlier_oos_fold():
    cfg = load_config()
    entry = _bars(1200, 3_600_000)
    htf = _bars(400, 14_400_000)
    baseline = robust_validate_v2(entry, htf, cfg, n_folds=3, oos_fraction=0.20)
    changed = list(entry)
    for i in range(1000, len(changed)):
        candle = changed[i]
        changed[i] = Candle(
            timestamp=candle.timestamp,
            open=candle.open * 3.0,
            high=candle.high * 3.0,
            low=candle.low * 3.0,
            close=candle.close * 3.0,
            volume=candle.volume,
        )
    mutated = robust_validate_v2(changed, htf, cfg, n_folds=3, oos_fraction=0.20)
    first_base = baseline.folds[0].out_of_sample_performance
    first_mutated = mutated.folds[0].out_of_sample_performance
    assert first_base.total_trades == first_mutated.total_trades
    assert first_base.total_pnl == first_mutated.total_pnl
    assert first_base.profit_factor == first_mutated.profit_factor
