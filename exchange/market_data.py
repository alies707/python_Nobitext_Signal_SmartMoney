"""Market data layer built on top of :class:`NobitexClient`.

Responsibilities:
* rank available markets using a transparent, weighted scoring model,
* select the top N tradable markets,
* provide a clean snapshot of a market (price, spread, liquidity, activity),
* assemble the data required by the strategy engine.

All heavy lifting / IO lives in :class:`NobitexClient`; this module only
orchestrates and scores.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from exchange.nobitex_client import NobitexClient
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MarketSnapshot:
    """A normalized view of a single market used for ranking."""

    symbol: str
    last_price: float = 0.0
    volume_24h: float = 0.0
    best_bid: float = 0.0
    best_ask: float = 0.0
    spread: float = 0.0
    bid_depth: float = 0.0
    ask_depth: float = 0.0
    trade_count: int = 0

    @property
    def mid_price(self) -> float:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return self.last_price

    @property
    def spread_pct(self) -> float:
        if self.mid_price <= 0:
            return 0.0
        return (self.spread / self.mid_price) * 100.0


@dataclass
class RankedMarket:
    snapshot: MarketSnapshot
    volume_score: float = 0.0
    liquidity_score: float = 0.0
    spread_score: float = 0.0
    activity_score: float = 0.0
    total_score: float = 0.0


class MarketDataProvider:
    """Retrieves and ranks markets from Nobitex."""

    def __init__(self, client: NobitexClient, config=None):
        self.client = client
        self.config = config

    # ------------------------------------------------------------------ #
    # Snapshot building
    # ------------------------------------------------------------------ #
    def build_snapshot(self, symbol: str, stats: Dict[str, dict]) -> Optional[MarketSnapshot]:
        """Build a :class:`MarketSnapshot` for ``symbol`` using stats + book."""
        raw = stats.get(symbol)
        if not raw:
            return None
        # Closed / delisted markets cannot be traded; skip them entirely so we
        # don't waste order-book / trades requests (which would 400 anyway).
        if raw.get("isClosed"):
            return None
        try:
            # v2 stats: price lives in `latest` (string); 24h volume in
            # `volumeDst` (quote currency) with `volumeSrc` as a fallback.
            last = float(raw.get("latest") or raw.get("price") or 0.0)
            vol = float(
                raw.get("volumeDst")
                or raw.get("volumeSrc")
                or raw.get("volume")
                or raw.get("vol")
                or 0.0
            )
        except (TypeError, ValueError):
            return None

        snap = MarketSnapshot(symbol=symbol, last_price=last, volume_24h=vol)

        # A market whose order book cannot be fetched (e.g. an invalid/legacy
        # symbol) is not tradable through the v2 endpoints; skip it.
        book = self.client.get_order_book(symbol, depth=20)
        if not book:
            return None
        try:
            bids = [(float(p), float(q)) for p, q in book.get("bids", [])]
            asks = [(float(p), float(q)) for p, q in book.get("asks", [])]
            if bids:
                snap.best_bid = bids[0][0]
                snap.bid_depth = sum(q for _, q in bids)
            if asks:
                snap.best_ask = asks[0][0]
                snap.ask_depth = sum(q for _, q in asks)
            if snap.best_bid and snap.best_ask:
                snap.spread = snap.best_ask - snap.best_bid
        except (TypeError, ValueError) as exc:
            logger.warning("Malformed order book for %s: %s", symbol, exc)
            return None

        trades = self.client.get_recent_trades(symbol, limit=50)
        snap.trade_count = len(trades) if trades else 0
        return snap

    # ------------------------------------------------------------------ #
    # Ranking
    # ------------------------------------------------------------------ #
    def rank_markets(self, top_n: int = 10, candidate_pool: int = 60) -> List[RankedMarket]:
        """Rank available markets and return the top ``top_n``.

        Scoring weights (from the spec):
        * 24h Volume      -> 40%
        * Liquidity       -> 30%
        * Spread Quality  -> 20%
        * Market Activity -> 10%

        Scores are min-max normalized across the candidate universe so that the
        weights are applied to a 0..1 scale.

        To stay within the public API rate limits, the full universe is first
        narrowed to the ``candidate_pool`` highest-volume *tradable* markets
        (open, with a last price and 24h volume); order-book / trade snapshots
        are only built for those candidates before the weighted scoring runs.
        """
        stats = self.client.get_market_stats()
        if not stats:
            logger.error("No market stats available; cannot rank markets")
            return []

        # Pre-filter to tradable markets and rank by 24h volume to bound the
        # number of (rate-limited) order-book / trade calls we make.
        tradable = []
        for symbol, raw in stats.items():
            if raw.get("isClosed"):
                continue
            try:
                last = float(raw.get("latest") or 0.0)
                vol = float(raw.get("volumeDst") or raw.get("volumeSrc") or 0.0)
            except (TypeError, ValueError):
                continue
            if last > 0 and vol > 0:
                tradable.append((symbol, vol))
        if not tradable:
            return []
        tradable.sort(key=lambda x: x[1], reverse=True)
        candidates = [s for s, _ in tradable[: max(candidate_pool, top_n)]]

        snapshots: List[MarketSnapshot] = []
        for symbol in candidates:
            snap = self.build_snapshot(symbol, stats)
            if snap and snap.last_price > 0 and snap.volume_24h > 0:
                snapshots.append(snap)

        if not snapshots:
            return []

        volumes = [s.volume_24h for s in snapshots]
        depths = [s.bid_depth + s.ask_depth for s in snapshots]
        spreads = [s.spread_pct for s in snapshots]
        activities = [float(s.trade_count) for s in snapshots]

        vol_score = _minmax(volumes)
        liq_score = _minmax(depths)
        # Tighter spread is better -> invert.
        spread_score = _minmax_inverted(spreads)
        act_score = _minmax(activities)

        w_v = 0.40
        w_l = 0.30
        w_s = 0.20
        w_a = 0.10

        ranked: List[RankedMarket] = []
        for i, snap in enumerate(snapshots):
            rm = RankedMarket(snapshot=snap)
            rm.volume_score = vol_score[i]
            rm.liquidity_score = liq_score[i]
            rm.spread_score = spread_score[i]
            rm.activity_score = act_score[i]
            rm.total_score = (
                w_v * rm.volume_score
                + w_l * rm.liquidity_score
                + w_s * rm.spread_score
                + w_a * rm.activity_score
            )
            ranked.append(rm)

        ranked.sort(key=lambda x: x.total_score, reverse=True)
        return ranked[:top_n]

    def select_top_markets(self, top_n: int = 10) -> List[str]:
        """Return the list of top ``top_n`` market symbols."""
        ranked = self.rank_markets(top_n=top_n)
        return [rm.snapshot.symbol for rm in ranked]


def _safe(x: float) -> float:
    return x if math.isfinite(x) else 0.0


def _minmax(values: List[float]) -> List[float]:
    vals = [_safe(v) for v in values]
    lo, hi = (min(vals), max(vals)) if vals else (0, 0)
    if hi - lo == 0:
        return [0.5 for _ in vals]
    return [ (v - lo) / (hi - lo) for v in vals ]


def _minmax_inverted(values: List[float]) -> List[float]:
    vals = [_safe(v) for v in values]
    lo, hi = (min(vals), max(vals)) if vals else (0, 0)
    if hi - lo == 0:
        return [0.5 for _ in vals]
    # Lower value = higher score.
    return [ 1.0 - (v - lo) / (hi - lo) for v in vals ]
