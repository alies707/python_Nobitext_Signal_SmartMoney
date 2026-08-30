from __future__ import annotations

import argparse
from datetime import datetime, timezone

from config import load_config
from data.historical_data import HistoricalData
from exchange.nobitex_client import NobitexClient, to_udf_symbol
from backtest.trend_pullback import TrendPullbackBacktester
from backtest.performance_v2 import compute_performance_v2
from strategy.trend_momentum_pullback import StrategyConfig, TrendMomentumPullbackStrategy


def ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest Trend/Momentum/Pullback Strategy V2 on Nobitex OHLCV.")
    parser.add_argument("--symbol", default="BTCIRT")
    parser.add_argument("--timeframe", default="15m", choices=["5m", "15m", "1H", "4H"])
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--equity", type=float, default=None)
    args = parser.parse_args()
    if args.limit < 250:
        raise SystemExit("--limit must be at least 250")

    cfg = load_config()
    client = NobitexClient(api_key=cfg.nobitex_api_key, api_url=cfg.nobitex_api_url)
    if not client.health_check():
        print("ERROR: Nobitex API unavailable")
        return 2

    hist = HistoricalData(client)
    manager = hist.download(to_udf_symbol(args.symbol), ["1D", "4H", args.timeframe], args.limit, use_cache=False)
    entry = manager.get(args.timeframe)
    htf = manager.get("4H")
    if len(entry) < 250 or len(htf) < 1:
        print(f"ERROR: insufficient data entry={len(entry)} 4H={len(htf)}")
        return 3

    strategy = TrendMomentumPullbackStrategy(StrategyConfig())
    result = TrendPullbackBacktester(strategy, cfg).run(
        entry, htf, to_udf_symbol(args.symbol), initial_equity=args.equity
    )
    perf = compute_performance_v2(result)
    coverage_days = ((entry[-1].timestamp - entry[0].timestamp) / 86_400_000) if len(entry) >= 2 else 0.0

    print("=" * 72)
    print("NOBITEX TREND / MOMENTUM / PULLBACK V2 BACKTEST")
    print("=" * 72)
    print(f"Symbol             : {to_udf_symbol(args.symbol)}")
    print(f"Timeframe          : {args.timeframe}")
    print(f"Entry candles      : {len(entry)}")
    print(f"4H candles         : {len(htf)}")
    print(f"Period             : {ts(entry[0].timestamp)} -> {ts(entry[-1].timestamp)}")
    print(f"Coverage           : {coverage_days:.2f} days")
    print(f"Initial equity     : {result.initial_equity:,.2f}")
    print(f"Final equity       : {result.final_equity:,.2f}")
    print(f"Total PnL          : {perf.total_pnl:+,.2f}")
    print(f"Total return       : {perf.total_return_pct:+.3f}%")
    print(f"Trades             : {perf.total_trades}")
    print(f"Wins               : {perf.wins}")
    print(f"Losses             : {perf.losses}")
    print(f"Win rate           : {perf.win_rate_pct:.2f}%")
    print(f"Profit factor      : {perf.profit_factor:.3f}")
    print(f"Average R          : {perf.average_r:+.3f}R")
    print(f"Expectancy         : {perf.expectancy_r:+.3f}R")
    print(f"Max drawdown       : {perf.max_drawdown_pct:.3f}%")
    print(f"Max loss streak    : {perf.max_consecutive_losses}")
    print(f"Max win streak     : {perf.max_consecutive_wins}")
    print(f"LONG                : {perf.long.trades} trades | {perf.long.win_rate_pct:.2f}% win | PF {perf.long.profit_factor:.3f} | PnL {perf.long.total_pnl:+,.2f}")
    print(f"SHORT               : {perf.short.trades} trades | {perf.short.win_rate_pct:.2f}% win | PF {perf.short.profit_factor:.3f} | PnL {perf.short.total_pnl:+,.2f}")
    print(f"Sample assessment  : {'SUFFICIENT FOR PRELIMINARY TEST' if perf.total_trades >= 30 and coverage_days >= 90 else 'INSUFFICIENT FOR STRATEGY VALIDATION'}")
    print("Execution model    : next-bar open + slippage; stop wins ambiguous bar")
    print("Look-ahead         : BLOCKED; completed HTF candles only")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
