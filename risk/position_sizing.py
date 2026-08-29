"""Position sizing.

Pure, deterministic calculation of position size from risk parameters.

    position_size = risk_amount / stop_distance

where ``risk_amount = capital * risk_per_trade``. Slippage and fees are
accounted for so the realized risk stays within the configured limit.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class PositionSizeResult:
    risk_amount: float
    stop_distance: float
    position_size: float  # units of base asset
    notional: float       # quote exposure
    valid: bool
    reason: str = ""


def compute_position_size(
    capital: float,
    risk_per_trade: float,
    entry: float,
    stop_loss: float,
    price_precision: float = 1.0,
    fee_rate: float = 0.0,
    slippage: float = 0.0,
) -> PositionSizeResult:
    """Compute position size for a proposed trade.

    Returns ``valid=False`` when inputs are invalid (zero/negative distance,
    non-positive prices, etc.) so the risk manager can reject the trade.
    """
    if capital <= 0 or entry <= 0 or stop_loss <= 0:
        return PositionSizeResult(0.0, 0.0, 0.0, 0.0, False, "invalid prices")
    stop_distance = abs(entry - stop_loss)
    if stop_distance <= 0:
        return PositionSizeResult(0.0, 0.0, 0.0, 0.0, False, "zero stop distance")

    risk_amount = capital * risk_per_trade
    # Adjust risk for expected exit slippage + fee on entry.
    effective_risk = risk_amount * (1.0 - fee_rate - slippage)
    if effective_risk <= 0:
        return PositionSizeResult(risk_amount, stop_distance, 0.0, 0.0, False, "risk eroded by costs")

    size = effective_risk / stop_distance
    notional = size * entry
    return PositionSizeResult(
        risk_amount=risk_amount,
        stop_distance=stop_distance,
        position_size=size,
        notional=notional,
        valid=True,
    )
