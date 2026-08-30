"""Regression tests for chronological multi-timeframe backtesting."""
from __future__ import annotations

from config import load_config
from data.candle_manager import CandleManager
from models.candle import Candle
from strategy.signal_engine import SignalEngine
from risk.risk_manager import RiskManager
from backtest.engine import BacktestEngine


def _series(count: int, step_ms: int):
    base = 1_700_000_000_000
    return [
        Candle(
            timestamp=base + i * step_ms,
            open=100.0 + i * 0.1,
            high=101.0 + i * 0.1,
            low=99.0 + i * 0.1,
            close=100.5 + i * 0.1,
            volume=1.0,
        )
        for i in range(count)
    ]


def test_manager_up_to_is_timestamp_safe_for_htf():
    mgr = CandleManager(symbol="TEST")
    mgr.set_candles("15m", _series(200, 15 * 60 * 1000))
    mgr.set_candles("4H", _series(20, 4 * 60 * 60 * 1000))
    mgr.set_candles("1D", _series(5, 24 * 60 * 60 * 1000))

    cfg = load_config()
    bt = BacktestEngine(cfg, SignalEngine(cfg), RiskManager(cfg, capital=cfg.initial_capital))
    view = bt._manager_up_to(mgr, 100, "15m")
    now = mgr.get("15m")[100].timestamp

    assert all(c.timestamp <= now for c in view.get("4H"))
    assert all(c.timestamp + 4 * 60 * 60 * 1000 <= now for c in view.get("4H"))
    assert all(c.timestamp + 24 * 60 * 60 * 1000 <= now for c in view.get("1D"))


def test_entry_timeframe_is_truncated_by_index():
    mgr = CandleManager(symbol="TEST")
    mgr.set_candles("15m", _series(20, 15 * 60 * 1000))
    mgr.set_candles("4H", _series(20, 4 * 60 * 60 * 1000))
    mgr.set_candles("1D", _series(5, 24 * 60 * 60 * 1000))

    cfg = load_config()
    bt = BacktestEngine(cfg, SignalEngine(cfg), RiskManager(cfg, capital=cfg.initial_capital))
    view = bt._manager_up_to(mgr, 7, "15m")
    assert len(view.get("15m")) == 8
    assert view.get("15m")[-1].timestamp == mgr.get("15m")[7].timestamp
