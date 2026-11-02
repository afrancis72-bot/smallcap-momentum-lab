"""Read-only Alpaca integration. Never submits or constructs brokerage orders."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import requests

TRADING = "https://paper-api.alpaca.markets"
MARKET = "https://data.alpaca.markets"
SUPPORTED_EXCHANGES = {"NASDAQ", "NYSE", "AMEX", "ARCA", "BATS", "NYSEARCA", "TXSE"}


class DataError(RuntimeError):
    pass


class AlpacaReadOnly:
    def __init__(self, key, secret, feed="iex"):
        if not key or not secret:
            raise DataError("Set Alpaca paper API credentials before requesting market data.")
        if feed not in {"iex", "sip", "delayed_sip"}:
            raise DataError("Unsupported market data feed.")
        self.feed = feed
        self.http = requests.Session()
        self.http.headers.update({
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "accept": "application/json",
        })

    def _get(self, url, params=None):
        try:
            response = self.http.get(url, params=params, timeout=18)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            if code in (401, 403):
                raise DataError(f"Alpaca HTTP {code}: credentials or market-data subscription not authorized.") from exc
            if code == 429:
                raise DataError("Alpaca rate limit (429). Do not refresh again immediately.") from exc
            raise DataError(f"Alpaca HTTP {code}: request failed.") from exc
        except (requests.RequestException, ValueError) as exc:
            raise DataError(f"Alpaca data request could not complete: {type(exc).__name__}") from exc

    def assets(self):
        result = self._get(TRADING + "/v2/assets", {"status": "active", "asset_class": "us_equity"})
        return [a for a in result if a.get("status") == "active"
                and a.get("class") == "us_equity"
                and a.get("exchange") in SUPPORTED_EXCHANGES
                and a.get("symbol") and a.get("tradable") is True]

    def snapshots(self, symbols, batch_size=125):
        """Batched GET; failed batch becomes a visible coverage gap, never fake zeros."""
        snapshots, errors, completed = {}, [], 0
        for offset in range(0, len(symbols), batch_size):
            batch = symbols[offset:offset + batch_size]
            try:
                result = self._get(MARKET + "/v2/stocks/snapshots", {
                    "symbols": ",".join(batch), "feed": self.feed,
                })
                snapshots.update(result or {})
                completed += len(batch)
            except DataError as exc:
                errors.append(f"Batch {offset // batch_size + 1}: {exc}")
                if "429" in str(exc):
                    break
        return snapshots, completed, errors

    def bars(self, symbol, days=7, max_pages=6):
        clean = symbol.upper().strip()
        if not clean or len(clean) > 20 or not all(ch.isalnum() or ch in ".-" for ch in clean):
            raise DataError("Invalid ticker symbol.")
        end = datetime.now(timezone.utc) - timedelta(minutes=16)
        start = end - timedelta(days=int(days))
        params = {
            "start": start.isoformat(), "end": end.isoformat(),
            "timeframe": "1Min", "limit": 10000, "feed": self.feed,
            "adjustment": "raw", "sort": "asc",
        }
        bars, truncated = [], False
        for page in range(max_pages):
            obj = self._get(MARKET + f"/v2/stocks/{quote(clean, safe='')}/bars", params)
            bars.extend(obj.get("bars") or [])
            token = obj.get("next_page_token")
            if not token:
                break
            params["page_token"] = token
            if page == max_pages - 1:
                truncated = True
        return bars, truncated

    def news(self, symbol, limit=12):
        obj = self._get(MARKET + "/v1beta1/news", {
            "symbols": symbol.upper().strip(), "limit": min(50, int(limit)), "sort": "desc"
        })
        return obj.get("news") or []
