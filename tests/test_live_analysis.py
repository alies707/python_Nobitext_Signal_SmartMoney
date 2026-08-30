from __future__ import annotations

from models.candle import Candle
from strategy.trend_momentum_pullback import StrategyConfig, TrendMomentumPullbackStrategy


def _candles(count: int = 260) -> list[Candle]:
    out: list[Candle] = []
    for i in range(count):
        close = 100.0 + i * 0.05
        out.append(
            Candle(
                timestamp=1_700_000_000_000 + i * 900_000,
                open=close - 0.1,
                high=close + 0.2,
                low=close - 0.2,
                close=close,
                volume=100.0,
            )
        )
    return out


def test_strategy_diagnostics_expose_all_gate_checks():
    candles = _candles()
    strategy = TrendMomentumPullbackStrategy(
        StrategyConfig(min_atr_pct=0.0001, max_atr_pct=0.10)
    )
    diagnostics = strategy.diagnose(candles, candles)

    expected = {
        "data",
        "htf_regime",
        "atr_filter",
        "breakout",
        "pullback_window",
        "pullback_confirmation",
        "risk_reward",
        "final_signal",
    }
    assert expected.issubset(diagnostics)
    assert diagnostics["final_signal"] is False


def test_strategy_diagnostics_never_uses_future_candles():
    candles = _candles()
    strategy = TrendMomentumPullbackStrategy()
    full = strategy.diagnose(candles, candles)
    truncated = strategy.diagnose(candles[:-1], candles[:-1])
    assert isinstance(full, dict)
    assert isinstance(truncated, dict)
    assert full["data"] is True
    assert truncated["data"] is True
