# Strategy Specification v2.0

## Regime-Adaptive Trend + Breakout + Pullback

Status: research implementation. This specification is the source of truth for the v2 strategy. It is not a claim of profitability.

## 1. Research conclusion

The strategy family selected for this project is trend following / time-series momentum with a Donchian-style breakout, ATR volatility normalization, and a pullback entry. Smart-money concepts are not used as the primary source of edge. Liquidity and SMC-style observations may be logged as secondary context, but they cannot manufacture a trade when the systematic trend/breakout conditions are absent.

The reason is evidence quality. Time-series momentum has been documented across equity-index, currency, commodity, and bond futures, with persistence over several months. Long-horizon historical work also reports positive average returns for trend following across many decades. These results do not prove that the same parameters will work on Nobitex crypto markets, so the strategy must be validated locally with costs and out-of-sample data.

A 2026 BTC study of a Donchian breakout with ATR volatility filtering and ATR risk management reported positive backtest results but also emphasized sensitivity to transaction costs, parameters, and market regime. Therefore this implementation deliberately keeps the rules simple and exposes all parameters for walk-forward testing.

## 2. Strategy objective

Capture medium-term directional moves while avoiding:

- counter-trend entries;
- raw breakout chasing after an already extended move;
- trades in abnormally low or extreme volatility;
- entries without a defined structural stop;
- fixed-position sizing that ignores volatility.

## 3. Timeframes

Recommended initial configuration for Nobitex:

- Higher timeframe: 4H
- Execution timeframe: 15m
- Optional research configuration: 1H / 5m

The higher timeframe is used only from candles that are fully closed at the execution timestamp. No future higher-timeframe candle may be referenced.

## 4. Market regime

Bullish regime:

- HTF close > EMA(200)
- EMA(50) > EMA(200)
- EMA(50) slope is positive over the configured slope window

Bearish regime is the exact inverse.

If neither side qualifies, the strategy does not trade.

## 5. Volatility filter

ATR is calculated with Wilder-style true range smoothing.

A trade is allowed only when:

`min_atr_pct <= ATR / close <= max_atr_pct`

The default research bounds are 0.5% and 8% of price. These are parameters, not sacred constants.

## 6. Breakout event

Long breakout:

`close[t] > highest(high[t-N:t-1])`

Short breakout:

`close[t] < lowest(low[t-N:t-1])`

The current candle is never included in the channel used to define its own breakout.

## 7. Extension protection

A breakout is not immediately bought.

After a breakout, the engine creates a pending setup for a limited number of bars. The market must retrace toward the breakout level or the execution EMA.

This is designed to reduce buying/selling after an already stretched candle.

## 8. Pullback entry

Long:

- a valid bullish regime exists;
- a Donchian breakout occurred recently;
- price retraces into the breakout level or EMA(20) zone;
- the current closed candle closes bullish and above the selected trigger level.

Short is symmetric.

Entry is at the close of the confirmation candle for research/backtest purposes. Live execution must model order latency and slippage separately.

## 9. Structural stop

Long stop:

`min(recent_pullback_low, breakout_level) - ATR * stop_buffer`

Short stop:

`max(recent_pullback_high, breakout_level) + ATR * stop_buffer`

The stop is therefore tied to market structure and volatility rather than a fixed percentage.

## 10. Targets

Primary research target:

- TP1 = 2R
- TP2 = 3R

A later version may replace fixed R targets with confirmed external liquidity targets, but that change must be independently validated. The initial implementation intentionally avoids subjective liquidity selection.

## 11. Position sizing

Risk is expressed as a percentage of equity.

`risk_cash = equity * risk_percent`

`position_size = risk_cash / abs(entry - stop)`

The strategy must never increase size because the signal score is high. Signal quality and risk size are separate concerns.

## 12. Signal quality

The strategy is binary at the execution layer: all mandatory conditions must be satisfied. A diagnostic score may be reported, but it cannot override a failed mandatory condition.

Diagnostic components:

- HTF regime
- breakout quality
- pullback quality
- volatility regime
- reward/risk
- optional volume confirmation

## 13. Invalidation

A pending breakout setup expires when:

- the pullback window expires;
- price closes materially back through the opposite side of the breakout structure;
- the higher-timeframe regime flips;
- the volatility filter becomes invalid before entry.

After entry, normal trade management controls the position.

## 14. No-lookahead requirements

The implementation must satisfy all of the following:

1. Donchian channels exclude the current candle.
2. EMA and ATR use only candles at or before the decision candle.
3. HTF candles must be fully closed before they are used.
4. Entry occurs no earlier than the close of the confirmation candle.
5. Backtest execution must account for fees and slippage.
6. Parameter selection must be separated from the final out-of-sample period.

## 15. Why SMC is secondary

Order blocks, FVGs, liquidity sweeps and MSS are useful descriptive frameworks, but their mechanical definitions vary considerably. The project should not assume that a discretionary SMC label is an established statistical edge. The v2 system therefore uses a measurable trend/momentum core and can log SMC features later as candidate explanatory variables.

## 16. Validation protocol

Before any live use:

1. Test on multiple Nobitex symbols.
2. Include realistic fees and slippage.
3. Separate in-sample and out-of-sample periods.
4. Use walk-forward validation.
5. Run parameter sensitivity tests.
6. Run bootstrap/Monte Carlo trade-order tests.
7. Report Profit Factor, Expectancy, Sharpe, Sortino, Max Drawdown, CAGR, trade count, exposure, average R, and losing streaks.
8. Compare against buy-and-hold and a simple Donchian baseline.
9. Test long and short independently.
10. Reject the strategy if performance depends on a narrow parameter combination or one small historical period.

## 17. Initial parameters

- HTF EMA fast: 50
- HTF EMA slow: 200
- Execution EMA: 20
- Donchian lookback: 20
- Pullback window: 8 bars
- ATR period: 14
- Stop ATR buffer: 0.50
- Minimum ATR percentage: 0.50%
- Maximum ATR percentage: 8.00%
- Minimum reward/risk: 1.80
- Risk per trade: 0.50%

These are starting research parameters. They must not be optimized on the final test set.

## 18. Strategy state machine

`NO_SETUP -> REGIME_CONFIRMED -> BREAKOUT_CONFIRMED -> PULLBACK_PENDING -> ENTRY_TRIGGERED -> TRADE_ACTIVE -> EXITED`

A pending setup may transition to `INVALIDATED` or `EXPIRED`.

## 19. Research hierarchy

The project should prefer, in order:

1. simple rules with broad evidence;
2. causal, deterministic definitions;
3. realistic costs;
4. robust performance across regimes;
5. only then additional SMC or discretionary-style filters.

Complexity is not evidence. More labels on a chart do not magically create alpha.
