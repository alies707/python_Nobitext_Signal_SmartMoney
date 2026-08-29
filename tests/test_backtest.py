"""Unit tests for the backtest engine and performance analytics."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.helpers import make_bars, make_manager
from strategy.signal_engine import SignalEngine
from risk.risk_manager import RiskManager
from backtest.engine import BacktestEngine
from backtest.performance import compute_performance, save_journal
from config import load_config
from data.candle_manager import CandleManager


BULLISH_SPECS = [
    (100,100,1,1,1), (100,110,1,1,1), (110,130,1,1,1), (130,150,1,1,1),
    (150,165,1,1,1), (165,172,1,1,1), (172,178,1,1,1), (178,180,1,1,1),
    (178,176,2,1,1), (176,172,1,1,1), (172,168,1,1,1), (168,172,1,1,1),
    (172,180,1,1,1), (180,174,0,1,1), (174,150,1,1,1), (150,120,0,0,1),
    (121,128,1,0,1), (128,132,1,1,1), (132,135,1,1,1), (133,128,1,1,1),
    (128,124,1,1,1), (124,122,1,1,1), (122,121,1,1,1), (121,121,1,1,1),
    (122,121,3,3,50), (121,140,1,1,60), (140,149,1,1,1), (149,150,1,1,1),
    (150,151,1,1,1), (151,152,1,1,1),
]


def _build_manager():
    # Build a longer series so the backtest has several cycles to trade.
    specs = list(BULLISH_SPECS)
    # Append a pullback and another bullish impulse to create a 2nd opportunity.
    specs += [
        (152,150,1,1,1), (150,140,2,2,1), (140,138,2,2,1), (138,130,2,2,1),
        (130,120,1,1,1), (120,118,1,1,1), (118,119,3,3,50), (119,145,1,1,60),
        (145,150,1,1,1), (150,151,1,1,1),
    ]
    return make_manager("TEST", make_bars(specs), bullish_htf=True)


def test_backtest_runs_and_produces_trades():
    mgr = _build_manager()
    cfg = load_config()
    eng = SignalEngine(cfg)
    rm = RiskManager(cfg, capital=cfg.initial_capital)
    bt = BacktestEngine(cfg, eng, rm)
    trades = bt.run(mgr, "15m", verbose=False)
    assert isinstance(trades, list)
    # Performance must run even with zero trades.
    perf = compute_performance(trades, cfg.initial_capital)
    assert perf.total_trades == len(trades)


def test_backtest_no_look_ahead_future_data():
    # The engine must never access candles beyond the current index.
    mgr = _build_manager()
    cfg = load_config()
    eng = SignalEngine(cfg)

    # Patch analyze to verify it only ever sees truncated history.
    original = eng.analyze
    violations = []

    def spy(manager, symbol, entry_tf):
        for tf, candles in manager.candles.items():
            if any(c.timestamp > manager.candles[entry_tf][-1].timestamp for c in candles):
                violations.append(tf)
        return original(manager, symbol, entry_tf)

    eng.analyze = spy
    rm = RiskManager(cfg, capital=cfg.initial_capital)
    bt = BacktestEngine(cfg, eng, rm)
    bt.run(mgr, "15m", verbose=False)
    assert violations == [], f"Future data accessed in timeframes: {violations}"


def test_performance_stats_correct():
    from backtest.engine import Trade

    trades = [
        Trade("a", "TEST", "LONG", 100, 95, 110, 120, 130, 20, "x", "y",
              entry_timestamp=1, size=10, result="WIN", _realized_pnl=100.0),
        Trade("b", "TEST", "LONG", 100, 95, 110, 120, 130, 20, "x", "y",
              entry_timestamp=2, size=10, result="LOSS", _realized_pnl=-50.0),
    ]
    perf = compute_performance(trades, 1_000_000)
    assert perf.total_trades == 2
    assert perf.winning_trades == 1
    assert perf.losing_trades == 1
    assert perf.win_rate == 50.0
    assert perf.total_pnl == 50.0


def test_save_journal_writes_files():
    import tempfile, json
    from backtest.engine import Trade

    trades = [
        Trade("a", "TEST", "LONG", 100, 95, 110, 120, 130, 20, "x", "y",
              entry_timestamp=1, size=10, _realized_pnl=100.0, result="WIN",
              r_multiple=2.0, exit_price=110, exit_timestamp=2),
    ]
    with tempfile.TemporaryDirectory() as d:
        prefix = os.path.join(d, "journal_TEST_15m")
        csv_path, json_path = save_journal(trades, prefix)
        assert os.path.exists(csv_path)
        assert os.path.exists(json_path)
        with open(json_path) as fh:
            data = json.load(fh)
        assert data[0]["trade_id"] == "a"


def test_backtest_handles_insufficient_data():
    mgr = CandleManager(symbol="X")
    mgr.set_candles("15m", make_bars(BULLISH_SPECS[:5]))
    mgr.set_candles("4H", make_bars(BULLISH_SPECS[:5]))
    mgr.set_candles("1D", make_bars(BULLISH_SPECS[:5]))
    cfg = load_config()
    eng = SignalEngine(cfg)
    rm = RiskManager(cfg, capital=cfg.initial_capital)
    bt = BacktestEngine(cfg, eng, rm)
    trades = bt.run(mgr, "15m", verbose=False)
    assert trades == []
