"""Nobitex exchange API client.

Implements a thin, dependency-light HTTP client for the Nobitex public REST
API. It focuses on:

* available markets,
* market statistics (used for dynamic ranking),
* order book,
* recent trades,
* OHLCV candles.

The client is defensive: timeouts, retries, rate-limit awareness and invalid
responses are handled so that a single failing request never crashes the
engine. API keys are never required for the public endpoints used here, and are
never logged.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import requests

from utils.logger import get_logger, mask_secret

logger = get_logger(__name__)

# Map our internal timeframe labels to Nobitex OHLC resolutions.
# The v2 candle endpoint (/market/udf/history) is TradingView UDF style and uses
# minute integers ("15", "60", "240") or "1D"/"D" for daily.
TIMEFRAME_TO_RESOLUTION = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "1H": "60",
    "4H": "240",
    "1D": "1D",
    "1W": "1W",
}

# Seconds per resolution, used to derive a `from` bound when only a limit is given.
_RESOLUTION_SECONDS = {
    "1": 60,
    "5": 300,
    "15": 900,
    "60": 3600,
    "240": 14400,
    "1D": 86400,
    "D": 86400,
    "1W": 604800,
    "W": 604800,
}


def to_udf_symbol(symbol: str) -> str:
    """Normalize an internal symbol to the v2 API (UDF) form.

    The v2 endpoints (candles, order book, trades) expect uppercase, dash-free
    symbols where the Iranian Rial quote is written ``IRT``, e.g.::
        btc-rls  -> BTCIRT
        BTCIRT   -> BTCIRT
        btc-usdt -> BTCUSDT
    """
    s = symbol.strip().upper().replace("-", "").replace("_", "")
    return s.replace("RLS", "IRT")


def to_stats_key(symbol: str) -> str:
    """Normalize an internal symbol to the dash-lowercase key used in
    ``/market/stats`` (e.g. ``BTCIRT`` -> ``btc-rls``). Accepts both the stats
    form (``btc-rls``) and the UDF form (``BTCIRT``)."""
    # Quote currencies accepted by Nobitex, longest first so e.g. "usdt"
    # matches before "usd".
    known_quotes = ("usdt", "usdc", "busd", "tusd", "ust", "rls", "try", "eur")
    s = symbol.strip().lower().replace("-", "").replace("_", "")
    s = s.replace("irt", "rls")  # stats quote is "rls", not "irt"
    for q in known_quotes:
        if s.endswith(q) and len(s) > len(q):
            base = s[: -len(q)]
            return f"{base}-{q}"
    return s.lower()


class NobitexClientError(Exception):
    """Raised on unrecoverable client-level errors."""


class NobitexClient:
    """HTTP client for the Nobitex public API."""

    BASE_URL = "https://apiv2.nobitex.ir"

    def __init__(
        self,
        api_key: str = "",
        api_url: str = BASE_URL,
        timeout: int = 15,
        max_retries: int = 3,
        backoff: float = 1.5,
    ):
        self.api_key = api_key
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.session = requests.Session()
        self.connected: bool = False
        # Apply secret filter so API keys never leak into logs.
        logger.addFilter(_SecretFilter([api_key] if api_key else []))

    # ------------------------------------------------------------------ #
    # Low level request helper
    # ------------------------------------------------------------------ #
    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        url = f"{self.api_url}{path}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "TraderBot/smart-money-engine-1.0.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Token {self.api_key}"

        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=self.timeout,
                )
                self.connected = True
                # Rate-limit / 5xx handling with bounded retry.
                if resp.status_code in (429, 500, 502, 503, 504):
                    logger.warning(
                        "Nobitex returned %s on %s (attempt %s/%s)",
                        resp.status_code,
                        path,
                        attempt,
                        self.max_retries,
                    )
                    time.sleep(self.backoff * attempt)
                    last_error = NobitexClientError(f"HTTP {resp.status_code}")
                    continue
                if resp.status_code != 200:
                    # 400 (e.g. InvalidSymbol) is an expected, non-fatal case
                    # for filtered/delisted symbols; report once and stop.
                    if resp.status_code == 400:
                        logger.warning(
                            "Nobitex HTTP 400 on %s: %s",
                            path,
                            resp.text[:200],
                        )
                        return None
                    logger.error(
                        "Nobitex HTTP error %s on %s: %s",
                        resp.status_code,
                        path,
                        resp.text[:200],
                    )
                    resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict) and data.get("status") == "failed":
                    logger.error("Nobitex API error: %s", data.get("message"))
                    return None
                return data
            except requests.exceptions.Timeout as exc:
                last_error = exc
                logger.warning("Nobitex timeout on %s (attempt %s)", path, attempt)
            except requests.exceptions.ConnectionError as exc:
                last_error = exc
                logger.warning("Nobitex connection error on %s (attempt %s)", path, attempt)
            except requests.exceptions.HTTPError as exc:
                last_error = exc
                logger.error("Nobitex HTTPError on %s: %s", path, exc)
                return None
            except ValueError as exc:  # JSON decode error
                last_error = exc
                logger.error("Nobitex returned invalid JSON on %s: %s", path, exc)
                return None
            if attempt < self.max_retries:
                time.sleep(self.backoff * attempt)

        self.connected = False
        logger.error("Nobitex request to %s failed after retries: %s", path, last_error)
        return None

    # ------------------------------------------------------------------ #
    # Public endpoints
    # ------------------------------------------------------------------ #
    def get_markets(self) -> List[str]:
        """Return the list of available market symbols (e.g. ``btc-rls``).

        The v2 API has no dedicated coins-list endpoint, so the market universe
        is derived from the ``/market/stats`` response keys (dash-lowercase).
        """
        stats = self.get_market_stats()
        if not stats:
            return []
        return list(stats.keys())

    def get_market_stats(self) -> Dict[str, Dict[str, Any]]:
        """Return market statistics keyed by symbol.

        The response contains 24h volume, last price, best bid/ask, high/low
        and is used for dynamic market ranking.
        """
        data = self._request("GET", "/market/stats")
        if not data:
            return {}
        stats = data.get("stats")
        if not isinstance(stats, dict):
            logger.error("Unexpected market/stats payload shape")
            return {}
        return stats

    def get_order_book(self, symbol: str, depth: int = 10) -> Optional[Dict[str, Any]]:
        data = self._request("GET", f"/v3/orderbook/{to_udf_symbol(symbol)}")
        if not data or data.get("status") != "ok":
            return None
        asks = data.get("asks", [])[:depth]
        bids = data.get("bids", [])[:depth]
        return {"symbol": symbol, "asks": asks, "bids": bids}

    def get_recent_trades(self, symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
        data = self._request("GET", f"/v2/trades/{to_udf_symbol(symbol)}")
        if not data or data.get("status") != "ok":
            return []
        trades = data.get("trades", [])[:limit]
        # Normalize trade fields to a stable shape.
        normalized = []
        for tr in trades:
            normalized.append(
                {
                    "timestamp": int(tr.get("time", 0)),
                    "price": float(tr.get("price", 0)),
                    "volume": float(tr.get("volume", 0)),
                    "side": tr.get("type", ""),
                }
            )
        return normalized

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "15m",
        since: Optional[int] = None,
        until: Optional[int] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """Fetch OHLCV candles from the Nobitex v2 UDF history endpoint.

        Parameters
        ----------
        symbol:
            Market symbol, e.g. ``BTCIRT`` (normalized to the v2 UDF form).
        timeframe:
            Internal label from ``supported_timeframes``.
        since, until:
            Epoch *seconds* bounds. When omitted, the most recent ``limit``
            candles are requested.
        limit:
            Maximum number of candles to retrieve. The UDF endpoint returns at
            most 500 candles per request, so larger windows are fetched with
            several backward paging chunks.
        """
        resolution = TIMEFRAME_TO_RESOLUTION.get(timeframe)
        if resolution is None:
            logger.error("Unsupported timeframe for OHLC: %s", timeframe)
            return []

        res_sec = _RESOLUTION_SECONDS.get(resolution, 900)
        now = int(time.time())
        until_ts = int(until) if until is not None else now
        since_ts = int(since) if since is not None else None

        MAX_PER_REQ = 500
        collected: List[Dict[str, Any]] = []
        chunk_to = until_ts
        safety = 50
        while len(collected) < limit and safety > 0:
            safety -= 1
            chunk_from = chunk_to - MAX_PER_REQ * res_sec
            if since_ts is not None:
                chunk_from = max(chunk_from, since_ts)

            data = self._request(
                "GET",
                "/market/udf/history",
                params={
                    "symbol": to_udf_symbol(symbol),
                    "resolution": resolution,
                    "from": chunk_from,
                    "to": chunk_to,
                },
            )
            if not data:
                break
            status = data.get("s")
            if status == "no_data":
                # No more history in this window; stop if we reached `since`.
                if since_ts is not None and chunk_from <= since_ts:
                    break
                chunk_to = chunk_from - 1
                continue
            if status != "ok":
                logger.error("Nobitex UDF history error: %s", status)
                break

            chunk = self._parse_udf_candles(data)
            if not chunk:
                break
            # Each chunk is older than the previously collected candles.
            collected = chunk + collected
            chunk_to = int(chunk[0]["timestamp"] / 1000) - 1
            if since_ts is not None and chunk_to <= since_ts:
                break

        if limit:
            collected = collected[-limit:]
        return collected

    @staticmethod
    def _parse_udf_candles(data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Convert a UDF history payload into normalized candle dicts (ms)."""
        t = data.get("t") or []
        o = data.get("o") or []
        h = data.get("h") or []
        l = data.get("l") or []
        c = data.get("c") or []
        v = data.get("v") or []
        if not t or len(t) < 2:
            return []

        candles: List[Dict[str, Any]] = []
        length = min(len(t), len(o), len(h), len(l), len(c))
        for i in range(length):
            candles.append(
                {
                    "timestamp": int(t[i]) * 1000,  # convert s -> ms
                    "open": float(o[i]),
                    "high": float(h[i]),
                    "low": float(l[i]),
                    "close": float(c[i]),
                    "volume": float(v[i]) if i < len(v) else 0.0,
                }
            )

        # Sort chronologically, dedupe by timestamp.
        seen = set()
        unique = []
        for cd in sorted(candles, key=lambda x: x["timestamp"]):
            if cd["timestamp"] in seen:
                continue
            seen.add(cd["timestamp"])
            unique.append(cd)
        return unique

    def health_check(self) -> bool:
        """Return True when the API is reachable."""
        stats = self.get_market_stats()
        return bool(stats)


class _SecretFilter(logging.Filter):
    """Redacts secret values from log records."""

    def __init__(self, secrets: List[str]):
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secrets:
            return True
        msg = record.getMessage()
        if any(s in msg for s in self._secrets):
            record.msg = mask_secret(str(record.msg))
            record.args = ()
        return True
