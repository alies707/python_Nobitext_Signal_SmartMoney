from __future__ import annotations

import pytest

from config import load_config
from models.candle import Candle
from backtest.validation_v2 import time_split, validate_v2


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
    assert result.in_sample_result.initial_equity == cfg.initial_capital
    assert result.out_of_sample_result.initial_equity == cfg.initial_capital
    assert result.in_sample_performance.total_trades >= 0
    assert result.out_of_sample_performance.total_trades >= 0
    assert result.split.out_of_sample_htf[0].timestamp < result.split.cutoff_timestamp
