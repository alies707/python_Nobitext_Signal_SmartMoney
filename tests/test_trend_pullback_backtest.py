from __future__ import annotations

from config import load_config
from models.candle import Candle
from strategy.trend_momentum_pullback import Direction, StrategyConfig, TrendMomentumPullbackStrategy, TrendPullbackSignal, StrategyState
from backtest.trend_pullback import TrendPullbackBacktester


def _bars(values: list[float], step_ms: int = 900_000, start_ms: int = 1_700_000_000_000) -> list[Candle]:
    out = []
    for i, close in enumerate(values):
        prev = values[i - 1] if i else close
        out.append(Candle(
            timestamp=start_ms + i * step_ms,
            open=prev,
            high=max(prev, close) + 1,
            low=min(prev, close) - 1,
            close=close,
            volume=100.0,
        ))
    return out


def test_backtester_returns_clean_result_for_insufficient_data():
    cfg = load_config()
    strategy = TrendMomentumPullbackStrategy()
    bt = TrendPullbackBacktester(strategy, cfg)
    result = bt.run(_bars([100.0, 101.0]), _bars([100.0, 101.0]), "TEST")
    assert result.trades == []
    assert result.final_equity == cfg.initial_capital


def test_backtester_rejects_non_chronological_entry_data():
    cfg = load_config()
    strategy = TrendMomentumPullbackStrategy()
    bt = TrendPullbackBacktester(strategy, cfg)
    candles = _bars([100.0, 101.0, 102.0])
    candles[1], candles[2] = candles[2], candles[1]
    try:
        bt.run(candles, _bars([100.0, 101.0, 102.0]), "TEST")
    except ValueError as exc:
        assert "strictly increasing" in str(exc)
    else:
        raise AssertionError("non-chronological candles must be rejected")


def test_backtester_conservative_ambiguity_prefers_stop():
    cfg = load_config()
    strategy = TrendMomentumPullbackStrategy(StrategyConfig(
        htf_fast_ema=5,
        htf_slow_ema=10,
        execution_ema=3,
        donchian_period=3,
        atr_period=3,
        min_atr_pct=0.0001,
        max_atr_pct=1.0,
        pullback_window=3,
        min_reward_risk=1.0,
    ))
    bt = TrendPullbackBacktester(strategy, cfg)
    candles = _bars([100 + i for i in range(20)])
    result = bt.run(candles, candles, "TEST")
    assert isinstance(result.trades, list)


def test_backtester_hides_in_progress_htf_candle():
    cfg = load_config()
    strategy = TrendMomentumPullbackStrategy()
    original = strategy.generate
    observed = []

    def spy(candles, htf_candles=None, equity=None):
        now = candles[-1].timestamp
        observed.append((now, list(htf_candles or [])))
        if htf_candles:
            assert all(h.timestamp + 14_400_000 <= now for h in htf_candles)
        return original(candles, htf_candles, equity)

    strategy.generate = spy
    bt = TrendPullbackBacktester(strategy, cfg)
    entry = _bars([100 + i * 0.1 for i in range(260)], step_ms=900_000)
    htf = _bars([100 + i * 0.5 for i in range(100)], step_ms=14_400_000)
    bt.run(entry, htf, "TEST")
    assert observed


def test_backtester_rejects_non_chronological_htf_data():
    cfg = load_config()
    strategy = TrendMomentumPullbackStrategy()
    bt = TrendPullbackBacktester(strategy, cfg)
    htf = _bars([100.0, 101.0, 102.0], step_ms=14_400_000)
    htf[1], htf[2] = htf[2], htf[1]
    try:
        bt.run(_bars([100.0, 101.0, 102.0]), htf, "TEST")
    except ValueError as exc:
        assert "HTF candles must be strictly increasing" in str(exc)
    else:
        raise AssertionError("non-chronological HTF candles must be rejected")


def test_equity_curve_includes_open_trade_mark_to_market():
    cfg = load_config()
    strategy_cfg = StrategyConfig(
        htf_fast_ema=5,
        htf_slow_ema=10,
        execution_ema=3,
        donchian_period=3,
        atr_period=3,
        min_atr_pct=0.0001,
        max_atr_pct=1.0,
        pullback_window=3,
        min_reward_risk=1.0,
    )

    class DeterministicSignalStrategy(TrendMomentumPullbackStrategy):
        def __init__(self):
            super().__init__(strategy_cfg)
            self.calls = 0

        def generate(self, candles, htf_candles=None, equity=None):
            self.calls += 1
            if self.calls != 1:
                return None
            close = candles[-1].close
            stop = close - 5.0
            risk = close - stop
            return TrendPullbackSignal(
                direction=Direction.LONG,
                timestamp=candles[-1].timestamp,
                entry=close,
                stop_loss=stop,
                tp1=close + 10.0,
                tp2=close + 15.0,
                risk_reward=2.0,
                atr=1.0,
                breakout_level=close,
                regime="BULLISH",
                state=StrategyState.ENTRY_TRIGGERED,
                risk_fraction=self.config.risk_per_trade,
                position_size=None,
                explanation=["Deterministic test signal"],
            )

    strategy = DeterministicSignalStrategy()
    bt = TrendPullbackBacktester(strategy, cfg)
    candles = _bars([100.0 + i for i in range(20)] + [121.0, 122.0, 123.0, 124.0])
    htf = _bars([100.0 + i for i in range(20)], step_ms=14_400_000)
    result = bt.run(candles, htf, "TEST")
    assert result.trades
    assert any(value != cfg.initial_capital for _, value in result.equity_curve)
    assert any(value > cfg.initial_capital for _, value in result.equity_curve)
