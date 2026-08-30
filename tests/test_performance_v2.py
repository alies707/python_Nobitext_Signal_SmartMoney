from __future__ import annotations

import math

from backtest.performance_v2 import compute_performance_v2
from backtest.trend_pullback import V2BacktestResult, V2Trade
from strategy.trend_momentum_pullback import Direction


def _trade(i, direction, pnl, r, entry_ts, exit_ts, result):
    return V2Trade(
        trade_id=i,
        symbol="TEST",
        direction=direction,
        signal_timestamp=entry_ts - 1,
        entry_timestamp=entry_ts,
        entry=100.0,
        stop_loss=95.0 if direction == Direction.LONG else 105.0,
        tp1=110.0 if direction == Direction.LONG else 90.0,
        tp2=115.0 if direction == Direction.LONG else 85.0,
        size=1.0,
        entry_fee=0.0,
        realized_pnl=pnl,
        remaining=0.0,
        exit_timestamp=exit_ts,
        exit_price=110.0,
        result=result,
        exit_reason="TP1" if result == "WIN" else "STOP",
    )


def test_performance_v2_calculates_core_metrics():
    trades = [
        _trade(1, Direction.LONG, 10.0, 2.0, 1, 2, "WIN"),
        _trade(2, Direction.LONG, -5.0, -1.0, 3, 4, "LOSS"),
        _trade(3, Direction.SHORT, 20.0, 4.0, 5, 6, "WIN"),
    ]
    result = V2BacktestResult(
        initial_equity=100.0,
        final_equity=125.0,
        trades=trades,
        equity_curve=[(1, 100.0), (2, 110.0), (4, 104.0), (6, 125.0)],
    )
    perf = compute_performance_v2(result)
    assert perf.total_trades == 3
    assert perf.wins == 2
    assert perf.losses == 1
    assert math.isclose(perf.win_rate_pct, 66.66666666666667, rel_tol=0.0, abs_tol=1e-12)
    assert perf.profit_factor == 6.0
    assert perf.total_pnl == 25.0
    assert perf.total_return_pct == 25.0
    assert math.isclose(perf.average_r, 5.0 / 3.0, rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(perf.expectancy_r, perf.average_r, rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(perf.max_drawdown_pct, 6.0 / 110.0 * 100.0, rel_tol=0.0, abs_tol=1e-12)
    assert perf.max_consecutive_wins == 1
    assert perf.max_consecutive_losses == 1
    assert perf.long.trades == 2
    assert perf.long.wins == 1
    assert perf.short.trades == 1
    assert perf.short.wins == 1


def test_performance_v2_handles_empty_result():
    result = V2BacktestResult(100.0, 100.0, [], [(1, 100.0)])
    perf = compute_performance_v2(result)
    assert perf.total_trades == 0
    assert perf.win_rate_pct == 0.0
    assert perf.total_pnl == 0.0
