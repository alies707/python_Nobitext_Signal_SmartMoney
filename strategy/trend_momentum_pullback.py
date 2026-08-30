"""Regime-adaptive trend + breakout + pullback strategy.

This module provides a deterministic research baseline. All trading decisions
are made from closed candles only. The public ``diagnose`` method exposes every
major decision gate without changing the signal-generation rules, making live
analysis auditable instead of returning an opaque ``None``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from typing import Any, List, Optional, Sequence

from models.candle import Candle


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


class StrategyState(str, Enum):
    NO_SETUP = "NO_SETUP"
    REGIME_CONFIRMED = "REGIME_CONFIRMED"
    BREAKOUT_CONFIRMED = "BREAKOUT_CONFIRMED"
    PULLBACK_PENDING = "PULLBACK_PENDING"
    ENTRY_TRIGGERED = "ENTRY_TRIGGERED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    htf_fast_ema: int = 50
    htf_slow_ema: int = 200
    execution_ema: int = 20
    donchian_period: int = 20
    pullback_window: int = 8
    atr_period: int = 14
    slope_window: int = 5
    stop_atr_buffer: float = 0.50
    min_atr_pct: float = 0.005
    max_atr_pct: float = 0.08
    min_reward_risk: float = 1.80
    tp1_r: float = 2.0
    tp2_r: float = 3.0
    risk_per_trade: float = 0.005
    breakout_zone_atr: float = 0.50
    min_breakout_body_atr: float = 0.30
    require_volume_confirmation: bool = False
    volume_period: int = 20

    def validate(self) -> None:
        periods = (
            self.htf_fast_ema,
            self.htf_slow_ema,
            self.execution_ema,
            self.donchian_period,
            self.pullback_window,
            self.atr_period,
            self.slope_window,
            self.volume_period,
        )
        if any(p < 2 for p in periods):
            raise ValueError("All indicator periods must be at least 2")
        if self.htf_fast_ema >= self.htf_slow_ema:
            raise ValueError("htf_fast_ema must be smaller than htf_slow_ema")
        if not 0 < self.min_atr_pct < self.max_atr_pct:
            raise ValueError("ATR percentage bounds are invalid")
        if self.stop_atr_buffer <= 0:
            raise ValueError("stop_atr_buffer must be positive")
        if self.min_reward_risk <= 0 or self.tp1_r <= 0 or self.tp2_r <= 0:
            raise ValueError("Reward/risk values must be positive")
        if self.tp1_r >= self.tp2_r:
            raise ValueError("tp1_r must be smaller than tp2_r")
        if not 0 < self.risk_per_trade <= 0.05:
            raise ValueError("risk_per_trade must be between 0 and 5 percent")
        if self.breakout_zone_atr <= 0 or self.min_breakout_body_atr < 0:
            raise ValueError("ATR breakout parameters are invalid")


@dataclass(frozen=True, slots=True)
class TrendPullbackSignal:
    direction: Direction
    timestamp: int
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    risk_reward: float
    atr: float
    breakout_level: float
    regime: str
    state: StrategyState
    risk_fraction: float
    position_size: Optional[float]
    explanation: List[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PendingBreakout:
    direction: Direction
    breakout_index: int
    breakout_level: float
    breakout_atr: float


def _ema(values: Sequence[float], period: int) -> List[Optional[float]]:
    if period < 2:
        raise ValueError("EMA period must be at least 2")
    result: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return result
    seed = sum(values[:period]) / period
    result[period - 1] = seed
    alpha = 2.0 / (period + 1.0)
    previous = seed
    for i in range(period, len(values)):
        previous = (values[i] * alpha) + (previous * (1.0 - alpha))
        result[i] = previous
    return result


def _true_ranges(candles: Sequence[Candle]) -> List[float]:
    if not candles:
        return []
    ranges = [candles[0].high - candles[0].low]
    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i - 1]
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return ranges


def _atr(candles: Sequence[Candle], period: int) -> List[Optional[float]]:
    tr = _true_ranges(candles)
    result: List[Optional[float]] = [None] * len(candles)
    if len(tr) < period:
        return result
    value = sum(tr[:period]) / period
    result[period - 1] = value
    for i in range(period, len(tr)):
        value = ((value * (period - 1)) + tr[i]) / period
        result[i] = value
    return result


def _highest(values: Sequence[float], start: int, end: int) -> float:
    if start >= end:
        raise ValueError("highest requires a non-empty range")
    return max(values[start:end])


def _lowest(values: Sequence[float], start: int, end: int) -> float:
    if start >= end:
        raise ValueError("lowest requires a non-empty range")
    return min(values[start:end])


def _htf_regime(htf_candles: Sequence[Candle], config: StrategyConfig) -> str:
    closes = [c.close for c in htf_candles]
    fast = _ema(closes, config.htf_fast_ema)
    slow = _ema(closes, config.htf_slow_ema)
    index = len(htf_candles) - 1
    if index < 0 or fast[index] is None or slow[index] is None:
        return "NEUTRAL"
    if index < config.slope_window or fast[index - config.slope_window] is None:
        return "NEUTRAL"
    fast_now = fast[index]
    slow_now = slow[index]
    fast_old = fast[index - config.slope_window]
    close = closes[index]
    if close > slow_now and fast_now > slow_now and fast_now > fast_old:
        return "BULLISH"
    if close < slow_now and fast_now < slow_now and fast_now < fast_old:
        return "BEARISH"
    return "NEUTRAL"


def _volume_ok(candles: Sequence[Candle], index: int, period: int) -> bool:
    if index < period:
        return False
    current = candles[index].volume
    average = sum(c.volume for c in candles[index - period:index]) / period
    if average <= 0:
        return True
    return current >= average


def _recent_swing_low(candles: Sequence[Candle], start: int, end: int) -> float:
    return min(c.low for c in candles[start:end])


def _recent_swing_high(candles: Sequence[Candle], start: int, end: int) -> float:
    return max(c.high for c in candles[start:end])


class TrendMomentumPullbackStrategy:
    """Generate the most recent deterministic trend-pullback signal."""

    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.config = config or StrategyConfig()
        self.config.validate()

    def generate(
        self,
        candles: Sequence[Candle],
        htf_candles: Sequence[Candle] | None = None,
        equity: float | None = None,
    ) -> Optional[TrendPullbackSignal]:
        diagnostics = self.diagnose(candles, htf_candles)
        if not diagnostics["data"] or not diagnostics["htf_data"]:
            return None
        if not diagnostics["htf_regime_ok"]:
            return None
        if not diagnostics["atr_filter"]:
            return None
        breakout = diagnostics["breakout_candidate"]
        if breakout is None:
            return None
        if not diagnostics["pullback_window"]:
            return None
        return self._confirm_pullback(candles, diagnostics["ema"], diagnostics["atr"], breakout, diagnostics["htf_regime"], equity)

    def diagnose(
        self,
        candles: Sequence[Candle],
        htf_candles: Sequence[Candle] | None = None,
    ) -> dict[str, Any]:
        """Return an auditable snapshot of every major strategy gate.

        The method mirrors ``generate`` but never places an order or mutates
        state. It is intentionally based only on candles supplied to it.
        """
        result: dict[str, Any] = {
            "data": bool(candles),
            "htf_data": bool(htf_candles),
            "htf_regime": "NEUTRAL",
            "htf_regime_ok": False,
            "atr_filter": False,
            "atr_pct": None,
            "breakout_candidate": None,
            "breakout": False,
            "pullback_window": False,
            "pullback_confirmation": False,
            "risk_reward": None,
            "final_signal": False,
            "blocking_reason": "No valid setup detected.",
            "ema": [],
            "atr": [],
        }
        if not candles or not htf_candles:
            result["blocking_reason"] = "Required entry or higher-timeframe data is missing."
            return result
        if any(candles[i].timestamp >= candles[i + 1].timestamp for i in range(len(candles) - 1)):
            raise ValueError("candles must be strictly increasing by timestamp")
        if len(candles) < self._minimum_candles():
            result["blocking_reason"] = "Insufficient entry-timeframe history."
            return result

        regime = _htf_regime(htf_candles, self.config)
        result["htf_regime"] = regime
        result["htf_regime_ok"] = regime != "NEUTRAL"
        if not result["htf_regime_ok"]:
            result["blocking_reason"] = "Higher-timeframe regime is neutral."
            return result

        closes = [c.close for c in candles]
        ema = _ema(closes, self.config.execution_ema)
        atr = _atr(candles, self.config.atr_period)
        result["ema"] = ema
        result["atr"] = atr
        last = len(candles) - 1
        if ema[last] is None or atr[last] is None or candles[last].close <= 0:
            result["blocking_reason"] = "Indicators are not ready."
            return result

        atr_pct = atr[last] / candles[last].close
        result["atr_pct"] = atr_pct
        result["atr_filter"] = self.config.min_atr_pct <= atr_pct <= self.config.max_atr_pct
        if not result["atr_filter"]:
            result["blocking_reason"] = "ATR volatility filter failed."
            return result

        breakout = self._latest_breakout(candles, atr, regime)
        result["breakout_candidate"] = breakout
        result["breakout"] = breakout is not None
        if breakout is None:
            result["blocking_reason"] = "No confirmed breakout in the pullback scan window."
            return result

        result["pullback_window"] = last > breakout.breakout_index and (last - breakout.breakout_index) <= self.config.pullback_window
        if not result["pullback_window"]:
            result["blocking_reason"] = "The latest breakout is outside the pullback window."
            return result

        pullback = self._pullback_status(candles, ema, atr, breakout)
        result["pullback_confirmation"] = pullback["confirmed"]
        result["risk_reward"] = pullback["risk_reward"]
        result["final_signal"] = pullback["confirmed"] and (pullback["risk_reward"] is not None and pullback["risk_reward"] >= self.config.min_reward_risk)
        if result["final_signal"]:
            result["blocking_reason"] = ""
        elif not pullback["confirmed"]:
            result["blocking_reason"] = pullback["reason"]
        else:
            result["blocking_reason"] = "Risk/reward is below the configured minimum."
        return result

    def _minimum_candles(self) -> int:
        return max(
            self.config.donchian_period + 2,
            self.config.execution_ema + 2,
            self.config.atr_period + 2,
            self.config.volume_period + 2 if self.config.require_volume_confirmation else 0,
        )

    def _latest_breakout(
        self,
        candles: Sequence[Candle],
        atr: Sequence[Optional[float]],
        regime: str,
    ) -> Optional[PendingBreakout]:
        last = len(candles) - 1
        earliest = max(
            self.config.donchian_period,
            self.config.atr_period,
            self.config.execution_ema,
        )
        start = max(earliest, last - self.config.pullback_window)
        for i in range(last, start - 1, -1):
            if i <= self.config.donchian_period or atr[i] is None:
                continue
            previous_high = _highest([c.high for c in candles], i - self.config.donchian_period, i)
            previous_low = _lowest([c.low for c in candles], i - self.config.donchian_period, i)
            candle = candles[i]
            body = candle.body
            if regime == "BULLISH" and candle.close > previous_high:
                if body >= atr[i] * self.config.min_breakout_body_atr:
                    if not self.config.require_volume_confirmation or _volume_ok(candles, i, self.config.volume_period):
                        return PendingBreakout(Direction.LONG, i, previous_high, atr[i])
            if regime == "BEARISH" and candle.close < previous_low:
                if body >= atr[i] * self.config.min_breakout_body_atr:
                    if not self.config.require_volume_confirmation or _volume_ok(candles, i, self.config.volume_period):
                        return PendingBreakout(Direction.SHORT, i, previous_low, atr[i])
        return None

    def _pullback_status(
        self,
        candles: Sequence[Candle],
        ema: Sequence[Optional[float]],
        atr: Sequence[Optional[float]],
        breakout: PendingBreakout,
    ) -> dict[str, Any]:
        last = len(candles) - 1
        candle = candles[last]
        atr_now = atr[last]
        ema_now = ema[last]
        if atr_now is None or ema_now is None:
            return {"confirmed": False, "risk_reward": None, "reason": "Indicators are not ready."}
        zone = self.config.breakout_zone_atr * atr_now
        touched = candles[breakout.breakout_index + 1:last + 1]
        if not touched:
            return {"confirmed": False, "risk_reward": None, "reason": "No post-breakout pullback candle exists yet."}
        if breakout.direction == Direction.LONG:
            pullback_low = min(c.low for c in touched)
            level_touched = pullback_low <= breakout.breakout_level + zone
            resumed = candle.close > candle.open and candle.close > breakout.breakout_level
            ema_support = candle.low <= ema_now + zone and candle.close > ema_now
            confirmed = level_touched and (resumed or ema_support)
            if not confirmed:
                return {"confirmed": False, "risk_reward": None, "reason": "Pullback has not produced a bullish confirmation."}
            stop_reference = min(_recent_swing_low(candles, breakout.breakout_index, last + 1), breakout.breakout_level)
            stop = stop_reference - (atr_now * self.config.stop_atr_buffer)
            risk = candle.close - stop
            if risk <= 0:
                return {"confirmed": False, "risk_reward": None, "reason": "Stop-loss geometry is invalid."}
            rr = self.config.tp1_r
        else:
            pullback_high = max(c.high for c in touched)
            level_touched = pullback_high >= breakout.breakout_level - zone
            resumed = candle.close < candle.open and candle.close < breakout.breakout_level
            ema_resistance = candle.high >= ema_now - zone and candle.close < ema_now
            confirmed = level_touched and (resumed or ema_resistance)
            if not confirmed:
                return {"confirmed": False, "risk_reward": None, "reason": "Pullback has not produced a bearish confirmation."}
            stop_reference = max(_recent_swing_high(candles, breakout.breakout_index, last + 1), breakout.breakout_level)
            stop = stop_reference + (atr_now * self.config.stop_atr_buffer)
            risk = stop - candle.close
            if risk <= 0:
                return {"confirmed": False, "risk_reward": None, "reason": "Stop-loss geometry is invalid."}
            rr = self.config.tp1_r
        return {"confirmed": True, "risk_reward": rr, "reason": ""}

    def _confirm_pullback(
        self,
        candles: Sequence[Candle],
        ema: Sequence[Optional[float]],
        atr: Sequence[Optional[float]],
        breakout: PendingBreakout,
        regime: str,
        equity: float | None,
    ) -> Optional[TrendPullbackSignal]:
        last = len(candles) - 1
        candle = candles[last]
        atr_now = atr[last]
        ema_now = ema[last]
        if atr_now is None or ema_now is None:
            return None

        zone = self.config.breakout_zone_atr * atr_now
        if breakout.direction == Direction.LONG:
            touched = candles[breakout.breakout_index + 1:last + 1]
            if not touched:
                return None
            pullback_low = min(c.low for c in touched)
            level_touched = pullback_low <= breakout.breakout_level + zone
            resumed = candle.close > candle.open and candle.close > breakout.breakout_level
            ema_support = candle.low <= ema_now + zone and candle.close > ema_now
            if not level_touched or not (resumed or ema_support):
                return None
            stop_reference = min(_recent_swing_low(candles, breakout.breakout_index, last + 1), breakout.breakout_level)
            stop = stop_reference - (atr_now * self.config.stop_atr_buffer)
            risk = candle.close - stop
            if risk <= 0:
                return None
            tp1 = candle.close + (risk * self.config.tp1_r)
            tp2 = candle.close + (risk * self.config.tp2_r)
            rr = (tp1 - candle.close) / risk
            explanation = [
                "Bullish HTF regime confirmed",
                "Donchian upside breakout confirmed on a closed candle",
                "Price retraced toward the breakout level or execution EMA",
                "Bullish pullback confirmation closed above the breakout structure",
                "Stop uses recent pullback structure plus ATR buffer",
            ]
        else:
            touched = candles[breakout.breakout_index + 1:last + 1]
            if not touched:
                return None
            pullback_high = max(c.high for c in touched)
            level_touched = pullback_high >= breakout.breakout_level - zone
            resumed = candle.close < candle.open and candle.close < breakout.breakout_level
            ema_resistance = candle.high >= ema_now - zone and candle.close < ema_now
            if not level_touched or not (resumed or ema_resistance):
                return None
            stop_reference = max(_recent_swing_high(candles, breakout.breakout_index, last + 1), breakout.breakout_level)
            stop = stop_reference + (atr_now * self.config.stop_atr_buffer)
            risk = stop - candle.close
            if risk <= 0:
                return None
            tp1 = candle.close - (risk * self.config.tp1_r)
            tp2 = candle.close - (risk * self.config.tp2_r)
            rr = (candle.close - tp1) / risk
            explanation = [
                "Bearish HTF regime confirmed",
                "Donchian downside breakout confirmed on a closed candle",
                "Price retraced toward the breakout level or execution EMA",
                "Bearish pullback confirmation closed below the breakout structure",
                "Stop uses recent pullback structure plus ATR buffer",
            ]

        if rr < self.config.min_reward_risk:
            return None
        size = None
        if equity is not None:
            if not isfinite(equity) or equity <= 0:
                raise ValueError("equity must be a positive finite number")
            risk_cash = equity * self.config.risk_per_trade
            size = risk_cash / abs(candle.close - stop)

        return TrendPullbackSignal(
            direction=breakout.direction,
            timestamp=candle.timestamp,
            entry=candle.close,
            stop_loss=stop,
            tp1=tp1,
            tp2=tp2,
            risk_reward=rr,
            atr=atr_now,
            breakout_level=breakout.breakout_level,
            regime=regime,
            state=StrategyState.ENTRY_TRIGGERED,
            risk_fraction=self.config.risk_per_trade,
            position_size=size,
            explanation=explanation,
        )
