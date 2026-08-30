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


def _performance(trades, initial_equity: float) -> dict:
    if not trades:
        return {
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "average_r": 0.0,
            "total_pnl": 0.0,
            "return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "long_trades": 0,
            "short_trades": 0,
        }

    wins = [t for t in trades if t.result == "WIN"]
    losses = [t for t in trades if t.result == "LOSS"]
    gross_profit = sum(t.realized_pnl for t in wins)
    gross_loss = abs(sum(t.realized_pnl for t in losses))
    total_pnl = sum(t.realized_pnl for t in trades)

    equity = initial_equity
    peak = initial_equity
    max_dd = 0.0
    for trade in trades:
        equity += trade.realized_pnl
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100.0)

    r_values = [t.r_multiple for t in trades]
    return {
        "win_rate": len(wins) / len(trades) * 100.0,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else float("inf"),
        "average_r": sum(r_values) / len(r_values) if r_values else 0.0,
        "total_pnl": total_pnl,
        "return_pct": total_pnl / initial_equity * 100.0 if initial_equity > 0 else 0.0,
        "max_drawdown_pct": max_dd,
        "long_trades": sum(1 for t in trades if t.direction.value == "LONG"),
        "short_trades": sum(1 for t in trades if t.direction.value == "SHORT"),
    }


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

    perf = _performance(result.trades, result.initial_equity)
    wins = sum(1 for t in result.trades if t.result == "WIN")
    losses = sum(1 for t in result.trades if t.result == "LOSS")
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
    print(f"Total PnL          : {perf['total_pnl']:+,.2f}")
    print(f"Total return       : {perf['return_pct']:+.3f}%")
    print(f"Trades             : {len(result.trades)}")
    print(f"Wins               : {wins}")
    print(f"Losses             : {losses}")
    print(f"Win rate           : {perf['win_rate']:.2f}%")
    print(f"Profit factor      : {perf['profit_factor']:.3f}")
    print(f"Average R          : {perf['average_r']:+.3f}R")
    print(f"Max drawdown       : {perf['max_drawdown_pct']:.3f}%")
    print(f"LONG / SHORT       : {perf['long_trades']} / {perf['short_trades']}")
    print(f"Sample assessment  : {'SUFFICIENT FOR PRELIMINARY TEST' if len(result.trades) >= 30 and coverage_days >= 90 else 'INSUFFICIENT FOR STRATEGY VALIDATION'}")
    print("Execution model    : next-bar open + slippage; stop wins ambiguous bar")
    print("Look-ahead         : BLOCKED; completed HTF candles only")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
