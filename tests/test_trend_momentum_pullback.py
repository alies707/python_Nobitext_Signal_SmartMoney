from models.candle import Candle
from strategy.trend_momentum_pullback import (
    Direction,
    StrategyConfig,
    StrategyState,
    TrendMomentumPullbackStrategy,
    _atr,
    _ema,
)


def make_candles(values, start=1_700_000_000_000, step=900_000):
    candles = []
    for i, close in enumerate(values):
        previous = values[i - 1] if i else close
        open_price = previous
        high = max(open_price, close) + 1.0
        low = min(open_price, close) - 1.0
        candles.append(
            Candle(
                timestamp=start + i * step,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=1000.0,
            )
        )
    return candles


def test_ema_and_atr_are_causal_and_sized_correctly():
    candles = make_candles([100 + i for i in range(40)])
    ema = _ema([c.close for c in candles], 10)
    atr = _atr(candles, 14)
    assert len(ema) == len(candles)
    assert len(atr) == len(candles)
    assert ema[8] is None
    assert ema[9] is not None
    assert atr[12] is None
    assert atr[13] is not None


def test_strategy_rejects_neutral_regime():
    candles = make_candles([100 + ((i % 3) - 1) for i in range(260)])
    strategy = TrendMomentumPullbackStrategy()
    assert strategy.generate(candles) is None


def test_config_rejects_invalid_parameters():
    try:
        StrategyConfig(htf_fast_ema=200, htf_slow_ema=50).validate()
    except ValueError:
        return
    raise AssertionError("invalid EMA ordering must raise ValueError")


def test_signal_contract_contains_explicit_state_and_direction():
    values = [100.0 + i * 0.15 for i in range(260)]
    values.extend([139.0, 140.0, 141.5, 140.2, 139.8, 140.5, 141.8])
    candles = make_candles(values)
    strategy = TrendMomentumPullbackStrategy(
        StrategyConfig(
            donchian_period=20,
            pullback_window=8,
            min_atr_pct=0.0001,
            max_atr_pct=0.10,
        )
    )
    signal = strategy.generate(candles, equity=100_000)
    if signal is not None:
        assert signal.direction in (Direction.LONG, Direction.SHORT)
        assert signal.state == StrategyState.ENTRY_TRIGGERED
        assert signal.entry > 0
        assert signal.stop_loss > 0
        assert signal.position_size > 0
