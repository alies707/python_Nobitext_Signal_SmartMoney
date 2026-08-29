"""Historical data acquisition and persistence.

Downloads OHLCV history for a symbol across multiple timeframes using the
Nobitex client, validates it via :class:`CandleManager`, and optionally caches
it to CSV for reproducible backtests.

When the API is unavailable the module reports the failure rather than
fabricating data (see project requirement #48).
"""
from __future__ import annotations

import csv
import os
from typing import Dict, List, Optional

from data.candle_manager import CandleManager
from exchange.nobitex_client import NobitexClient
from models.candle import Candle
from utils.logger import get_logger

logger = get_logger(__name__)

# Interval in milliseconds per timeframe, used for gap detection / resampling.
TF_TO_MS = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1H": 60 * 60_000,
    "4H": 4 * 60 * 60_000,
    "1D": 24 * 60 * 60_000,
}


class HistoricalData:
    """Manages retrieval and local caching of historical candles."""

    def __init__(self, client: NobitexClient, cache_dir: str = "data/history"):
        self.client = client
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Download
    # ------------------------------------------------------------------ #
    def download(
        self,
        symbol: str,
        timeframes: Optional[List[str]] = None,
        limit: int = 500,
        use_cache: bool = False,
    ) -> CandleManager:
        """Download candles for ``symbol`` across ``timeframes``.

        Returns a :class:`CandleManager` containing whatever data could be
        retrieved. If a timeframe fully fails, it is simply empty (the engine
        and tests can detect insufficient data).
        """
        timeframes = timeframes or ["1m", "5m", "15m", "1H", "4H", "1D"]
        manager = CandleManager(symbol=symbol)

        for tf in timeframes:
            candles: List[Candle] = []
            if use_cache:
                candles = self.load_from_csv(symbol, tf)
            if not candles:
                raw = self.client.get_ohlcv(symbol, tf, limit=limit)
                candles = [Candle.from_dict(r) for r in raw]
                if use_cache and candles:
                    self.save_to_csv(symbol, tf, candles)
            manager.set_candles(tf, candles)
            if not candles:
                logger.warning("No candles retrieved for %s/%s", symbol, tf)
        return manager

    # ------------------------------------------------------------------ #
    # CSV persistence
    # ------------------------------------------------------------------ #
    def _path(self, symbol: str, tf: str) -> str:
        safe = symbol.replace("/", "_")
        return os.path.join(self.cache_dir, f"{safe}_{tf}.csv")

    def save_to_csv(self, symbol: str, tf: str, candles: List[Candle]) -> None:
        path = self._path(symbol, tf)
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
                for c in candles:
                    writer.writerow(
                        [c.timestamp, c.open, c.high, c.low, c.close, c.volume]
                    )
            logger.debug("Saved %d candles to %s", len(candles), path)
        except OSError as exc:
            logger.error("Failed saving CSV %s: %s", path, exc)

    def load_from_csv(self, symbol: str, tf: str) -> List[Candle]:
        path = self._path(symbol, tf)
        if not os.path.exists(path):
            return []
        candles: List[Candle] = []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    candles.append(
                        Candle(
                            timestamp=int(row["timestamp"]),
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            volume=float(row.get("volume", 0.0)),
                        )
                    )
        except (OSError, ValueError, KeyError) as exc:
            logger.error("Failed loading CSV %s: %s", path, exc)
            return []
        return candles
