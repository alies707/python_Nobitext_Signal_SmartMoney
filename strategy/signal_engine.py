"""Smart Money Signal Engine.

This is the orchestration layer of the strategy. It is intentionally free of any
UI, web, or persistence concerns: it consumes a :class:`CandleManager` and emits
a structured :class:`Signal` (or a ``NONE`` signal when no valid setup exists).

Pipeline (all chronological, no look-ahead):

1. HTF bias from Daily + 4H market structure.
2. Liquidity detection on the entry timeframe (up to the MSS candle).
3. MSS detection (requires sweep + displacement + structure break).
4. FVG detection/ scoring around the MSS.
5. Order Block detection preceding the MSS.
6. Premium / Discount classification of the planned entry.
7. Entry, Stop Loss and Take-Profit (liquidity-based) computation.
8. Risk/Reward validation (>= configured minimum).
9. Smart Money Confidence Score.
10. Signal emission only when every gate passes.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from config import Config
from data.candle_manager import CandleManager
from models.candle import Candle
from models.setup import (
    Bias,
    Direction,
    FVG,
    LiquidityLevel,
    OrderBlock,
    Setup,
    ZoneType,
)
from models.signal import Confidence, Signal
from strategy.displacement import detect_displacement
from strategy.fair_value_gap import FvgContext, find_relevant_fvg
from strategy.liquidity import best_liquidity, detect_liquidity
from strategy.liquidity_sweep import detect_sweep_before
from strategy.market_structure import analyze_structure
from strategy.mss import detect_mss
from strategy.order_block import detect_order_block, fvg_near_ob
from strategy.premium_discount import classify_zone, compute_equilibrium
from strategy.smart_money_score import MAX_SCORE, confidence_from_score, score_setup
from strategy.swing_detection import get_structural_swings
from utils.logger import get_logger

logger = get_logger(__name__)


class SignalEngine:
    def __init__(self, config: Config):
        self.config = config
        self.atr_period = 14
        self.vol_period = 20
        self.mss_lookback = 8
        self.scan_window = 40  # candles scanned for the latest MSS

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #
    def analyze(
        self,
        manager: CandleManager,
        symbol: str,
        entry_tf: Optional[str] = None,
    ) -> Signal:
        entry_tf = entry_tf or self.config.default_timeframe
        return self._build_signal(manager, symbol, entry_tf)

    # ------------------------------------------------------------------ #
    # 1. HTF bias
    # ------------------------------------------------------------------ #
    def _htf_bias(self, manager: CandleManager) -> Tuple[Bias, dict]:
        htf = self.config.htf_timeframes  # ["1D", "4H"]
        trends = {}
        for tf in htf:
            candles = manager.get(tf)
            if len(candles) < 10:
                trends[tf] = "NEUTRAL"
                continue
            highs, lows = get_structural_swings(candles, index=len(candles) - 1)
            # Use last two swing highs/lows for trend.
            if len(highs) >= 2 and len(lows) >= 2:
                hh = highs[-1].price > highs[-2].price
                hl = lows[-1].price > lows[-2].price
                lh = highs[-1].price < highs[-2].price
                ll = lows[-1].price < lows[-2].price
                if hh and hl:
                    trends[tf] = "BULLISH"
                elif lh and ll:
                    trends[tf] = "BEARISH"
                else:
                    trends[tf] = "NEUTRAL"
            else:
                trends[tf] = "NEUTRAL"

        vals = list(trends.values())
        if all(v == "BULLISH" for v in vals):
            return Bias.LONG_BIAS, trends
        if all(v == "BEARISH" for v in vals):
            return Bias.SHORT_BIAS, trends
        return Bias.NO_BIAS, trends

    # ------------------------------------------------------------------ #
    # 2-9. Core analysis
    # ------------------------------------------------------------------ #
    def _analyze_setup(
        self, manager: CandleManager, symbol: str, entry_tf: str, bias: Bias
    ) -> Optional[Setup]:
        candles = manager.get(entry_tf)
        if len(candles) < max(self.atr_period, self.vol_period) + 5:
            logger.debug("%s/%s: insufficient candles for analysis", symbol, entry_tf)
            return None

        if bias == Bias.LONG_BIAS:
            direction = "BULLISH"
        elif bias == Bias.SHORT_BIAS:
            direction = "BEARISH"
        else:
            return None  # Do not force a bias.

        end = len(candles) - 1
        start = max(self.vol_period, end - self.scan_window)

        # Scan backward for the most recent confirmed MSS in the direction.
        mss = None
        for i in range(end, start - 1, -1):
            res = detect_mss(
                candles,
                index=i,
                levels=detect_liquidity(candles, index=i, timeframe=entry_tf),
                atr_period=self.atr_period,
                vol_period=self.vol_period,
                max_gap=self.mss_lookback,
            )
            if res.confirmed and res.direction == direction:
                mss = res
                break
        if mss is None or mss.index is None:
            return None

        mss_index = mss.index
        trade_dir = Direction.LONG if direction == "BULLISH" else Direction.SHORT
        setup = Setup(symbol=symbol, direction=trade_dir, bias=bias)

        # Liquidity known up to the MSS candle.
        levels = detect_liquidity(candles, index=mss_index, timeframe=entry_tf)
        setup.liquidity_levels = levels
        setup.best_liquidity = best_liquidity(levels)
        setup.sweep_confirmed = mss.sweep_index is not None
        setup.sweep_index = mss.sweep_index
        setup.displacement_confirmed = mss.displacement_index is not None
        setup.displacement_index = mss.displacement_index
        setup.mss_confirmed = True
        setup.mss_index = mss_index

        # FVG + OB
        disp = detect_displacement(
            candles, index=mss_index, atr_period=self.atr_period, vol_period=self.vol_period
        )
        ctx = FvgContext(
            mss_confirmed=True,
            displacement_strong=(disp.volume_ratio or 0.0) > 1.5,
        )
        ob = detect_order_block(candles, mss_index, direction, timeframe=entry_tf)
        setup.order_block = ob
        if ob is not None:
            ctx.near_order_block = True
        ctx.htf_aligned = bias != Bias.NO_BIAS

        fvg = find_relevant_fvg(
            candles, mss_index, direction, ctx, timeframe=entry_tf
        )
        setup.fvg = fvg
        if fvg is not None and ob is not None:
            ctx.near_order_block = fvg_near_ob(fvg.lower, fvg.upper, ob)

        # Premium / Discount range from recent swings. The dealing range spans
        # the full set of detected swing extremes (the external range price has
        # been operating within), not just the most recent single swing.
        highs, lows = get_structural_swings(candles, index=mss_index)
        range_high = max((s.price for s in highs), default=candles[mss_index].high)
        range_low = min((s.price for s in lows), default=candles[mss_index].low)

        # Entry zone: prefer FVG + OB overlap.
        entry_zone = self._entry_zone(fvg, ob)
        if entry_zone is None:
            return None
        setup.entry_zone_high, setup.entry_zone_low = entry_zone
        setup.entry = (entry_zone[0] + entry_zone[1]) / 2.0

        zone = classify_zone(setup.entry, range_high, range_low)
        setup.premium_discount_zone = zone
        setup.equilibrium = compute_equilibrium(range_high, range_low)

        # Stop loss.
        stop = self._compute_stop(candles, mss, ob, direction, entry_tf)
        if stop is None:
            return None
        setup.stop_loss = stop

        # Targets from liquidity.
        tp1, tp2, tp3, target_ok = self._select_targets(direction, setup.entry, levels)
        setup.tp1, setup.tp2, setup.tp3 = tp1, tp2, tp3
        setup.liquidity_target = target_ok

        # Risk / Reward.
        rr = self._risk_reward(setup.entry, setup.stop_loss, tp2 or tp1, direction)
        if rr is None:
            return None
        setup.risk_reward = rr

        # Score.
        flags = {
            "HTF Bias": bias != Bias.NO_BIAS,
            "Liquidity": setup.best_liquidity is not None and setup.best_liquidity.score >= 4,
            "Sweep": setup.sweep_confirmed,
            "Displacement": setup.displacement_confirmed,
            "MSS": setup.mss_confirmed,
            "FVG": fvg is not None and fvg.score >= 7,
            "Order Block": ob is not None and ob.fresh and ob.validated,
            "Premium Discount": zone in (ZoneType.DISCOUNT, ZoneType.EQUILIBRIUM),
            "Liquidity Target": target_ok,
        }
        breakdown = score_setup(flags)
        setup.smart_money_score = breakdown.total
        setup.score_breakdown = breakdown.to_dict()

        setup.entry_reason = (
            f"FVG+OB overlap entry at {setup.entry:.2f} "
            f"({zone.value if isinstance(zone, ZoneType) else zone})"
        )

        setup.explanation = self._explain(setup, flags)
        setup.confirmed = (
            setup.smart_money_score >= self.config.min_smart_money_score
            and setup.risk_reward >= self.config.min_risk_reward
        )
        return setup

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _entry_zone(self, fvg: Optional[FVG], ob: Optional[OrderBlock]) -> Optional[Tuple[float, float]]:
        if fvg is None and ob is None:
            return None
        if fvg is not None and ob is not None:
            lo = max(fvg.lower, ob.zone_low)
            hi = min(fvg.upper, ob.zone_high)
            if hi > lo:
                return (lo, hi)
            # No strict overlap: use the nearer of the two zones (prefer FVG).
            return (fvg.lower, fvg.upper)
        if fvg is not None:
            return (fvg.lower, fvg.upper)
        return (ob.zone_low, ob.zone_high)

    def _compute_stop(
        self,
        candles: List[Candle],
        mss,
        ob: Optional[OrderBlock],
        direction: str,
        timeframe: str,
    ) -> Optional[float]:
        from strategy.indicators import compute_atr

        idx = mss.index
        atr = compute_atr(candles, period=self.atr_period, index=idx)
        if atr <= 0:
            return None
        buffer = atr * self.config.atr_multiplier

        sweep_index = mss.sweep_index
        if direction == "BULLISH":
            base = candles[sweep_index].low if sweep_index is not None else None
            if ob is not None:
                base = min(base, ob.zone_low) if base is not None else ob.zone_low
            if base is None:
                return None
            return base - buffer
        else:
            base = candles[sweep_index].high if sweep_index is not None else None
            if ob is not None:
                base = max(base, ob.zone_high) if base is not None else ob.zone_high
            if base is None:
                return None
            return base + buffer

    def _select_targets(
        self, direction: str, entry: float, levels: List[LiquidityLevel]
    ) -> Tuple[Optional[float], Optional[float], Optional[float], bool]:
        if direction == "BULLISH":
            candidates = sorted(
                [l for l in levels if l.level_type == "BUY-SIDE" and l.price > entry],
                key=lambda x: x.price,
            )
        else:
            candidates = sorted(
                [l for l in levels if l.level_type == "SELL-SIDE" and l.price < entry],
                key=lambda x: -x.price,
            )
        if not candidates:
            return None, None, None, False
        tp1 = candidates[0].price
        tp2 = candidates[1].price if len(candidates) > 1 else None
        tp3 = candidates[2].price if len(candidates) > 2 else (tp2 or tp1)
        return tp1, tp2, tp3, tp2 is not None

    def _risk_reward(
        self, entry: float, stop: float, target: Optional[float], direction: str
    ) -> Optional[float]:
        if target is None or entry == stop:
            return None
        risk = abs(entry - stop)
        if risk <= 0:
            return None
        reward = abs(target - entry)
        return reward / risk

    def _explain(self, setup: Setup, flags: dict) -> List[str]:
        out: List[str] = []
        mapping = [
            ("HTF Bias", "Higher Timeframe Bias"),
            ("Liquidity", "Tradable Liquidity Pool"),
            ("Sweep", "Liquidity Sweep"),
            ("Displacement", "Displacement"),
            ("MSS", "Market Structure Shift"),
            ("FVG", "Fair Value Gap"),
            ("Order Block", "Order Block"),
            ("Premium Discount", "Premium/Discount Entry"),
            ("Liquidity Target", "Liquidity Target"),
        ]
        for key, label in mapping:
            mark = "OK" if flags.get(key) else "MISSING"
            out.append(f"[{mark}] {label}")
        return out

    # ------------------------------------------------------------------ #
    # Signal assembly
    # ------------------------------------------------------------------ #
    def _build_signal(self, manager: CandleManager, symbol: str, entry_tf: str) -> Signal:
        bias, trends = self._htf_bias(manager)
        setup = None
        if bias != Bias.NO_BIAS:
            setup = self._analyze_setup(manager, symbol, entry_tf, bias)

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
                risk_reward=0.0,
                smart_money_score=setup.smart_money_score if setup else 0,
                confidence=Confidence.LOW,
                liquidity_target=False,
                setup_explanation=setup.explanation if setup else ["No valid Smart Money setup detected."],
                score_breakdown=setup.score_breakdown if setup else {},
            )

        confidence = confidence_from_score(setup.smart_money_score)
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
            confidence=confidence,
            liquidity_target=setup.liquidity_target,
            setup_explanation=setup.explanation,
            score_breakdown=setup.score_breakdown,
        )


def candles_ts(manager: CandleManager, entry_tf: str) -> float:
    cs = manager.get(entry_tf)
    return cs[-1].timestamp if cs else 0
