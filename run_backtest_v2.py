from __future__ import annotations

import argparse
from datetime import datetime, timezone

from config import load_config
from data.historical_data import HistoricalData
from exchange.nobitex_client import NobitexClient, to_udf_symbol
from backtest.trend_pullback import TrendPullbackBacktester
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

    strategy_cfg = StrategyConfig()
    strategy = TrendMomentumPullbackStrategy(strategy_cfg)
    bt = TrendPullbackBacktester(strategy, cfg)
    result = bt.run(entry, htf, to_udf_symbol(args.symbol), initial_equity=args.equity)

    wins = sum(1 for t in result.trades if t.result == "WIN")
    losses = sum(1 for t in result.trades if t.result == "LOSS")
    total_pnl = sum(t.realized_pnl for t in result.trades)
    print("=" * 72)
    print("NOBITEX TREND / MOMENTUM / PULLBACK V2 BACKTEST")
    print("=" * 72)
    print(f"Symbol             : {to_udf_symbol(args.symbol)}")
    print(f"Timeframe          : {args.timeframe}")
    print(f"Entry candles      : {len(entry)}")
    print(f"4H candles         : {len(htf)}")
    print(f"Period             : {ts(entry[0].timestamp)} -> {ts(entry[-1].timestamp)}")
    print(f"Initial equity     : {result.initial_equity:,.2f}")
    print(f"Final equity       : {result.final_equity:,.2f}")
    print(f"Total PnL          : {total_pnl:+,.2f}")
    print(f"Trades             : {len(result.trades)}")
    print(f"Wins               : {wins}")
    print(f"Losses             : {losses}")
    print(f"Win rate           : {(wins / len(result.trades) * 100.0) if result.trades else 0.0:.2f}%")
    print("Execution model    : next-bar open + slippage; stop wins ambiguous bar")
    print("Look-ahead         : BLOCKED by truncated historical views")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
