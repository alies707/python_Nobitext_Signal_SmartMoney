"""Backtest performance analytics and trade journal persistence.

Computes the full set of required statistics from a list of :class:`Trade`
records and writes the journal to CSV and JSON (no database required).
"""
from __future__ import annotations

import csv
import json
import math
import os
from dataclasses import dataclass, field
from typing import List, Optional

from backtest.engine import Trade


@dataclass
class Performance:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    average_r: float = 0.0
    total_return_pct: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    long_trades: int = 0
    long_wins: int = 0
    short_trades: int = 0
    short_wins: int = 0
    total_pnl: float = 0.0
    initial_capital: float = 0.0


def _safe_div(a: float, b: float) -> float:
    return a / b if b != 0 else 0.0


def compute_performance(trades: List[Trade], initial_capital: float) -> Performance:
    perf = Performance(initial_capital=initial_capital)
    if not trades:
        return perf

    wins = [t for t in trades if t.result == "WIN"]
    losses = [t for t in trades if t.result == "LOSS"]
    perf.total_trades = len(trades)
    perf.winning_trades = len(wins)
    perf.losing_trades = len(losses)
    perf.win_rate = _safe_div(len(wins), len(trades)) * 100.0

    gross_profit = sum(t._realized_pnl for t in wins)
    gross_loss = abs(sum(t._realized_pnl for t in losses))
    perf.profit_factor = _safe_div(gross_profit, gross_loss)
    perf.total_pnl = sum(t._realized_pnl for t in trades)
    perf.total_return_pct = _safe_div(perf.total_pnl, initial_capital) * 100.0

    r_values = [t.r_multiple for t in trades]
    perf.average_r = sum(r_values) / len(r_values) if r_values else 0.0
    perf.average_win = _safe_div(gross_profit, len(wins)) if wins else 0.0
    perf.average_loss = -_safe_div(gross_loss, len(losses)) if losses else 0.0
    perf.largest_win = max((t._realized_pnl for t in wins), default=0.0)
    perf.largest_loss = min((t._realized_pnl for t in losses), default=0.0)

    # Consecutive streaks.
    cur_win = cur_loss = best_win = best_loss = 0
    for t in trades:
        if t.result == "WIN":
            cur_win += 1
            cur_loss = 0
            best_win = max(best_win, cur_win)
        elif t.result == "LOSS":
            cur_loss += 1
            cur_win = 0
            best_loss = max(best_loss, cur_loss)
    perf.consecutive_wins = best_win
    perf.consecutive_losses = best_loss

    # LONG / SHORT breakdown.
    perf.long_trades = sum(1 for t in trades if t.direction == "LONG")
    perf.long_wins = sum(1 for t in trades if t.direction == "LONG" and t.result == "WIN")
    perf.short_trades = sum(1 for t in trades if t.direction == "SHORT")
    perf.short_wins = sum(1 for t in trades if t.direction == "SHORT" and t.result == "WIN")

    # Sharpe ratio from R-multiple series (proxy for return series).
    mean_r = perf.average_r
    if len(r_values) > 1:
        var = sum((r - mean_r) ** 2 for r in r_values) / (len(r_values) - 1)
        std_r = math.sqrt(var)
        perf.sharpe_ratio = _safe_div(mean_r, std_r) * math.sqrt(252) if std_r > 0 else 0.0
    else:
        perf.sharpe_ratio = 0.0

    # Max drawdown from the equity curve.
    equity = initial_capital
    peak = initial_capital
    max_dd = 0.0
    for t in trades:
        equity += t._realized_pnl
        peak = max(peak, equity)
        dd = _safe_div(peak - equity, peak) * 100.0 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    perf.max_drawdown_pct = max_dd

    return perf


def _trade_row(t: Trade) -> dict:
    return {
        "trade_id": t.trade_id,
        "symbol": t.symbol,
        "direction": t.direction,
        "entry": t.entry,
        "stop": t.stop,
        "tp1": t.tp1,
        "tp2": t.tp2,
        "tp3": t.tp3,
        "score": t.score,
        "reason": t.reason,
        "market_condition": t.market_condition,
        "entry_timestamp": t.entry_timestamp,
        "exit_timestamp": t.exit_timestamp,
        "exit_price": t.exit_price,
        "result": t.result,
        "r_multiple": round(t.r_multiple, 4),
        "fees": round(t.fees, 4),
        "slippage": round(t.slippage_cost, 4),
        "funding": round(t.funding_cost, 4),
        "size": round(t.size, 8),
        "realized_pnl": round(t._realized_pnl, 4),
    }


def save_journal(trades: List[Trade], path_prefix: str) -> tuple:
    """Persist trades to CSV and JSON. ``path_prefix`` excludes extension."""
    csv_path = path_prefix + ".csv"
    json_path = path_prefix + ".json"
    rows = [_trade_row(t) for t in trades]
    if rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2, default=str)
    return csv_path, json_path
