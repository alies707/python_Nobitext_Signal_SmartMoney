"""Risk manager.

Enforces account-level risk limits and decides whether a proposed signal may be
taken. No order execution is performed (Phase 1 is analysis/backtesting only).

Limits:
* risk per trade
* maximum daily loss
* maximum open positions
* maximum correlated exposure

The manager is stateful with respect to the *current* session (open positions
and realized daily PnL) so it can be reused by the backtest engine and a future
live monitor. It is intentionally free of any IO.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config import Config
from models.signal import Signal
from risk.position_sizing import compute_position_size


@dataclass
class Position:
    symbol: str
    direction: str
    entry: float
    stop_loss: float
    size: float
    risk_amount: float
    correlation_group: str = "default"


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    position_size: float = 0.0
    notional: float = 0.0
    risk_amount: float = 0.0


class RiskManager:
    def __init__(self, config: Config, capital: Optional[float] = None):
        self.config = config
        self.capital = capital if capital is not None else config.initial_capital
        self.open_positions: List[Position] = []
        self.realized_pnl_today: float = 0.0
        self.daily_loss_limit = self.capital * config.max_daily_loss

    # ------------------------------------------------------------------ #
    def can_open_new(self) -> bool:
        return len(self.open_positions) < self.config.max_open_positions

    def daily_loss_breached(self) -> bool:
        return self.realized_pnl_today <= -self.daily_loss_limit

    def correlated_exposure(self, group: str = "default") -> float:
        return sum(p.risk_amount for p in self.open_positions if p.correlation_group == group)

    # ------------------------------------------------------------------ #
    def evaluate(self, signal: Signal, correlation_group: str = "default") -> RiskDecision:
        """Evaluate a signal against all risk limits."""
        if signal.direction.value == "NONE":
            return RiskDecision(approved=False, reason="no signal")
        if signal.entry is None or signal.stop_loss is None:
            return RiskDecision(approved=False, reason="missing entry/stop")
        if not self.can_open_new():
            return RiskDecision(approved=False, reason="max open positions reached")
        if self.daily_loss_breached():
            return RiskDecision(approved=False, reason="daily loss limit breached")

        size_result = compute_position_size(
            capital=self.capital,
            risk_per_trade=self.config.risk_per_trade,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            fee_rate=self.config.fee_rate,
            slippage=self.config.slippage,
        )
        if not size_result.valid or size_result.position_size <= 0:
            return RiskDecision(approved=False, reason="invalid position size")

        # Correlated exposure check.
        proposed_risk = size_result.risk_amount
        current_corr = self.correlated_exposure(correlation_group)
        if current_corr + proposed_risk > self.capital * self.config.max_correlated_exposure:
            return RiskDecision(
                approved=False,
                reason="correlated exposure limit exceeded",
                position_size=size_result.position_size,
                notional=size_result.notional,
                risk_amount=proposed_risk,
            )

        return RiskDecision(
            approved=True,
            reason="approved",
            position_size=size_result.position_size,
            notional=size_result.notional,
            risk_amount=proposed_risk,
        )

    # ------------------------------------------------------------------ #
    def open_position(self, signal: Signal, group: str = "default") -> Optional[Position]:
        decision = self.evaluate(signal, group)
        if not decision.approved:
            return None
        pos = Position(
            symbol=signal.symbol,
            direction=signal.direction.value,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            size=decision.position_size,
            risk_amount=decision.risk_amount,
            correlation_group=group,
        )
        self.open_positions.append(pos)
        return pos

    def close_position(self, symbol: str, exit_price: float) -> float:
        """Close a position and book realized PnL. Returns realized PnL."""
        for i, p in enumerate(self.open_positions):
            if p.symbol == symbol:
                if p.direction == "LONG":
                    pnl = (exit_price - p.entry) * p.size
                else:
                    pnl = (p.entry - exit_price) * p.size
                pnl -= p.notional_cost_fees(self.config) if hasattr(p, "notional_cost_fees") else 0.0
                self.realized_pnl_today += pnl
                self.open_positions.pop(i)
                return pnl
        return 0.0


# Helper attached after class for fee-aware PnL (kept simple/transparent).
def _position_notional_cost(pos: Position, config: Config) -> float:
    notional = pos.size * pos.entry
    return notional * (config.fee_rate + config.slippage)


Position.notional_cost_fees = lambda self, cfg: _position_notional_cost(self, cfg)  # type: ignore
