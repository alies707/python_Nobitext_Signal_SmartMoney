"""Causal backtest engine for TrendMomentumPullbackStrategy V2.

Signals are generated only from candles available at bar close i. Any accepted
signal is filled no earlier than bar i+1 open, with configurable slippage and
entry fee. Exit evaluation is conservative: stop is checked before targets when
both are touched inside the same bar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from config import Config
from models.candle import Candle
from strategy.trend_momentum_pullback import Direction, TrendMomentumPullbackStrategy


@dataclass
class V2Trade:
    trade_id: int
    symbol: str
    direction: Direction
    signal_timestamp: int
    entry_timestamp: int
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    size: float
    entry_fee: float
    exit_fee: float = 0.0
    realized_pnl: float = 0.0
    remaining: float = 0.0
    exit_timestamp: Optional[int] = None
    exit_price: Optional[float] = None
    result: str = "OPEN"
    exit_reason: str = ""

    @property
    def risk_cash(self) -> float:
        return abs(self.entry - self.stop_loss) * self.size

    @property
    def r_multiple(self) -> float:
        return self.realized_pnl / self.risk_cash if self.risk_cash > 0 else 0.0


@dataclass
class V2BacktestResult:
    initial_equity: float
    final_equity: float
    trades: List[V2Trade] = field(default_factory=list)
    equity_curve: List[tuple[int, float]] = field(default_factory=list)


class TrendPullbackBacktester:
    def __init__(self, strategy: TrendMomentumPullbackStrategy, config: Config):
        self.strategy = strategy
        self.config = config

    def run(
        self,
        candles: Sequence[Candle],
        htf_candles: Sequence[Candle],
        symbol: str,
        initial_equity: float | None = None,
    ) -> V2BacktestResult:
        starting_equity = initial_equity if initial_equity is not None else self.config.initial_capital
        equity = starting_equity
        if equity <= 0:
            raise ValueError("initial_equity must be positive")
        if len(candles) < 3 or len(htf_candles) < 1:
            return V2BacktestResult(equity, equity)
        if any(candles[i].timestamp >= candles[i + 1].timestamp for i in range(len(candles) - 1)):
            raise ValueError("entry candles must be strictly increasing")
        if any(htf_candles[i].timestamp >= htf_candles[i + 1].timestamp for i in range(len(htf_candles) - 1)):
            raise ValueError("HTF candles must be strictly increasing")

        trades: List[V2Trade] = []
        open_trade: Optional[V2Trade] = None
        warmup = self.strategy._minimum_candles()
        self._curve: List[tuple[int, float]] = []

        for i in range(warmup, len(candles) - 1):
            bar = candles[i]
            next_bar = candles[i + 1]

            if open_trade is not None:
                self._update_trade(open_trade, bar)
                if open_trade.result != "OPEN":
                    equity += open_trade.realized_pnl
                    trades.append(open_trade)
                    open_trade = None

            if open_trade is None:
                # Only HTF candles whose full OHLC is known by bar close are visible.
                # A 4H candle opening earlier than the 15m bar may still be forming.
                visible_htf = [
                    h for h in htf_candles
                    if h.timestamp + self._timeframe_ms("4H") <= bar.timestamp
                ]
                signal = self.strategy.generate(candles[: i + 1], visible_htf)
                if signal is not None and signal.direction != Direction.NONE:
                    entry_raw = next_bar.open
                    slip = entry_raw * self.config.slippage
                    entry = entry_raw + slip if signal.direction == Direction.LONG else entry_raw - slip
                    risk_per_unit = abs(entry - signal.stop_loss)
                    if risk_per_unit > 0:
                        risk_cash = equity * self.config.risk_per_trade
                        size = risk_cash / risk_per_unit
                        entry_fee = entry * size * self.config.fee_rate
                        open_trade = V2Trade(
                            trade_id=len(trades) + 1,
                            symbol=symbol,
                            direction=signal.direction,
                            signal_timestamp=signal.timestamp,
                            entry_timestamp=next_bar.timestamp,
                            entry=entry,
                            stop_loss=signal.stop_loss,
                            tp1=signal.tp1,
                            tp2=signal.tp2,
                            size=size,
                            entry_fee=entry_fee,
                            realized_pnl=-entry_fee,
                            remaining=size,
                        )

            equity_curve_value = equity + (open_trade.realized_pnl if open_trade is not None else 0.0)
            self._append_equity(equity_curve_value, bar.timestamp)

        if open_trade is not None:
            last = candles[-1]
            self._close_all(open_trade, last.close, last.timestamp, "END")
            equity += open_trade.realized_pnl
            trades.append(open_trade)
            self._append_equity(equity, last.timestamp)

        curve = self._curve
        self._curve = []
        return V2BacktestResult(
            initial_equity=starting_equity,
            final_equity=equity,
            trades=trades,
            equity_curve=curve,
        )

    @staticmethod
    def _timeframe_ms(timeframe: str) -> int:
        tf = timeframe.strip().upper()
        values = {"1M": 60_000, "5M": 300_000, "15M": 900_000, "1H": 3_600_000,
                  "4H": 14_400_000, "1D": 86_400_000}
        try:
            return values[tf]
        except KeyError as exc:
            raise ValueError(f"Unsupported timeframe: {timeframe}") from exc

    def _append_equity(self, value: float, timestamp: int) -> None:
        self._curve.append((timestamp, value))

    def _update_trade(self, trade: V2Trade, candle: Candle) -> None:
        if trade.remaining <= 0:
            trade.result = "WIN" if trade.realized_pnl >= 0 else "LOSS"
            return
        if trade.direction == Direction.LONG:
            if candle.low <= trade.stop_loss:
                self._close_all(trade, trade.stop_loss, candle.timestamp, "STOP")
                return
            hit2 = trade.tp2 is not None and candle.high >= trade.tp2
            hit1 = trade.tp1 is not None and candle.high >= trade.tp1
            if hit2:
                self._close_all(trade, trade.tp2, candle.timestamp, "TP2")
            elif hit1:
                self._close_all(trade, trade.tp1, candle.timestamp, "TP1")
        else:
            if candle.high >= trade.stop_loss:
                self._close_all(trade, trade.stop_loss, candle.timestamp, "STOP")
                return
            hit2 = trade.tp2 is not None and candle.low <= trade.tp2
            hit1 = trade.tp1 is not None and candle.low <= trade.tp1
            if hit2:
                self._close_all(trade, trade.tp2, candle.timestamp, "TP2")
            elif hit1:
                self._close_all(trade, trade.tp1, candle.timestamp, "TP1")

    def _close_all(self, trade: V2Trade, price: float, timestamp: int, reason: str) -> None:
        qty = trade.remaining
        if qty <= 0:
            return
        pnl = (price - trade.entry) * qty if trade.direction == Direction.LONG else (trade.entry - price) * qty
        fee = price * qty * self.config.fee_rate
        trade.realized_pnl += pnl - fee
        trade.exit_fee += fee
        trade.remaining = 0.0
        trade.exit_timestamp = timestamp
        trade.exit_price = price
        trade.exit_reason = reason
        trade.result = "WIN" if trade.realized_pnl >= 0 else "LOSS"
