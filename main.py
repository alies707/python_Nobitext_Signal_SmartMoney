"""Smart Money Trading Engine - terminal entry point.

This module only *orchestrates*. All strategy logic lives in the engine
packages. The terminal layer formats structured results for display; it never
computes signals itself. This keeps the strategy reusable behind any future UI
(Flask, Telegram, REST, ...).

Usage
-----
    python main.py                       # analyze default symbol
    python main.py --symbol BTCIRT
    python main.py --symbol BTCIRT --timeframe 15m
    python main.py --scan                # rank + analyze top 10 markets
    python main.py --backtest
    python main.py --backtest --symbol BTCIRT
    python main.py --backtest --symbol BTCIRT --timeframe 15m
    python main.py --backtest --verbose
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import List, Optional

from config import Config, load_config
from data.candle_manager import CandleManager
from data.historical_data import HistoricalData
from exchange.market_data import MarketDataProvider
from exchange.nobitex_client import NobitexClient, to_stats_key
from models.signal import Signal, Confidence
from models.setup import Direction, Bias
from strategy.signal_engine import SignalEngine
from utils.logger import get_logger
from backtest.engine import BacktestEngine
from backtest.performance import compute_performance, save_journal
from risk.risk_manager import RiskManager

logger = get_logger(__name__)


# ----------------------------------------------------------------------------
# Terminal formatting helpers
# ----------------------------------------------------------------------------
SEP = "=" * 60


def _fmt(value, decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{value:,.{decimals}f}"
    except (ValueError, TypeError):
        return str(value)


def print_header(title: str) -> None:
    print(SEP)
    print(title)
    print("=" * len(title))


def print_system_status(client: NobitexClient) -> None:
    print(SEP)
    print("SMART MONEY TRADING ENGINE")
    print("=" * 29)
    print("\n## System Status\n")
    print(f"Nobitex API       : {'CONNECTED' if client.connected else 'DISCONNECTED'}")
    print("Market Data       : OK")
    print("Strategy Engine   : READY")
    mode = "LIVE ANALYSIS" if not _backtest_mode else "BACKTEST"
    print(f"Mode              : {mode}")


_backtest_mode = False


def print_markets(ranked) -> None:
    print("\n" + SEP)
    print("TOP 10 MARKETS")
    print("==============\n")
    for i, rm in enumerate(ranked, 1):
        print(f"{i}. {rm.snapshot.symbol}  (score {rm.total_score:.3f})")
    print()


def _clear_screen() -> None:
    # ANSI clear + home; harmless on terminals that ignore it.
    print("\033[2J\033[H", end="")


def _none_signal(symbol: str) -> Signal:
    """A placeholder NONE signal used when a market has no data / failed."""
    return Signal(
        symbol=symbol,
        direction=Direction.NONE,
        timestamp=0,
        timeframe="",
        htf_bias=Bias.NO_BIAS,
        entry=None,
        entry_zone_high=None,
        entry_zone_low=None,
        stop_loss=None,
        tp1=None,
        tp2=None,
        tp3=None,
        risk_reward=0.0,
        smart_money_score=0,
        confidence=Confidence.LOW,
        liquidity_target=False,
        setup_explanation=["No data available."],
        score_breakdown={},
    )


def print_dashboard(rows, title: str, connected: bool = True) -> None:
    """Render a compact one-screen table of all analyzed markets.

    ``rows`` is a list of ``(symbol, signal)`` tuples. This keeps the whole
    watchlist / top-markets overview visible on a single screen instead of
    scrolling through verbose per-signal blocks.
    """
    print("\n" + SEP)
    print("SMART MONEY TRADING ENGINE" + ("   [CONNECTED]" if connected else "   [OFFLINE]"))
    print(SEP + "\n")
    print(title)
    print()

    header = (
        f"{'SYMBOL':<13} {'DIR':<5} {'SCORE':>5}  "
        f"{'ENTRY':>14} {'STOP':>14} {'TP1':>14} {'R:R':>5}"
    )
    print(header)
    print("-" * len(header))
    for symbol, sig in rows:
        if sig.direction.value == "NONE":
            print(
                f"{symbol:<13} {'NONE':<5} {'-':>5}  "
                f"{'-':>14} {'-':>14} {'-':>14} {'-':>5}"
            )
        else:
            print(
                f"{symbol:<13} {sig.direction.value:<5} {sig.smart_money_score:>5}  "
                f"{_fmt(sig.entry, 1):>14} {_fmt(sig.stop_loss, 1):>14} "
                f"{_fmt(sig.tp1, 1):>14} {sig.risk_reward:>5.2f}"
            )
    print()


def print_signal(signal: Signal) -> None:
    if signal.direction.value == "NONE":
        print(f"\n## {signal.symbol}\n")
        print("Signal: NONE\n")
        print("Reason:")
        for line in signal.setup_explanation:
            print(f"  - {line}")
        print()
        return

    print("\n" + SEP)
    print("SIGNAL")
    print("======\n")
    print(f"Direction: {signal.direction.value}")
    print()
    print(f"Entry:       {_fmt(signal.entry)}")
    print(f"Stop Loss:   {_fmt(signal.stop_loss)}")
    print()
    print(f"TP1:         {_fmt(signal.tp1)}")
    print(f"TP2:         {_fmt(signal.tp2)}")
    print(f"TP3:         {_fmt(signal.tp3)}")
    print()
    print(f"Risk/Reward: {signal.risk_reward:.2f}")
    print()
    print(f"Smart Money Score: {signal.smart_money_score} / 24")
    print(f"Confidence: {signal.confidence.value}")
    print()
    print(SEP)
    print("SIGNAL EXPLANATION")
    print("=================\n")
    for line in signal.setup_explanation:
        print(f"  {line}")
    print()
    print("Score breakdown:")
    for k, v in signal.score_breakdown.items():
        print(f"  {k:<18} +{v}")
    print()


def print_backtest(perf, symbol: str, timeframe: str, trades, verbose: bool, journal_paths) -> None:
    print("\n" + SEP)
    print("BACKTEST RESULTS")
    print("================\n")
    print(f"Symbol: {symbol}")
    print(f"Timeframe: {timeframe}")
    print()
    print(f"Initial Capital: {_fmt(perf.initial_capital, 0)} IRR")
    print()
    print(f"Trades:            {perf.total_trades}")
    print(f"Winning Trades:    {perf.winning_trades}")
    print(f"Losing Trades:     {perf.losing_trades}")
    print(f"Win Rate:          {perf.win_rate:.2f}%")
    print(f"Profit Factor:     {perf.profit_factor:.2f}")
    print(f"Average R:         {perf.average_r:.2f}")
    print(f"Total Return:      {perf.total_return_pct:+.2f}%")
    print(f"Maximum Drawdown:  -{perf.max_drawdown_pct:.2f}%")
    print(f"Sharpe Ratio:      {perf.sharpe_ratio:.2f}")
    print()
    print(f"LONG Trades:  {perf.long_trades}  (wins: {perf.long_wins})")
    print(f"SHORT Trades: {perf.short_trades}  (wins: {perf.short_wins})")
    print()
    if journal_paths:
        print(f"Journal: {journal_paths[0]} / {journal_paths[1]}")
    if verbose and trades:
        print("\n-- Individual Trades --")
        for t in trades:
            print(
                f"  {t.trade_id} {t.direction:<5} score={t.score:>2} "
                f"entry={_fmt(t.entry)} exit={_fmt(t.exit_price)} "
                f"R={t.r_multiple:+.2f} {t.result}"
            )
    print()


# ----------------------------------------------------------------------------
# Data preparation
# ----------------------------------------------------------------------------
def build_manager(
    hist: HistoricalData, symbol: str, timeframes: List[str], limit: int = 800, use_cache: bool = False
) -> Optional[CandleManager]:
    manager = hist.download(symbol, timeframes=timeframes, limit=limit, use_cache=use_cache)
    # Ensure we got at least one entry-timeframe (5m/15m/1H) candle set.
    entry_tfs = [tf for tf in ("5m", "15m", "1H") if tf in timeframes]
    if not any(manager.get(tf) for tf in entry_tfs):
        logger.error("No entry-timeframe candles retrieved for %s", symbol)
        return None
    return manager


# ----------------------------------------------------------------------------
# Modes
# ----------------------------------------------------------------------------
def run_single(config: Config, symbol: str, timeframe: str) -> None:
    client = NobitexClient(api_key=config.nobitex_api_key, api_url=config.nobitex_api_url)
    client.health_check()
    print_system_status(client)
    hist = HistoricalData(client)
    tfs = sorted(set(["1D", "4H"] + [timeframe]))
    manager = build_manager(hist, symbol, tfs)
    if manager is None:
        print(f"\nUnable to retrieve data for {symbol}. Cannot analyze.")
        return
    engine = SignalEngine(config)
    signal = engine.analyze(manager, symbol, timeframe)
    print_signal(signal)


def run_scan(config: Config, monitor: bool = False, watchlist: Optional[List[str]] = None, verbose: bool = False) -> None:
    global _backtest_mode
    _backtest_mode = False
    client = NobitexClient(api_key=config.nobitex_api_key, api_url=config.nobitex_api_url)
    client.health_check()
    connected = client.connected

    engine = SignalEngine(config)
    hist = HistoricalData(client)

    # Watchlist mode: analyze and show ONLY the requested symbols (in the
    # order given). No market ranking is performed.
    if watchlist:
        title = f"WATCHLIST  ({len(watchlist)} symbols)"
        seen = set()
        try:
            while True:
                rows: List = []
                for raw in watchlist:
                    symbol = to_stats_key(raw)
                    try:
                        tfs = ["1D", "4H", config.default_timeframe]
                        manager = build_manager(hist, symbol, tfs)
                        if manager is None:
                            # Placeholder so the symbol still appears on screen.
                            rows.append((symbol, _none_signal(symbol)))
                            continue
                        signal = engine.analyze(manager, symbol, config.default_timeframe)
                        key = (symbol, signal.direction.value, round(signal.entry or 0, -3))
                        if key in seen:
                            rows.append((symbol, signal))
                            continue
                        seen.add(key)
                        rows.append((symbol, signal))
                    except Exception as exc:  # keep monitoring despite a bad market
                        logger.exception("Analysis failed for %s: %s", symbol, exc)
                        rows.append((symbol, _none_signal(symbol)))
                if monitor:
                    _clear_screen()
                print_dashboard(rows, title, connected)
                if verbose:
                    for symbol, sig in rows:
                        if sig.direction.value != "NONE":
                            print_signal(sig)
                if not monitor:
                    break
                logger.info("Sleeping %ss until next scan cycle", config.scan_interval)
                time.sleep(config.scan_interval)
        except KeyboardInterrupt:
            print("\nScan interrupted by user.")
        return

    # Ranking mode: rank the whole universe, then show a one-screen dashboard.
    provider = MarketDataProvider(client, config)
    ranked = provider.rank_markets(top_n=config.top_markets_count)
    if not ranked:
        print("\nNo markets ranked. Check API connectivity / market stats.")
        return
    title = "TOP MARKETS"
    seen = set()
    try:
        while True:
            rows = []
            for rm in ranked:
                symbol = rm.snapshot.symbol
                try:
                    tfs = ["1D", "4H", config.default_timeframe]
                    manager = build_manager(hist, symbol, tfs)
                    if manager is None:
                        rows.append((symbol, _none_signal(symbol)))
                        continue
                    signal = engine.analyze(manager, symbol, config.default_timeframe)
                    rows.append((symbol, signal))
                except Exception as exc:
                    logger.exception("Analysis failed for %s: %s", symbol, exc)
                    rows.append((symbol, _none_signal(symbol)))
            if monitor:
                _clear_screen()
            print_dashboard(rows, title, connected)
            if verbose:
                for symbol, sig in rows:
                    if sig.direction.value != "NONE":
                        print_signal(sig)
            if not monitor:
                break
            logger.info("Sleeping %ss until next scan cycle", config.scan_interval)
            time.sleep(config.scan_interval)
    except KeyboardInterrupt:
        print("\nScan interrupted by user.")


def run_backtest(config: Config, symbol: Optional[str], timeframe: str, verbose: bool) -> None:
    global _backtest_mode
    _backtest_mode = True
    client = NobitexClient(api_key=config.nobitex_api_key, api_url=config.nobitex_api_url)
    client.health_check()
    print_system_status(client)

    symbol = symbol or _first_tradable(client, config) or "BTCIRT"
    hist = HistoricalData(client)
    tfs = sorted(set(["1D", "4H"] + [timeframe]))
    manager = build_manager(hist, symbol, tfs, limit=1500)
    if manager is None:
        print(f"\nUnable to retrieve historical data for {symbol}. Cannot backtest.")
        return

    engine = SignalEngine(config)
    risk = RiskManager(config, capital=config.initial_capital)
    bt = BacktestEngine(config, engine, risk)
    trades = bt.run(manager, timeframe, verbose=verbose)
    perf = compute_performance(trades, config.initial_capital)
    print_backtest(perf, symbol, timeframe, trades, verbose, None)

    if trades:
        prefix = f"data/journal_{symbol}_{timeframe}"
        paths = save_journal(trades, prefix)
        print(f"Journal saved to {paths[0]} and {paths[1]}")
    else:
        print("No trades generated (strategy produced no valid setups).")


def _first_tradable(client: NobitexClient, config: Config) -> Optional[str]:
    try:
        stats = client.get_market_stats()
        # v2 stats keys use dash-lowercase form, e.g. "btc-rls".
        for sym in stats:
            if sym.endswith("-rls") or sym.endswith("-usdt"):
                return sym
    except Exception:
        pass
    return None


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="smart_money_trading_engine",
        description="Standalone Smart Money (ICT/RTM) crypto trading strategy engine.",
    )
    p.add_argument("--symbol", type=str, default=None, help="Market symbol, e.g. BTCIRT")
    p.add_argument("--timeframe", type=str, default=None, help="Entry timeframe, e.g. 15m")
    p.add_argument("--scan", action="store_true", help="Rank and analyze top markets")
    p.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="Comma-separated watchlist, e.g. btc-rls,eth-rls,xrp-rls",
    )
    p.add_argument("--monitor", action="store_true", help="Continuously monitor (with --scan)")
    p.add_argument("--backtest", action="store_true", help="Run historical backtest")
    p.add_argument("--verbose", action="store_true", help="Verbose output (e.g. per-trade)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    config = load_config()
    problems = config.validate()
    if problems:
        for p in problems:
            logger.error("Config problem: %s", p)
        return 2

    timeframe = args.timeframe or config.default_timeframe

    if args.backtest:
        run_backtest(config, args.symbol, timeframe, args.verbose)
        return 0

    # Resolve the effective watchlist (CLI --symbols overrides config WATCHLIST).
    watchlist = None
    if args.symbols:
        watchlist = [s.strip() for s in args.symbols.split(",") if s.strip()]
    elif config.watchlist:
        watchlist = config.watchlist

    if args.scan or watchlist:
        run_scan(config, monitor=args.monitor, watchlist=watchlist, verbose=args.verbose)
        return 0

    symbol = args.symbol or "BTCIRT"
    run_single(config, symbol, timeframe)
    return 0


if __name__ == "__main__":
    sys.exit(main())
