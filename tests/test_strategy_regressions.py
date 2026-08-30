"""Regression tests for the second strategy audit pass."""
from models.setup import LiquidityLevel
from strategy.liquidity import _merge_levels
from strategy.premium_discount import classify_zone
from models.setup import ZoneType


def _level(price, side, score=3):
    return LiquidityLevel(
        price=price,
        level_type=side,
        liquidity_class="EXTERNAL",
        score=score,
        strength=1.0,
        tests=1,
        timeframe="15m",
        created_at=1,
    )


def test_buy_and_sell_liquidity_are_not_merged():
    merged = _merge_levels([_level(100.0, "BUY-SIDE"), _level(100.01, "SELL-SIDE")])
    assert len(merged) == 2


def test_directional_premium_discount_classification():
    assert classify_zone(25, 100, 0) == ZoneType.DISCOUNT
    assert classify_zone(75, 100, 0) == ZoneType.PREMIUM
    assert classify_zone(50, 100, 0) == ZoneType.EQUILIBRIUM
