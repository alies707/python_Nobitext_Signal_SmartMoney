"""Historical backtesting engine.

Simulates the strategy over historical candles *chronologically*, so the
strategy never sees the future. For every bar the engine:

1. builds a view of the market restricted to candles up to that bar,
2. asks the :class:`SignalEngine` for a signal,
3. if approved by the :class:`RiskManager`, schedules an entry on the next bar
   (only filled if the entry price is actually reachable),
4. manages the position: stop loss, and partial closes at TP1/TP2/TP3,
5. applies fees, slippage and optional funding,
6. records the trade in a journal.

No real orders are placed.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import List, Optional

from config import Config
from data.candle_manager import CandleManager
from models.candle import Candle
from models.signal import Direction, Signal
from risk.position_sizing import compute_position_size
from risk.risk_manager import RiskManager
from strategy.signal_engine import SignalEngine
from utils.logger import get_logger

logger = get_logger(__name__)

# Fraction of the position closed at each target (must sum to 1.0).
TP_ALLOCATION = [0.4, 0.3, 0.3]


@dataclass
class Trade:
    trade_id: str
    symbol: str
    direction: str
    entry: float
    stop: float
    tp1: Optional[float]
    tp2: Optional[float]
    tp3: Optional[float]
    score: int
    reason: str
    market_condition: str
    entry_timestamp: int
    size: float
    fees: float = 0.0
    slippage_cost: float = 0.0
    funding_cost: float = 0.0
    exit_timestamp: Optional[int] = None
    exit_price: Optional[float] = None
    result: str = "OPEN"  # WIN / LOSS / OPEN
    r_multiple: float = 0.0
    _realized_pnl: float = 0.0
    _remaining: float = 0.0


class BacktestEngine:
    def __init__(
        self,
        config: Config,
        signal_engine: SignalEngine,
        risk_manager: RiskManager,
        funding_per_bar: float = 0.0,
    ):
        self.config = config
        self.engine = signal_engine
        self.risk = risk_manager
        self.funding_per_bar = funding_per_bar
        self.trades: List[Trade] = []
        self._open_trade: Optional[Trade] = None

    # ------------------------------------------------------------------ #
    def _manager_up_to(self, manager: CandleManager, index: int) -> CandleManager:
        """Return a manager whose candles are truncated at ``index`` (no future)."""
        truncated = CandleManager(symbol=manager.symbol)
        for tf, candles in manager.candles.items():
            truncated.candles[tf] = candles[: index + 1]
        return truncated

    def run(self, manager: CandleManager, entry_tf: str, verbose: bool = False) -> List[Trade]:
        self.trades = []
        self._open_trade = None
        full = manager.get(entry_tf)
        if len(full) < 50:
            logger.warning("Backtest skipped: insufficient candles (%d)", len(full))
            return self.trades

        warmup = max(self.engine.atr_period, self.engine.vol_period) + 10
        pending_entry: Optional[Signal] = None

        for i in range(warmup, len(full)):
            truncated = self._manager_up_to(manager, i)
            signal = self.engine.analyze(truncated, manager.symbol, entry_tf)

            # Manage an open position on the current bar first.
            if self._open_trade is not None:
                self._update_position(full[i], signal.timestamp, verbose=verbose)
                if self._open_trade is None:
                    pending_entry = None
                continue

            # Try to fill a pending entry from the previous bar.
            if pending_entry is not None:
                filled = self._try_fill(pending_entry, full[i])
                if filled is not None:
                    self._open_trade = filled
                    self.risk.open_positions.append(_as_position(filled, self.config))
                pending_entry = None

            # Queue a new pending entry from a fresh actionable signal.
            if self._open_trade is None and signal.direction != Direction.NONE:
                decision = self.risk.evaluate(signal)
                if decision.approved:
                    pending_entry = signal

        # Force-close any still-open trade at the final bar.
        if self._open_trade is not None:
            last = full[-1]
            self._close_at(self._open_trade, last.close, last.timestamp)
        return self.trades

    # ------------------------------------------------------------------ #
    def _try_fill(self, signal: Signal, candle: Candle) -> Optional[Trade]:
        entry = signal.entry
        if entry is None or signal.stop_loss is None:
            return None
        slip = entry * self.config.slippage
        if signal.direction == Direction.LONG:
            fill_price = entry + slip
            if candle.low > fill_price:
                return None  # entry never reached
        else:
            fill_price = entry - slip
            if candle.high < fill_price:
                return None

        decision = self.risk.evaluate(signal)
        if not decision.approved or decision.position_size <= 0:
            return None
        size = decision.position_size
        fees = fill_price * size * self.config.fee_rate
        trade = Trade(
            trade_id=str(uuid.uuid4())[:8],
            symbol=signal.symbol,
            direction=signal.direction.value,
            entry=fill_price,
            stop=signal.stop_loss,
            tp1=signal.tp1,
            tp2=signal.tp2,
            tp3=signal.tp3,
            score=signal.smart_money_score,
            reason=" | ".join(signal.setup_explanation),
            market_condition=signal.htf_bias.value,
            entry_timestamp=candle.timestamp,
            size=size,
            fees=fees,
            _remaining=size,
        )
        return trade

    def _update_position(self, candle: Candle, ts: int, verbose: bool = False) -> None:
        t = self._open_trade
        if t is None:
            return

        if t.direction == "LONG":
            # Stop takes priority (conservative).
            if candle.low <= t.stop:
                self._close_fraction(t, t.stop, ts, "STOP", t._remaining)
                self._finalize(t, ts, "STOP")
                return
            for frac, tp in zip(TP_ALLOCATION, [t.tp1, t.tp2, t.tp3]):
                if tp is None or t._remaining <= 0:
                    continue
                if candle.high >= tp:
                    self._close_fraction(t, tp, ts, "TP", t.size * frac)
        else:
            if candle.high >= t.stop:
                self._close_fraction(t, t.stop, ts, "STOP", t._remaining)
                self._finalize(t, ts, "STOP")
                return
            for frac, tp in zip(TP_ALLOCATION, [t.tp1, t.tp2, t.tp3]):
                if tp is None or t._remaining <= 0:
                    continue
                if candle.low <= tp:
                    self._close_fraction(t, tp, ts, "TP", t.size * frac)

        if t._remaining <= 1e-12:
            self._finalize(t, ts, "TP")

    def _close_fraction(self, t: Trade, price: float, ts: int, kind: str, qty: float) -> None:
        if qty <= 0:
            return
        if t.direction == "LONG":
            pnl = (price - t.entry) * qty
        else:
            pnl = (t.entry - price) * qty
        fees = price * qty * self.config.fee_rate
        pnl -= fees
        t._realized_pnl += pnl
        t.fees += fees
        t._remaining -= qty
        t.exit_price = price
        t.exit_timestamp = ts

    def _finalize(self, t: Trade, ts: int, reason: str) -> None:
        t.exit_timestamp = t.exit_timestamp or ts
        t.result = "WIN" if t._realized_pnl >= 0 else "LOSS"
        risk = abs(t.entry - t.stop) * t.size if t.stop else 0.0
        t.r_multiple = (t._realized_pnl / risk) if risk > 0 else 0.0
        self.risk.realized_pnl_today += t._realized_pnl
        # Remove from risk manager open positions.
        self.risk.open_positions = [p for p in self.risk.open_positions if p.symbol != t.symbol]
        self._open_trade = None

    def _close_at(self, t: Trade, price: float, ts: int) -> None:
        if t._remaining > 0:
            self._close_fraction(t, price, ts, "END", t._remaining)
        self._finalize(t, ts, "END")


def _as_position(trade: Trade, config: Config):
    """Create a lightweight position record for the risk manager."""
    from risk.risk_manager import Position

    return Position(
        symbol=trade.symbol,
        direction=trade.direction,
        entry=trade.entry,
        stop_loss=trade.stop,
        size=trade.size,
        risk_amount=abs(trade.entry - trade.stop) * trade.size,
    )
