"""Unit tests for risk management and position sizing."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import load_config
from models.signal import Signal, Confidence
from models.setup import Direction, Bias
from risk.risk_manager import RiskManager
from risk.position_sizing import compute_position_size


def _signal(direction="LONG", entry=100.0, stop=95.0):
    return Signal(
        symbol="TEST", direction=Direction(direction), timestamp=0, timeframe="15m",
        htf_bias=Bias.LONG_BIAS, entry=entry, entry_zone_high=entry, entry_zone_low=entry,
        stop_loss=stop, tp1=110.0, tp2=120.0, tp3=130.0, risk_reward=2.0,
        smart_money_score=20, confidence=Confidence.HIGH, liquidity_target=True,
        setup_explanation=[], score_breakdown={},
    )


def test_position_size_basic():
    res = compute_position_size(capital=1_000_000, risk_per_trade=0.01, entry=100.0, stop_loss=95.0)
    assert res.valid
    assert res.position_size == 1_000_000 * 0.01 / 5.0


def test_position_size_zero_distance_invalid():
    res = compute_position_size(capital=1_000_000, risk_per_trade=0.01, entry=100.0, stop_loss=100.0)
    assert not res.valid


def test_position_size_negative_prices_invalid():
    res = compute_position_size(capital=1_000_000, risk_per_trade=0.01, entry=-5.0, stop_loss=95.0)
    assert not res.valid


def test_risk_rejects_none_signal():
    cfg = load_config()
    rm = RiskManager(cfg, capital=1_000_000)
    sig = _signal(direction="NONE")
    dec = rm.evaluate(sig)
    assert not dec.approved


def test_risk_approves_valid_signal():
    cfg = load_config()
    rm = RiskManager(cfg, capital=1_000_000)
    dec = rm.evaluate(_signal())
    assert dec.approved
    assert dec.position_size > 0


def test_max_open_positions_enforced():
    cfg = load_config()
    cfg.max_open_positions = 1
    rm = RiskManager(cfg, capital=1_000_000)
    assert rm.open_position(_signal()) is not None
    # Second position blocked by max-open limit.
    dec = rm.evaluate(_signal())
    assert not dec.approved


def test_daily_loss_limit_enforced():
    cfg = load_config()
    rm = RiskManager(cfg, capital=1_000_000)
    rm.realized_pnl_today = -(1_000_000 * cfg.max_daily_loss) - 1
    dec = rm.evaluate(_signal())
    assert not dec.approved
    assert "daily loss" in dec.reason.lower()


def test_correlated_exposure_limit():
    cfg = load_config()
    rm = RiskManager(cfg, capital=1_000_000)
    big = _signal(entry=100.0, stop=50.0)  # large risk per unit
    dec = rm.evaluate(big)
    # If the single trade already exceeds correlated cap it should be rejected.
    if dec.risk_amount > 1_000_000 * cfg.max_correlated_exposure:
        assert not dec.approved
