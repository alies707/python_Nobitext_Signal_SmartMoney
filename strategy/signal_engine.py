"""Smart Money Signal Engine."""
from __future__ import annotations

from typing import List, Optional, Tuple

from config import Config
from data.candle_manager import CandleManager
from models.candle import Candle
from models.setup import Bias, Direction, FVG, LiquidityLevel, OrderBlock, Setup, ZoneType
from models.signal import Confidence, Signal
from strategy.displacement import detect_displacement
from strategy.fair_value_gap import FvgContext, find_relevant_fvg, score_fvg
from strategy.liquidity import best_liquidity, detect_liquidity
from strategy.mss import detect_mss
from strategy.order_block import detect_order_block, fvg_near_ob
from strategy.premium_discount import classify_zone, compute_equilibrium
from strategy.smart_money_score import confidence_from_score, score_setup
from strategy.swing_detection import get_structural_swings
from utils.logger import get_logger

logger = get_logger(__name__)


class SignalEngine:
    def __init__(self, config: Config):
        self.config = config
        self.atr_period = 14
        self.vol_period = 20
        self.mss_lookback = 8
        self.scan_window = 40

    def analyze(self, manager: CandleManager, symbol: str, entry_tf: Optional[str] = None) -> Signal:
        entry_tf = entry_tf or self.config.default_timeframe
        return self._build_signal(manager, symbol, entry_tf)

    def _htf_bias(self, manager: CandleManager) -> Tuple[Bias, dict]:
        trends = {}
        for tf in self.config.htf_timeframes:
            candles = manager.get(tf)
            if len(candles) < 10:
                trends[tf] = "NEUTRAL"
                continue
            highs, lows = get_structural_swings(candles, index=len(candles) - 1)
            if len(highs) < 2 or len(lows) < 2:
                trends[tf] = "NEUTRAL"
                continue
            hh = highs[-1].price > highs[-2].price
            hl = lows[-1].price > lows[-2].price
            lh = highs[-1].price < highs[-2].price
            ll = lows[-1].price < lows[-2].price
            trends[tf] = "BULLISH" if hh and hl else "BEARISH" if lh and ll else "NEUTRAL"

        values = list(trends.values())
        if values and all(v == "BULLISH" for v in values):
            return Bias.LONG_BIAS, trends
        if values and all(v == "BEARISH" for v in values):
            return Bias.SHORT_BIAS, trends
        return Bias.NO_BIAS, trends

    def _dealing_range(self, candles: List[Candle], index: int) -> Optional[Tuple[float, float]]:
        """Use the latest confirmed external swing pair, not all-time extremes."""
        highs, lows = get_structural_swings(candles, index=index, left=2, right=2)
        if not highs or not lows:
            return None
        high = highs[-1]
        low = lows[-1]
        if high.price <= low.price:
            return None
        return low.price, high.price

    def _analyze_setup(self, manager: CandleManager, symbol: str, entry_tf: str, bias: Bias) -> Optional[Setup]:
        candles = manager.get(entry_tf)
        if len(candles) < max(self.atr_period, self.vol_period) + 5:
            return None
        direction = "BULLISH" if bias == Bias.LONG_BIAS else "BEARISH" if bias == Bias.SHORT_BIAS else None
        if direction is None:
            return None

        end = len(candles) - 1
        start = max(self.vol_period, end - self.scan_window)
        mss = None
        for i in range(end, start - 1, -1):
            result = detect_mss(
                candles,
                index=i,
                levels=detect_liquidity(candles, index=i, timeframe=entry_tf),
                atr_period=self.atr_period,
                vol_period=self.vol_period,
                max_gap=self.mss_lookback,
            )
            if result.confirmed and result.direction == direction:
                mss = result
                break
        if mss is None or mss.index is None:
            return None

        mss_index = mss.index
        trade_dir = Direction.LONG if direction == "BULLISH" else Direction.SHORT
        setup = Setup(symbol=symbol, direction=trade_dir, bias=bias)
        levels = detect_liquidity(candles, index=mss_index, timeframe=entry_tf)
        target_side = "BUY-SIDE" if direction == "BULLISH" else "SELL-SIDE"
        setup.liquidity_levels = levels
        setup.best_liquidity = best_liquidity(levels, side=target_side)
        setup.sweep_confirmed = mss.sweep_index is not None
        setup.sweep_index = mss.sweep_index
        setup.displacement_confirmed = mss.displacement_index is not None
        setup.displacement_index = mss.displacement_index
        setup.mss_confirmed = True
        setup.mss_index = mss_index

        disp = detect_displacement(candles, index=mss_index, atr_period=self.atr_period, vol_period=self.vol_period)
        ctx = FvgContext(
            mss_confirmed=True,
            displacement_strong=(disp.volume_ratio or 0.0) > 1.5,
            near_order_block=False,
            htf_aligned=bias != Bias.NO_BIAS,
        )
        ob = detect_order_block(candles, mss_index, direction, timeframe=entry_tf)
        setup.order_block = ob
        fvg = find_relevant_fvg(candles, mss_index, direction, ctx, timeframe=entry_tf)
        if fvg is None or ob is None:
            return None

        overlap = fvg_near_ob(fvg.lower, fvg.upper, ob)
        if not overlap:
            return None
        ctx.near_order_block = True
        score_fvg(fvg, ctx)
        if fvg.score < 7 or fvg.mitigated:
            return None
        setup.fvg = fvg

        dealing_range = self._dealing_range(candles, mss_index)
        if dealing_range is None:
            return None
        range_low, range_high = dealing_range

        entry_zone = self._entry_zone(fvg, ob)
        if entry_zone is None:
            return None
        setup.entry_zone_high, setup.entry_zone_low = entry_zone
        setup.entry = (entry_zone[0] + entry_zone[1]) / 2.0

        zone = classify_zone(setup.entry, range_high, range_low)
        setup.premium_discount_zone = zone
        setup.equilibrium = compute_equilibrium(range_high, range_low)

        stop = self._compute_stop(candles, mss, ob, direction)
        if stop is None:
            return None
        setup.stop_loss = stop

        tp1, tp2, tp3, target_ok = self._select_targets(direction, setup.entry, levels)
        setup.tp1, setup.tp2, setup.tp3 = tp1, tp2, tp3
        setup.liquidity_target = target_ok
        rr = self._risk_reward(setup.entry, setup.stop_loss, tp2 or tp1)
        if rr is None:
            return None
        setup.risk_reward = rr

        pd_favorable = (
            zone in (ZoneType.DISCOUNT, ZoneType.EQUILIBRIUM)
            if direction == "BULLISH"
            else zone in (ZoneType.PREMIUM, ZoneType.EQUILIBRIUM)
        )
        flags = {
            "HTF Bias": bias != Bias.NO_BIAS,
            "Liquidity": setup.best_liquidity is not None and setup.best_liquidity.score >= 4,
            "Sweep": setup.sweep_confirmed,
            "Displacement": setup.displacement_confirmed,
            "MSS": setup.mss_confirmed,
            "FVG": fvg.score >= 7,
            "Order Block": ob.fresh and ob.validated,
            "Premium Discount": pd_favorable,
            "Liquidity Target": target_ok,
        }
        breakdown = score_setup(flags)
        setup.smart_money_score = breakdown.total
        setup.score_breakdown = breakdown.to_dict()
        setup.entry_reason = f"Validated FVG+OB overlap at {setup.entry:.2f} ({zone.value})"
        setup.explanation = self._explain(setup, flags)
        setup.confirmed = (
            setup.smart_money_score >= self.config.min_smart_money_score
            and setup.risk_reward >= self.config.min_risk_reward
            and target_ok
            and pd_favorable
        )
        return setup

    def _entry_zone(self, fvg: Optional[FVG], ob: Optional[OrderBlock]) -> Optional[Tuple[float, float]]:
        if fvg is None or ob is None:
            return None
        low = max(fvg.lower, ob.zone_low)
        high = min(fvg.upper, ob.zone_high)
        if high < low:
            return None
        return low, high

    def _compute_stop(self, candles: List[Candle], mss, ob: Optional[OrderBlock], direction: str) -> Optional[float]:
        from strategy.indicators import compute_atr
        idx = mss.index
        atr = compute_atr(candles, period=self.atr_period, index=idx)
        if atr <= 0:
            return None
        buffer = atr * self.config.atr_multiplier
        sweep_index = mss.sweep_index
        if sweep_index is None:
            return None
        if direction == "BULLISH":
            base = candles[sweep_index].low
            if ob is not None:
                base = min(base, ob.zone_low)
            return base - buffer
        base = candles[sweep_index].high
        if ob is not None:
            base = max(base, ob.zone_high)
        return base + buffer

    def _select_targets(self, direction: str, entry: float, levels: List[LiquidityLevel]):
        side = "BUY-SIDE" if direction == "BULLISH" else "SELL-SIDE"
        candidates = [l for l in levels if l.level_type == side and (l.price > entry if direction == "BULLISH" else l.price < entry)]
        candidates.sort(key=lambda x: x.price, reverse=direction != "BULLISH")
        if not candidates:
            return None, None, None, False
        tp1 = candidates[0].price
        tp2 = candidates[1].price if len(candidates) > 1 else None
        tp3 = candidates[2].price if len(candidates) > 2 else (tp2 or tp1)
        return tp1, tp2, tp3, tp2 is not None

    def _risk_reward(self, entry: float, stop: float, target: Optional[float]) -> Optional[float]:
        if target is None:
            return None
        risk = abs(entry - stop)
        reward = abs(target - entry)
        return reward / risk if risk > 0 else None

    def _explain(self, setup: Setup, flags: dict) -> List[str]:
        labels = [
            ("HTF Bias", "Higher Timeframe Bias"),
            ("Liquidity", "Directional Liquidity Pool"),
            ("Sweep", "Liquidity Sweep"),
            ("Displacement", "Displacement"),
            ("MSS", "Internal Market Structure Shift"),
            ("FVG", "Fair Value Gap"),
            ("Order Block", "Validated Order Block"),
            ("Premium Discount", "Directional Premium/Discount"),
            ("Liquidity Target", "Directional Liquidity Target"),
        ]
        return [f"[{'OK' if flags.get(key) else 'MISSING'}] {label}" for key, label in labels]

    def _build_signal(self, manager: CandleManager, symbol: str, entry_tf: str) -> Signal:
        bias, _ = self._htf_bias(manager)
        setup = self._analyze_setup(manager, symbol, entry_tf, bias) if bias != Bias.NO_BIAS else None
        if setup is None or not setup.confirmed:
            return Signal(
                symbol=symbol,
                direction=Direction.NONE,
                timestamp=int(candles_ts(manager, entry_tf)),
                timeframe=entry_tf,
                htf_bias=bias,
                entry=None,
                entry_zone_high=None,
                entry_zone_low=None,
                stop_loss=None,
                tp1=None,
                tp2=None,
                tp3=None,
                risk_reward=setup.risk_reward if setup else 0.0,
                smart_money_score=setup.smart_money_score if setup else 0,
                confidence=confidence_from_score(setup.smart_money_score if setup else 0),
                liquidity_target=setup.liquidity_target if setup else False,
                setup_explanation=setup.explanation if setup else ["No valid Smart Money setup detected."],
                score_breakdown=setup.score_breakdown if setup else {},
            )
        return Signal(
            symbol=symbol,
            direction=setup.direction,
            timestamp=int(manager.get(entry_tf)[-1].timestamp),
            timeframe=entry_tf,
            htf_bias=bias,
            entry=setup.entry,
            entry_zone_high=setup.entry_zone_high,
            entry_zone_low=setup.entry_zone_low,
            stop_loss=setup.stop_loss,
            tp1=setup.tp1,
            tp2=setup.tp2,
            tp3=setup.tp3,
            risk_reward=setup.risk_reward,
            smart_money_score=setup.smart_money_score,
            confidence=confidence_from_score(setup.smart_money_score),
            liquidity_target=setup.liquidity_target,
            setup_explanation=setup.explanation,
            score_breakdown=setup.score_breakdown,
        )


def candles_ts(manager: CandleManager, entry_tf: str) -> float:
    candles = manager.get(entry_tf)
    return candles[-1].timestamp if candles else 0
