from __future__ import annotations

import argparse
from datetime import datetime, timezone

from backtest.validation_v2 import robust_validate_v2
from config import load_config
from data.historical_data import HistoricalData
from exchange.nobitex_client import NobitexClient, to_udf_symbol


def ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _show(label: str, p, fold=None) -> None:
    print(f"[{label}]")
    print(f"Trades             : {p.total_trades}")
    print(f"Wins / Losses      : {p.wins} / {p.losses}")
    print(f"Win rate           : {p.win_rate_pct:.2f}%")
    print(f"Profit factor      : {p.profit_factor:.3f}")
    print(f"Average R          : {p.average_r:+.3f}R")
    print(f"Expectancy         : {p.expectancy_r:+.3f}R")
    print(f"Return             : {p.total_return_pct:+.3f}%")
    print(f"Max drawdown       : {p.max_drawdown_pct:.3f}%")
    print(f"Max loss streak    : {p.max_consecutive_losses}")
    print(f"Max win streak     : {p.max_consecutive_wins}")
    print(f"LONG               : {p.long.trades} trades | {p.long.win_rate_pct:.2f}% win | PF {p.long.profit_factor:.3f}")
    print(f"SHORT              : {p.short.trades} trades | {p.short.win_rate_pct:.2f}% win | PF {p.short.profit_factor:.3f}")
    if fold is not None:
        print(f"OOS PF retention   : {fold.oos_pf_retention_pct:.2f}% of IS PF")


def main() -> int:
    parser = argparse.ArgumentParser(description="Robust time-series validation for Strategy V2.")
    parser.add_argument("--symbol", default="BTCIRT")
    parser.add_argument("--timeframe", default="1H", choices=["5m", "15m", "1H", "4H"])
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--folds", type=int, default=3)
    parser.add_argument("--oos-fraction", type=float, default=0.20)
    parser.add_argument("--min-trades-per-fold", type=int, default=20)
    args = parser.parse_args()
    if args.limit < 250:
        raise SystemExit("--limit must be at least 250")

    cfg = load_config()
    client = NobitexClient(api_key=cfg.nobitex_api_key, api_url=cfg.nobitex_api_url)
    if not client.health_check():
        print("ERROR: Nobitex API unavailable")
        return 2

    manager = HistoricalData(client).download(
        to_udf_symbol(args.symbol), ["4H", args.timeframe], args.limit, use_cache=False
    )
    entry = manager.get(args.timeframe)
    htf = manager.get("4H")
    if len(entry) < 250 or len(htf) < 2:
        print(f"ERROR: insufficient data entry={len(entry)} 4H={len(htf)}")
        return 3

    result = robust_validate_v2(
        entry,
        htf,
        cfg,
        n_folds=args.folds,
        oos_fraction=args.oos_fraction,
        min_trades_per_fold=args.min_trades_per_fold,
    )

    print("=" * 72)
    print("NOBITEX STRATEGY V2 - ROBUST TIME-SERIES VALIDATION")
    print("=" * 72)
    print(f"Symbol             : {to_udf_symbol(args.symbol)}")
    print(f"Timeframe          : {args.timeframe}")
    print(f"Entry candles      : {len(entry)}")
    print(f"Folds              : {len(result.folds)}")
    print(f"OOS fraction/fold  : {args.oos_fraction:.0%}")
    print(f"Min trades/fold    : {args.min_trades_per_fold}")
    print("Validation policy  : frozen parameters; expanding chronological OOS; no tuning")
    print("OOS account policy : equity is carried forward between contiguous folds")
    print("-" * 72)

    for fold in result.folds:
        print(f"[FOLD {fold.fold_id}]")
        print(f"IS period          : {ts(fold.split.in_sample[0].timestamp)} -> {ts(fold.split.in_sample[-1].timestamp)}")
        print(f"OOS period         : {ts(fold.split.out_of_sample[0].timestamp)} -> {ts(fold.split.out_of_sample[-1].timestamp)}")
        _show("IN-SAMPLE", fold.in_sample_performance)
        _show("OUT-OF-SAMPLE", fold.out_of_sample_performance, fold)
        print(f"Sample status      : {fold.sample_status(result.min_trades_per_fold)}")
        print(f"Performance status : {fold.performance_status(result.min_trades_per_fold)}")
        print("-" * 72)

    print("[ROBUSTNESS SUMMARY]")
    print(f"OOS total trades   : {result.total_oos_trades}")
    print(f"Sufficient folds    : {result.folds_with_sufficient_sample}/{len(result.folds)}")
    print(f"Inconclusive folds  : {result.inconclusive_folds}/{len(result.folds)}")
    print(f"Performance fails   : {result.performance_failures}/{len(result.folds)}")
    print(f"Positive OOS folds : {result.positive_oos_folds}/{len(result.folds)}")
    print(f"Median OOS PF      : {result.median_oos_profit_factor:.3f}")
    print(f"Median PF retention: {result.median_pf_retention_pct:.2f}%")
    print(f"Worst OOS PF       : {result.worst_oos_profit_factor:.3f}")
    print(f"OOS initial equity : {result.oos_initial_equity:,.2f}")
    print(f"OOS final equity   : {result.oos_final_equity:,.2f}")
    print(f"Aggregate OOS PnL  : {result.aggregate_oos_pnl:+,.2f}")
    print(f"Aggregate OOS ret. : {result.aggregate_oos_return_pct:+.3f}%")
    print(f"Robustness verdict : {'PASS' if result.passes_preliminary_robustness else 'FAIL'}")
    print("Note: PASS is a research gate only and is not proof of future profitability.")
    print("=" * 72)
    return 0 if result.passes_preliminary_robustness else 1


if __name__ == "__main__":
    raise SystemExit(main())
