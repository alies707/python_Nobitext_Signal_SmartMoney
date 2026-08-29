"""Unit tests for the Signal Engine (end-to-end setup generation)."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.helpers import make_bars, make_manager
from strategy.signal_engine import SignalEngine
from config import load_config
from models.signal import Signal, Confidence
from models.setup import Direction, Bias, ZoneType
from data.candle_manager import CandleManager
from models.candle import Candle


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


def _mirror(specs, center=150.0, offset=200.0):
    """Invert a bullish spec list into a bearish one (price levels flipped
    around ``center``, open->open / close->close; wicks swap), then shift up by
    a constant ``offset`` so all prices stay positive. The offset preserves
    every relative relationship, so the series is a clean bearish twin."""
    out = []
    for (o, c, wu, wd, v) in specs:
        no = offset + center - o
        nc = offset + center - c
        nwu = wd
        nwd = wu
        out.append((no, nc, nwu, nwd, v))
    return out


def test_bullish_setup_generates_long_signal():
    mgr = make_manager("TEST", make_bars(BULLISH_SPECS), bullish_htf=True)
    eng = SignalEngine(load_config())
    sig = eng.analyze(mgr, "TEST", "15m")
    assert isinstance(sig, Signal)
    assert sig.direction == Direction.LONG
    assert sig.smart_money_score >= 16
    assert sig.risk_reward >= 2.0
    assert sig.entry is not None and sig.stop_loss is not None
    assert sig.tp1 is not None
    assert sig.confidence in (Confidence.MEDIUM, Confidence.HIGH)


def test_bearish_setup_generates_short_signal():
    mgr = make_manager("TEST", make_bars(_mirror(BULLISH_SPECS)), bullish_htf=False)
    eng = SignalEngine(load_config())
    sig = eng.analyze(mgr, "TEST", "15m")
    assert sig.direction == Direction.SHORT
    assert sig.smart_money_score >= 16
    assert sig.risk_reward >= 2.0
    assert sig.entry is not None and sig.stop_loss is not None


def test_no_signal_when_no_htf_bias():
    # Manager without HTF candles -> NO_BIAS -> no forced signal.
    mgr = CandleManager(symbol="TEST")
    mgr.set_candles("15m", make_bars(BULLISH_SPECS))
    eng = SignalEngine(load_config())
    sig = eng.analyze(mgr, "TEST", "15m")
    assert sig.direction == Direction.NONE
    assert sig.smart_money_score == 0


def test_signal_is_reproducible_and_structured():
    mgr = make_manager("TEST", make_bars(BULLISH_SPECS), bullish_htf=True)
    eng = SignalEngine(load_config())
    sig1 = eng.analyze(mgr, "TEST", "15m")
    sig2 = eng.analyze(mgr, "TEST", "15m")
    assert sig1.to_dict() == sig2.to_dict()


def test_score_breakdown_present():
    mgr = make_manager("TEST", make_bars(BULLISH_SPECS), bullish_htf=True)
    eng = SignalEngine(load_config())
    sig = eng.analyze(mgr, "TEST", "15m")
    # Every component of the scoring model must be represented.
    for key in ["HTF Bias", "Liquidity", "Sweep", "Displacement", "MSS",
                "FVG", "Order Block", "Premium/Discount", "Liquidity Target"]:
        assert key in sig.score_breakdown
