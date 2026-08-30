"""Live Nobitex market-data analyzer for Strategy V2.

Fetches real OHLCV data from Nobitex and prints the complete analysis path in
plain terminal output. This script does not place orders and does not fabricate
missing data.

Examples:
    python run_trend_analysis.py --symbol BTCIRT
    python run_trend_analysis.py --symbol BTCIRT --timeframe 15m --limit 800
    python run_trend_analysis.py --symbol BTCIRT --timeframe 1H
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Sequence

from config import load_config
from data.historical_data import HistoricalData
from exchange.nobitex_client import NobitexClient, to_udf_symbol
from models.candle import Candle
from strategy.trend_momentum_pullback import (
    Direction,
    StrategyConfig,
    StrategyState,
    TrendMomentumPullbackStrategy,
    _atr,
    _ema,
    _htf_regime,
)


def fmt_price(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.2f}"


def fmt_ts(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def print_candle_summary(label: str, candles: Sequence[Candle]) -> None:
    print(f"\n[{label} DATA]")
    print(f"Candles received : {len(candles)}")
    if not candles:
        print("Status           : NO DATA")
        return
    first = candles[0]
    last = candles[-1]
    print(f"First candle     : {fmt_ts(first.timestamp)}")
    print(f"Last candle      : {fmt_ts(last.timestamp)}")
    print(f"Last close       : {fmt_price(last.close)}")
    print(f"Last volume      : {last.volume:,.4f}")
    gaps = 0
    if len(candles) > 1:
        expected = {
            "15m": 15 * 60 * 1000,
            "1H": 60 * 60 * 1000,
            "4H": 4 * 60 * 60 * 1000,
            "1D": 24 * 60 * 60 * 1000,
        }.get(label)
        if expected:
            gaps = sum(
                1 for a, b in zip(candles, candles[1:]) if b.timestamp - a.timestamp != expected
            )
    print(f"Timestamp gaps   : {gaps}")


def print_indicator_summary(entry: Sequence[Candle], htf4h: Sequence[Candle], htf1d: Sequence[Candle], config: StrategyConfig) -> None:
    print("\n[MARKET ANALYSIS]")
    if not entry:
        print("Entry timeframe  : NO DATA")
        return

    closes = [c.close for c in entry]
    ema20 = _ema(closes, config.execution_ema)
    atr = _atr(entry, config.atr_period)
    last = len(entry) - 1
    print(f"Execution close  : {fmt_price(closes[last])}")
    print(f"EMA{config.execution_ema:<14}: {fmt_price(ema20[last])}")
    print(f"ATR{config.atr_period:<14}: {fmt_price(atr[last])}")
    if atr[last] is not None and closes[last] > 0:
        print(f"ATR %            : {(atr[last] / closes[last]) * 100:.3f}%")
    print(f"HTF 4H regime    : {_htf_regime(htf4h, config)}")
    print(f"HTF 1D regime    : {_htf_regime(htf1d, config)}")


def print_signal(signal) -> None:
    print("\n[STRATEGY V2 RESULT]")
    if signal is None:
        print("State            : NO_VALID_SETUP")
        print("Signal           : NONE")
        print("Reason           : Current Nobitex data does not satisfy every required condition.")
        return

    print(f"State            : {signal.state.value}")
    print(f"Direction        : {signal.direction.value}")
    print(f"Regime           : {signal.regime}")
    print(f"Timestamp        : {fmt_ts(signal.timestamp)}")
    print(f"Entry            : {fmt_price(signal.entry)}")
    print(f"Stop Loss        : {fmt_price(signal.stop_loss)}")
    print(f"TP1              : {fmt_price(signal.tp1)}")
    print(f"TP2              : {fmt_price(signal.tp2)}")
    print(f"Risk/Reward      : {signal.risk_reward:.2f}R")
    print(f"ATR              : {fmt_price(signal.atr)}")
    print(f"Breakout level   : {fmt_price(signal.breakout_level)}")
    print(f"Risk / trade     : {signal.risk_fraction * 100:.2f}%")
    if signal.position_size is not None:
        print(f"Position size    : {signal.position_size:,.6f}")
    print("\nWhy this signal:")
    for item in signal.explanation:
        print(f"  - {item}")


def analyze(symbol: str, timeframe: str, limit: int, equity: float | None) -> int:
    config = load_config()
    client = NobitexClient(api_key=config.nobitex_api_key, api_url=config.nobitex_api_url)

    print("=" * 72)
    print("NOBITEX LIVE MARKET ANALYSIS - TREND / BREAKOUT / PULLBACK V2")
    print("=" * 72)
    print(f"Symbol           : {to_udf_symbol(symbol)}")
    print(f"Entry timeframe  : {timeframe}")
    print(f"Requested candles: {limit}")
    print("Orders            : DISABLED")
    print("Data source       : Nobitex public OHLCV API")

    if not client.health_check():
        print("\nERROR: Nobitex API is unavailable. No analysis was performed.")
        return 2

    hist = HistoricalData(client)
    manager = hist.download(
        to_udf_symbol(symbol),
        timeframes=["1D", "4H", timeframe],
        limit=limit,
        use_cache=False,
    )

    entry = manager.get(timeframe)
    htf4h = manager.get("4H")
    htf1d = manager.get("1D")

    print_candle_summary(timeframe, entry)
    print_candle_summary("4H", htf4h)
    print_candle_summary("1D", htf1d)

    strategy_config = StrategyConfig()
    strategy = TrendMomentumPullbackStrategy(strategy_config)
    print_indicator_summary(entry, htf4h, htf1d, strategy_config)

    print("\n[DECISION]")
    if not entry or not htf4h or not htf1d:
        print("State            : INSUFFICIENT_DATA")
        print("Signal           : NONE")
        print("Reason           : Required entry and higher-timeframe data is missing.")
        return 0

    signal = strategy.generate(entry, htf_candles=htf4h, equity=equity)
    print_signal(signal)
    print("\n" + "=" * 72)
    print("ANALYSIS COMPLETE - THIS PROGRAM DOES NOT EXECUTE TRADES")
    print("=" * 72)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze live Nobitex OHLCV data with Strategy V2.")
    parser.add_argument("--symbol", default="BTCIRT", help="Nobitex market symbol, e.g. BTCIRT or btc-rls")
    parser.add_argument("--timeframe", default="15m", choices=["5m", "15m", "1H", "4H"], help="Execution timeframe")
    parser.add_argument("--limit", type=int, default=800, help="Number of recent candles to request")
    parser.add_argument("--equity", type=float, default=None, help="Optional account equity for position-size calculation")
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    if args.limit < 250:
        raise SystemExit("--limit must be at least 250 for the default Strategy V2 configuration")
    raise SystemExit(analyze(args.symbol, args.timeframe, args.limit, args.equity))
