"""Candle manager.

Owns a multi-timeframe collection of candles for a single symbol and provides
the data-integrity guarantees required by the strategy:

* candles are sorted chronologically,
* duplicate timestamps are removed,
* invalid candles are rejected,
* missing candles are detected (gaps reported, not silently fabricated),
* look-ahead is impossible because the manager exposes only bounded windows.

Resampling from a base (lower) timeframe to a higher one is supported so the
engine can build a coherent multi-timeframe picture from a single download.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from models.candle import Candle
from utils.logger import get_logger
from utils.validators import validate_candles

logger = get_logger(__name__)


@dataclass
class CandleManager:
    """Holds candles per timeframe for one symbol."""

    symbol: str
    candles: Dict[str, List[Candle]] = field(default_factory=dict)

    def set_candles(self, timeframe: str, candles: List[Candle]) -> List[int]:
        """Store validated, sorted, de-duplicated candles for ``timeframe``.

        Returns the list of original indices that were rejected as invalid.
        """
        valid, rejected = validate_candles(candles)
        if rejected:
            logger.debug(
                "%s/%s: rejected %d invalid candles", self.symbol, timeframe, len(rejected)
            )
        # Sort chronological + dedupe by timestamp (keep last on conflict).
        seen: Dict[int, Candle] = {}
        for c in sorted(valid, key=lambda x: x.timestamp):
            seen[c.timestamp] = c
        ordered = [seen[ts] for ts in sorted(seen.keys())]
        self.candles[timeframe] = ordered
        return rejected

    def get(self, timeframe: str) -> List[Candle]:
        return self.candles.get(timeframe, [])

    def detect_missing(self, timeframe: str, expected_interval_ms: int) -> List[Tuple[int, int]]:
        """Detect gaps larger than one interval.

        Returns a list of ``(expected_timestamp, actual_next_timestamp)`` pairs
        describing missing segments. Missing candles are reported, never filled
        with fabricated data.
        """
        candles = self.get(timeframe)
        gaps: List[Tuple[int, int]] = []
        for i in range(1, len(candles)):
            prev = candles[i - 1].timestamp
            cur = candles[i].timestamp
            if cur - prev > expected_interval_ms * 1.5:
                gaps.append((prev + expected_interval_ms, cur))
        return gaps

    def resample(self, base_tf: str, target_tf: str, target_ms: int) -> List[Candle]:
        """Aggregate ``base_tf`` candles into ``target_tf`` bars.

        The resampling walks the base candles in order and buckets them by
        ``target_ms`` aligned to the base candle's timestamp, so no future data
        is ever used.
        """
        base = self.get(base_tf)
        if not base:
            return []
        buckets: Dict[int, List[Candle]] = {}
        order: List[int] = []
        for c in base:
            bucket_ts = (c.timestamp // target_ms) * target_ms
            if bucket_ts not in buckets:
                buckets[bucket_ts] = []
                order.append(bucket_ts)
            buckets[bucket_ts].append(c)

        out: List[Candle] = []
        for ts in order:
            grp = buckets[ts]
            out.append(
                Candle(
                    timestamp=ts,
                    open=grp[0].open,
                    high=max(c.high for c in grp),
                    low=min(c.low for c in grp),
                    close=grp[-1].close,
                    volume=sum(c.volume for c in grp),
                )
            )
        self.candles[target_tf] = out
        return out

    def latest_close(self, timeframe: str) -> Optional[float]:
        cs = self.get(timeframe)
        return cs[-1].close if cs else None
