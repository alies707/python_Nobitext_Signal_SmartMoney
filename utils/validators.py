"""Data validation utilities.

Centralizes OHLCV validation so that every data source (live API, file, test
fixture) is checked against the same rules before it reaches the strategy.
"""
from __future__ import annotations

from typing import List, Tuple

from models.candle import Candle


class ValidationError(Exception):
    """Raised when a data record fails validation."""


def is_valid_candle(c: Candle) -> bool:
    """Return True when a candle satisfies basic sanity constraints.

    Checks performed:
    * all price fields are finite numbers,
    * high >= low,
    * high >= open and high >= close,
    * low <= open and low <= close,
    * volume is non-negative.
    """
    if c is None:
        return False
    try:
        o, h, l, cl, v = c.open, c.high, c.low, c.close, c.volume
    except (AttributeError, TypeError):
        return False

    if not all(isinstance(x, (int, float)) for x in (o, h, l, cl, v)):
        return False
    if not all(__import__("math").isfinite(x) for x in (o, h, l, cl, v)):
        return False
    if h < l:
        return False
    if h < o or h < cl:
        return False
    if l > o or l > cl:
        return False
    if v < 0:
        return False
    return True


def validate_candle_strict(c: Candle) -> Candle:
    """Validate a candle, raising :class:`ValidationError` on failure."""
    if not is_valid_candle(c):
        raise ValidationError(f"Invalid candle at ts={getattr(c, 'timestamp', '?')}: {c}")
    return c


def validate_candles(candles: List[Candle]) -> Tuple[List[Candle], List[int]]:
    """Validate a list of candles.

    Returns
    -------
    (valid, rejected_indices)
        ``valid`` is the list of candles that passed validation (preserving
        order). ``rejected_indices`` is the list of original indices that were
        rejected.
    """
    valid: List[Candle] = []
    rejected: List[int] = []
    for i, c in enumerate(candles):
        if is_valid_candle(c):
            valid.append(c)
        else:
            rejected.append(i)
    return valid, rejected


def assert_no_look_ahead(current_index: int, reference_index: int, context: str = "") -> None:
    """Guard helper to assert a computation does not use future candles.

    Parameters
    ----------
    current_index:
        Index at which the decision is being made.
    reference_index:
        Index of data being referenced.
    """
    if reference_index > current_index:
        raise ValidationError(
            f"Look-ahead violation in {context}: referenced {reference_index} > current {current_index}"
        )
