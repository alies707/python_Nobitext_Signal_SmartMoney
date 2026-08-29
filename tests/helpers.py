"""Shared test helpers for building synthetic OHLCV candle series.

These helpers let unit tests construct deterministic, look-ahead-free market
scenarios without any network access.
"""
from __future__ import annotations

from typing import List, Optional

from data.candle_manager import CandleManager
from models.candle import Candle


def candle(idx: int, o: float, h: float, l: float, c: float, v: float = 1.0, step_ms: int = 900_000) -> Candle:
    return Candle(timestamp=1_000_000_000_000 + idx * step_ms, open=o, high=h, low=l, close=c, volume=v)


def make_candles(specs) -> List[Candle]:
    """Build candles from a list of (o, h, l, c, v) tuples (or just ohlc)."""
    out = []
    for i, s in enumerate(specs):
        if len(s) == 4:
            o, h, l, c = s
            v = 1.0
        else:
            o, h, l, c, v = s
        out.append(candle(i, o, h, l, c, v))
    return out


def make_bars(specs) -> List[Candle]:
    """Build OHLCV candles from (open, close, wick_up, wick_down, volume).

    This guarantees high >= max(open, close) and low <= min(open, close), so
    every generated candle passes data validation.
    """
    out = []
    for i, (o, c, wu, wd, v) in enumerate(specs):
        h = max(o, c) + abs(wu)
        l = min(o, c) - abs(wd)
        out.append(candle(i, float(o), float(h), float(l), float(c), float(v)))
    return out


def _invert_series(series, center: float = 110.0, offset: float = 200.0):
    """Return a price-inverted copy of an (o, h, l, c) series (high<->low swap,
    open<->close inversion) shifted up by ``offset`` so it stays positive. The
    constant offset preserves every relative relationship, so an ascending
    series becomes a genuine descending one."""
    out = []
    for (o, h, l, c) in series:
        out.append((
            offset + center - c,
            offset + center - l,
            offset + center - h,
            offset + center - o,
        ))
    return out


def make_manager(symbol: str, candles_15m: List[Candle], bullish_htf: bool = True) -> CandleManager:
    """Build a manager with a 15m series plus bullish/bearish 4H and 1D series."""
    mgr = CandleManager(symbol=symbol)
    mgr.set_candles("15m", candles_15m)

    # A deterministic ascending (HH/HL) HTF series. For the bearish case we
    # invert it so it becomes a genuine descending (LH/LL) series.
    bullish = [
        (100, 101, 99, 100), (100, 103, 99, 102), (102, 104, 101, 103), (103, 106, 102, 105),
        (105, 112, 104, 110), (110, 110, 107, 108), (108, 108, 105, 106), (106, 107, 101, 103),
        (103, 111, 102, 109), (109, 113, 108, 111), (111, 120, 110, 118), (118, 118, 115, 116),
        (116, 116, 113, 114), (114, 115, 108, 110), (110, 114, 109, 112), (112, 120, 111, 118),
    ]
    series = bullish if bullish_htf else _invert_series(bullish)
    htf = make_candles([(o, h, l, c, 1.0) for (o, h, l, c) in series])
    mgr.set_candles("4H", htf)
    mgr.set_candles("1D", make_candles([(o, h, l, c, 1.0) for (o, h, l, c) in series]))
    return mgr
