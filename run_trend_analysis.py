"""Live Nobitex market-data analyzer for Strategy V2.

Fetches real OHLCV data from Nobitex and prints an auditable decision path.
This script never places orders. It does not treat a data-quality warning as
an execution failure, but it clearly reports the warning so research/backtest
code can decide whether the dataset is acceptable.
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
    StrategyConfig,
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


def expected_interval_ms(label: str) -> int | None:
    return {
        "5m": 5 * 60 * 1000,
        "15m": 15 * 60 * 1000,
        "1H": 60 * 60 * 1000,
        "4H": 4 * 60 * 60 * 1000,
        "1D": 24 * 60 * 60 * 1000,
    }.get(label)


def gap_details(label: str, candles: Sequence[Candle]) -> list[tuple[int, int, int]]:
    expected = expected_interval_ms(label)
    if expected is None:
        return []
    gaps: list[tuple[int, int, int]] = []
    for previous, current in zip(candles, candles[1:]):
        delta = current.timestamp - previous.timestamp
        if delta != expected:
            gaps.append((previous.timestamp, current.timestamp, delta))
    return gaps


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
    gaps = gap_details(label, candles)
    print(f"Timestamp gaps   : {len(gaps)}")
    if gaps:
        previous_ts, current_ts, delta = gaps[0]
        expected = expected_interval_ms(label)
        print(
            "First gap        : "
            f"{fmt_ts(previous_ts)} -> {fmt_ts(current_ts)} "
            f"({delta / 60000:.1f} min; expected {expected / 60000:.1f} min)"
        )


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


def print_diagnostics(diagnostics: dict) -> None:
    print("\n[DECISION GATES]")
    print(f"Data ready       : {'PASS' if diagnostics['data'] else 'FAIL'}")
    print(f"HTF data ready   : {'PASS' if diagnostics['htf_data'] else 'FAIL'}")
    print(
        f"HTF regime       : {diagnostics['htf_regime']} "
        f"({'PASS' if diagnostics['htf_regime_ok'] else 'FAIL'})"
    )
    atr_pct = diagnostics.get("atr_pct")
    atr_text = "N/A" if atr_pct is None else f"{atr_pct * 100:.3f}%"
    print(
        f"ATR filter       : {'PASS' if diagnostics['atr_filter'] else 'FAIL'} "
        f"({atr_text})"
    )
    print(f"Breakout         : {'PASS' if diagnostics['breakout'] else 'FAIL'}")

    breakout = diagnostics.get("breakout_candidate")
    if breakout is not None:
        print(f"Breakout dir     : {breakout.direction.value}")
        print(f"Breakout candle  : {breakout.breakout_index}")
        print(f"Breakout level   : {fmt_price(breakout.breakout_level)}")
        print(f"Pullback window  : {'PASS' if diagnostics['pullback_window'] else 'FAIL'}")
    else:
        print("Pullback window  : N/A")

    print(
        f"Pullback confirm : "
        f"{'PASS' if diagnostics['pullback_confirmation'] else 'FAIL'}"
    )
    rr = diagnostics.get("risk_reward")
    print(f"Risk/Reward      : {'N/A' if rr is None else f'{rr:.2f}R'}")
    print(f"Final gate       : {'PASS' if diagnostics['final_signal'] else 'FAIL'}")
    if diagnostics.get("blocking_reason"):
        print(f"Blocking reason  : {diagnostics['blocking_reason']}")


def print_signal(signal) -> None:
    print("\n[STRATEGY V2 RESULT]")
    if signal is None:
        print("State            : NO_VALID_SETUP")
        print("Signal           : NONE")
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

    print("\n[STRATEGY AUDIT]")
    diagnostics = strategy.diagnose(entry, htf_candles=htf4h)
    print_diagnostics(diagnostics)

    if htf1d:
        daily_regime = _htf_regime(htf1d, strategy_config)
        print(f"1D independent check: {daily_regime}")
        if daily_regime != diagnostics["htf_regime"]:
            print("HTF consistency  : WARNING (4H and 1D regimes disagree)")
        else:
            print("HTF consistency  : PASS (4H and 1D regimes agree)")

    print("\n[FINAL RESULT]")
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
