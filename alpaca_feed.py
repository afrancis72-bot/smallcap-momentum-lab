"""Read-only Alpaca integration. Never submits or constructs brokerage orders."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import re
import requests

TRADING = "https://paper-api.alpaca.markets"
MARKET = "https://data.alpaca.markets"
SUPPORTED_EXCHANGES = {"NASDAQ", "NYSE", "AMEX", "ARCA", "BATS", "NYSEARCA", "TXSE"}

# Alpaca classifies exchange-listed warrants, rights, ETFs and units as us_equity.
# Exclude them from the primary common-stock research universe, including sub-$1 symbols.
_NON_COMMON_INSTRUMENT = re.compile(
    r"\b(warrants?|rights?|units?|preferred|preference shares?|"
    r"exchange.traded funds?|ETFs?|ETNs?|exchange.traded notes?|"
    r"notes? due [0-9]|debentures?|closed.end funds?)\b",
    flags=re.IGNORECASE,
)
_NON_COMMON_SUFFIX = re.compile(r"(?:[.-](?:WS?|RT?|U|P|PR))$", re.IGNORECASE)


def is_common_equity_asset(asset):
    if (asset.get("status") != "active" or asset.get("class") != "us_equity"
        or asset.get("exchange") not in SUPPORTED_EXCHANGES
        or asset.get("tradable") is not True
        or not asset.get("symbol")):
        return False
    name = str(asset.get("name") or "")
    symbol = str(asset.get("symbol") or "")
    return not (_NON_COMMON_INSTRUMENT.search(name) or _NON_COMMON_SUFFIX.search(symbol))



class DataError(RuntimeError):
    pass


class AccessError(DataError):
    """Access problem: a different data feed will require an explicit user choice."""
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
            if code == 401:
                raise AccessError(
                    "Alpaca HTTP 401: authentication rejected on this request. "
                    "Verify the paper API key and secret; if Free IEX works with "
                    "these same keys, the selected feed or account access needs checking."
                ) from exc
            if code == 403:
                raise AccessError(
                    "Alpaca HTTP 403: this feed or data request is not permitted "
                    "for your account. Use Free IEX for snapshots or select "
                    "historical SIP bars (15+ minutes old) for research."
                ) from exc
            if code == 429:
                raise DataError("Alpaca rate limit (429). Do not refresh again immediately.") from exc
            raise DataError(f"Alpaca HTTP {code}: request failed.") from exc
        except (requests.RequestException, ValueError) as exc:
            raise DataError(f"Alpaca data request could not complete: {type(exc).__name__}") from exc

    def assets(self):
        result = self._get(TRADING + "/v2/assets", {"status": "active", "asset_class": "us_equity"})
        return [a for a in result if is_common_equity_asset(a)]

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
            except AccessError:
                # Fail immediately instead of attempting 100+ additional batches.
                raise
            except DataError as exc:
                errors.append(f"Batch {offset // batch_size + 1}: {exc}")
                if "429" in str(exc):
                    break
        return snapshots, completed, errors

    def test_iex_connection(self, symbol="AAPL"):
        """Single-symbol, read-only key diagnostic; NOT a full-universe scan."""
        obj = self._get(MARKET + "/v2/stocks/snapshots", {
            "symbols": symbol, "feed": "iex",
        })
        return isinstance(obj, dict) and symbol in obj

    def bars(self, symbol, days=7, max_pages=6, historical_feed=None):
        clean = symbol.upper().strip()
        if not clean or len(clean) > 20 or not all(ch.isalnum() or ch in ".-" for ch in clean):
            raise DataError("Invalid ticker symbol.")
        # Delayed SIP is a snapshot feed; historical SIP bars >15 min old
        # can be requested separately without assuming real-time entitlement.
        selected_feed = historical_feed or ("sip" if self.feed == "delayed_sip" else self.feed)
        # Only authorized real-time SIP may request the last 15 minutes.
        delay = 0 if selected_feed == "sip" and self.feed == "sip" else 16
        end = datetime.now(timezone.utc) - timedelta(minutes=delay)
        start = end - timedelta(days=int(days))
        if selected_feed not in {"iex", "sip"}:
            raise DataError("Historical bars feed must be IEX or SIP.")
        params = {
            "start": start.isoformat(), "end": end.isoformat(),
            "timeframe": "1Min", "limit": 10000, "feed": selected_feed,
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
