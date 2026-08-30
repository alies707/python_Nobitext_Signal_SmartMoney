from __future__ import annotations

import argparse
from datetime import datetime, timezone

from config import load_config
from data.historical_data import HistoricalData
from exchange.nobitex_client import NobitexClient, to_udf_symbol
from backtest.validation_v2 import validate_v2


def ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _show(label: str, p) -> None:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Walk-forward-safe preliminary validation for Strategy V2.")
    parser.add_argument("--symbol", default="BTCIRT")
    parser.add_argument("--timeframe", default="1H", choices=["5m", "15m", "1H", "4H"])
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--oos-fraction", type=float, default=0.30)
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
    result = validate_v2(entry, htf, cfg, oos_fraction=args.oos_fraction)
    split = result.split
    cutoff = split.cutoff_timestamp
    print("=" * 72)
    print("NOBITEX STRATEGY V2 - IN-SAMPLE / OUT-OF-SAMPLE VALIDATION")
    print("=" * 72)
    print(f"Symbol             : {to_udf_symbol(args.symbol)}")
    print(f"Timeframe          : {args.timeframe}")
    print(f"Entry candles      : {len(entry)}")
    print(f"OOS fraction       : {args.oos_fraction:.0%}")
    print(f"Cutoff              : {ts(cutoff)}")
    print(f"IS period           : {ts(split.in_sample[0].timestamp)} -> {ts(split.in_sample[-1].timestamp)}")
    print(f"OOS period          : {ts(split.out_of_sample[0].timestamp)} -> {ts(split.out_of_sample[-1].timestamp)}")
    print("Validation policy   : frozen parameters; chronological split; no OOS fitting")
    print("-")
    _show("IN-SAMPLE", result.in_sample_performance)
    print("-")
    _show("OUT-OF-SAMPLE", result.out_of_sample_performance)
    print("-")
    print(f"OOS preliminary verdict : {'PASS' if result.oos_passes_preliminary else 'FAIL'}")
    print("Note: preliminary PASS is not proof of statistical robustness.")
    print("=" * 72)
    return 0 if result.oos_passes_preliminary else 1


if __name__ == "__main__":
    raise SystemExit(main())
