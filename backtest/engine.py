"""Historical backtesting engine with timestamp-safe multi-timeframe data."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import List, Optional

from config import Config
from data.candle_manager import CandleManager
from models.candle import Candle
from models.signal import Direction, Signal
from risk.risk_manager import RiskManager
from strategy.signal_engine import SignalEngine
from utils.logger import get_logger

logger = get_logger(__name__)
TP_ALLOCATION = [0.4, 0.3, 0.3]


def _timeframe_ms(timeframe: str) -> Optional[int]:
    tf = timeframe.strip().upper()
    units = {"M": 60_000, "H": 3_600_000, "D": 86_400_000, "W": 604_800_000}
    if tf in {"1D", "D"}:
        return 86_400_000
    if tf in {"1W", "W"}:
        return 604_800_000
    if tf.endswith("M") or tf.endswith("H") or tf.endswith("D") or tf.endswith("W"):
        try:
            return int(tf[:-1]) * units[tf[-1]]
        except (ValueError, KeyError):
            return None
    return None


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
    result: str = "OPEN"
    r_multiple: float = 0.0
    _realized_pnl: float = 0.0
    _remaining: float = 0.0


class BacktestEngine:
    def __init__(self, config: Config, signal_engine: SignalEngine, risk_manager: RiskManager, funding_per_bar: float = 0.0):
        self.config = config
        self.engine = signal_engine
        self.risk = risk_manager
        self.funding_per_bar = funding_per_bar
        self.trades: List[Trade] = []
        self._open_trade: Optional[Trade] = None
        self._last_day = None

    def _manager_up_to(self, manager: CandleManager, index: int, entry_tf: str) -> CandleManager:
        """Return only information that was actually known at the entry bar.

        Entry timeframe is cut by index. Higher timeframes are cut by timestamp,
        and an in-progress HTF candle is excluded because its final OHLC is not
        known yet. This prevents MTF look-ahead bias.
        """
        truncated = CandleManager(symbol=manager.symbol)
        entry_candles = manager.get(entry_tf)
        if not entry_candles or index >= len(entry_candles):
            return truncated
        now = entry_candles[index].timestamp
        for tf, candles in manager.candles.items():
            if tf == entry_tf:
                truncated.candles[tf] = candles[: index + 1]
                continue
            duration = _timeframe_ms(tf)
            if duration is None:
                truncated.candles[tf] = [c for c in candles if c.timestamp <= now]
            else:
                truncated.candles[tf] = [c for c in candles if c.timestamp + duration <= now]
        return truncated

    def run(self, manager: CandleManager, entry_tf: str, verbose: bool = False) -> List[Trade]:
        self.trades = []
        self._open_trade = None
        self._last_day = None
        full = manager.get(entry_tf)
        if len(full) < 50:
            logger.warning("Backtest skipped: insufficient candles (%d)", len(full))
            return self.trades

        warmup = max(self.engine.atr_period, self.engine.vol_period) + 10
        pending_entry: Optional[Signal] = None
        for i in range(warmup, len(full)):
            current = full[i]
            self._reset_daily_risk_if_needed(current.timestamp)
            truncated = self._manager_up_to(manager, i, entry_tf)
            signal = self.engine.analyze(truncated, manager.symbol, entry_tf)

            if self._open_trade is not None:
                self._update_position(current, signal.timestamp, verbose=verbose)
                if self._open_trade is None:
                    pending_entry = None
                continue

            if pending_entry is not None:
                filled = self._try_fill(pending_entry, current)
                if filled is not None:
                    self._open_trade = filled
                    self.risk.open_positions.append(_as_position(filled, self.config))
                pending_entry = None

            if self._open_trade is None and signal.direction != Direction.NONE:
                decision = self.risk.evaluate(signal)
                if decision.approved:
                    pending_entry = signal

        if self._open_trade is not None:
            last = full[-1]
            self._close_at(self._open_trade, last.close, last.timestamp)
        return self.trades

    def _reset_daily_risk_if_needed(self, timestamp: int) -> None:
        import datetime as dt
        day = dt.datetime.fromtimestamp(timestamp / 1000, tz=dt.timezone.utc).date()
        if self._last_day is None:
            self._last_day = day
        elif day != self._last_day:
            self.risk.realized_pnl_today = 0.0
            self._last_day = day

    def _try_fill(self, signal: Signal, candle: Candle) -> Optional[Trade]:
        entry = signal.entry
        if entry is None or signal.stop_loss is None:
            return None
        slip = entry * self.config.slippage
        if signal.direction == Direction.LONG:
            fill_price = entry + slip
            if candle.low > fill_price:
                return None
        else:
            fill_price = entry - slip
            if candle.high < fill_price:
                return None
        decision = self.risk.evaluate(signal)
        if not decision.approved or decision.position_size <= 0:
            return None
        size = decision.position_size
        fees = fill_price * size * self.config.fee_rate
        return Trade(
            trade_id=str(uuid.uuid4())[:8], symbol=signal.symbol, direction=signal.direction.value,
            entry=fill_price, stop=signal.stop_loss, tp1=signal.tp1, tp2=signal.tp2, tp3=signal.tp3,
            score=signal.smart_money_score, reason=" | ".join(signal.setup_explanation),
            market_condition=signal.htf_bias.value, entry_timestamp=candle.timestamp, size=size,
            fees=fees, _remaining=size,
        )

    def _update_position(self, candle: Candle, ts: int, verbose: bool = False) -> None:
        t = self._open_trade
        if t is None:
            return
        if t.direction == "LONG":
            if candle.low <= t.stop:
                self._close_fraction(t, t.stop, ts, "STOP", t._remaining)
                self._finalize(t, ts, "STOP")
                return
            for frac, tp in zip(TP_ALLOCATION, [t.tp1, t.tp2, t.tp3]):
                if tp is not None and t._remaining > 0 and candle.high >= tp:
                    self._close_fraction(t, tp, ts, "TP", min(t._remaining, t.size * frac))
        else:
            if candle.high >= t.stop:
                self._close_fraction(t, t.stop, ts, "STOP", t._remaining)
                self._finalize(t, ts, "STOP")
                return
            for frac, tp in zip(TP_ALLOCATION, [t.tp1, t.tp2, t.tp3]):
                if tp is not None and t._remaining > 0 and candle.low <= tp:
                    self._close_fraction(t, tp, ts, "TP", min(t._remaining, t.size * frac))
        if t._remaining <= 1e-12:
            self._finalize(t, ts, "TP")

    def _close_fraction(self, t: Trade, price: float, ts: int, kind: str, qty: float) -> None:
        if qty <= 0:
            return
        pnl = (price - t.entry) * qty if t.direction == "LONG" else (t.entry - price) * qty
        fees = price * qty * self.config.fee_rate
        t._realized_pnl += pnl - fees
        t.fees += fees
        t._remaining = max(0.0, t._remaining - qty)
        t.exit_price = price
        t.exit_timestamp = ts

    def _finalize(self, t: Trade, ts: int, reason: str) -> None:
        t.exit_timestamp = t.exit_timestamp or ts
        t.result = "WIN" if t._realized_pnl >= 0 else "LOSS"
        risk = abs(t.entry - t.stop) * t.size
        t.r_multiple = t._realized_pnl / risk if risk > 0 else 0.0
        self.risk.realized_pnl_today += t._realized_pnl
        self.risk.open_positions = [p for p in self.risk.open_positions if p.symbol != t.symbol]
        self.trades.append(t)
        self._open_trade = None

    def _close_at(self, t: Trade, price: float, ts: int) -> None:
        if t._remaining > 0:
            self._close_fraction(t, price, ts, "END", t._remaining)
        self._finalize(t, ts, "END")


def _as_position(trade: Trade, config: Config):
    from risk.risk_manager import Position
    return Position(
        symbol=trade.symbol, direction=trade.direction, entry=trade.entry,
        stop_loss=trade.stop, size=trade.size,
        risk_amount=abs(trade.entry - trade.stop) * trade.size,
    )
