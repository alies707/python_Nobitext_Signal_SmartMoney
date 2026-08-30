from tests.helpers import make_bars, make_manager
from tests.test_signal_engine import BULLISH_SPECS
from strategy.signal_engine import SignalEngine
from strategy.mss import detect_mss
from strategy.liquidity import detect_liquidity
from strategy.displacement import detect_displacement
from strategy.fair_value_gap import FvgContext, find_relevant_fvg
from strategy.order_block import detect_order_block, fvg_near_ob
from config import load_config


def test_debug_signal_pipeline():
    mgr = make_manager("TEST", make_bars(BULLISH_SPECS), bullish_htf=True)
    eng = SignalEngine(load_config())
    candles = mgr.get("15m")
    bias, trends = eng._htf_bias(mgr)
    end = len(candles) - 1
    start = max(eng.vol_period, end - eng.scan_window)
    mss = None
    mss_attempts = []
    for i in range(end, start - 1, -1):
        result = detect_mss(
            candles,
            index=i,
            levels=detect_liquidity(candles, index=i, timeframe="15m"),
            atr_period=eng.atr_period,
            vol_period=eng.vol_period,
            max_gap=eng.mss_lookback,
        )
        mss_attempts.append((i, result.confirmed, result.direction, result.sweep_index, result.displacement_index))
        if result.confirmed and result.direction == "BULLISH":
            mss = result
            break

    if mss is None:
        raise AssertionError(f"NO MSS bias={bias} trends={trends} attempts={mss_attempts}")

    direction = "BULLISH"
    disp = detect_displacement(candles, index=mss.index, atr_period=eng.atr_period, vol_period=eng.vol_period)
    ctx = FvgContext(
        mss_confirmed=True,
        displacement_strong=(disp.volume_ratio or 0.0) > 1.5,
        near_order_block=False,
        htf_aligned=True,
    )
    ob = detect_order_block(candles, mss.index, direction, timeframe="15m")
    fvg = find_relevant_fvg(candles, mss.index, direction, ctx, timeframe="15m")
    dealing_range = eng._dealing_range(candles, mss.index)
    overlap = fvg_near_ob(fvg.lower, fvg.upper, ob) if fvg and ob else None
    entry_zone = eng._entry_zone(fvg, ob) if fvg and ob else None
    report = {
        "bias": str(bias),
        "mss": (mss.index, mss.sweep_index, mss.displacement_index),
        "disp": (disp.confirmed, disp.volume_ratio, disp.atr),
        "ob": repr(ob),
        "fvg": repr(fvg),
        "dealing_range": dealing_range,
        "overlap": overlap,
        "entry_zone": entry_zone,
    }
    raise AssertionError(report)
