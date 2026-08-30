from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from backtest.trend_pullback import V2BacktestResult, V2Trade
from strategy.trend_momentum_pullback import Direction


@dataclass(frozen=True)
class SidePerformance:
    trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    total_pnl: float = 0.0
    average_r: float = 0.0


@dataclass(frozen=True)
class PerformanceV2:
    total_trades: int
    wins: int
    losses: int
    win_rate_pct: float
    profit_factor: float
    total_pnl: float
    total_return_pct: float
    average_r: float
    expectancy_r: float
    max_drawdown_pct: float
    max_consecutive_losses: int
    max_consecutive_wins: int
    long: SidePerformance
    short: SidePerformance


def _pf(trades: Sequence[V2Trade]) -> float:
    gross_profit = sum(t.realized_pnl for t in trades if t.realized_pnl > 0)
    gross_loss = abs(sum(t.realized_pnl for t in trades if t.realized_pnl < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _side(trades: Sequence[V2Trade], direction: Direction) -> SidePerformance:
    subset = [t for t in trades if t.direction == direction]
    wins = sum(t.result == "WIN" for t in subset)
    losses = sum(t.result == "LOSS" for t in subset)
    return SidePerformance(
        trades=len(subset),
        wins=wins,
        losses=losses,
        win_rate_pct=(wins / len(subset) * 100.0) if subset else 0.0,
        profit_factor=_pf(subset),
        total_pnl=sum(t.realized_pnl for t in subset),
        average_r=(sum(t.r_multiple for t in subset) / len(subset)) if subset else 0.0,
    )


def _max_streak(trades: Sequence[V2Trade], result: str) -> int:
    best = cur = 0
    for trade in trades:
        if trade.result == result:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def compute_performance_v2(result: V2BacktestResult) -> PerformanceV2:
    trades = sorted(result.trades, key=lambda t: (t.exit_timestamp or t.entry_timestamp, t.trade_id))
    total = len(trades)
    wins = sum(t.result == "WIN" for t in trades)
    losses = sum(t.result == "LOSS" for t in trades)
    r_values = [t.r_multiple for t in trades]
    initial = result.initial_equity
    total_pnl = sum(t.realized_pnl for t in trades)
    avg_r = sum(r_values) / len(r_values) if r_values else 0.0

    equity = initial
    peak = initial
    max_dd = 0.0
    for _, mark in result.equity_curve:
        equity = mark
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100.0)
    # Include final realized equity when an equity curve is sparse.
    peak = max(peak, initial)
    if peak > 0:
        max_dd = max(max_dd, (peak - result.final_equity) / peak * 100.0)

    return PerformanceV2(
        total_trades=total,
        wins=wins,
        losses=losses,
        win_rate_pct=(wins / total * 100.0) if total else 0.0,
        profit_factor=_pf(trades),
        total_pnl=total_pnl,
        total_return_pct=(total_pnl / initial * 100.0) if initial else 0.0,
        average_r=avg_r,
        expectancy_r=avg_r,
        max_drawdown_pct=max_dd,
        max_consecutive_losses=_max_streak(trades, "LOSS"),
        max_consecutive_wins=_max_streak(trades, "WIN"),
        long=_side(trades, Direction.LONG),
        short=_side(trades, Direction.SHORT),
    )
