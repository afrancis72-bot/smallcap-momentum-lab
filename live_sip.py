"""Read-only, per-user SIP WebSocket watchlist (never places orders).

This streams explicitly selected symbols, NOT the entire listed universe.
The scanner still uses snapshots to discover new movers. Prices shown as live
must be actual SIP trades timestamped inside the active Eastern session.
"""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Event, Lock, Thread
from zoneinfo import ZoneInfo
import json
import re

import websocket

from sessions import market_session, SESSION_CLOCK

_EASTERN = ZoneInfo("America/New_York")
_VALID_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,19}$")
_URL = "wss://stream.data.alpaca.markets/v2/sip"


def _parse_timestamp(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


class SIPLiveStream:
    """Single background read-only connection while a browser session watches."""

    def __init__(self, key, secret, symbols):
        clean = list(dict.fromkeys(str(s).upper().strip() for s in symbols))
        self.symbols = tuple(s for s in clean if _VALID_SYMBOL.fullmatch(s))[:40]
        if not key or not secret or not self.symbols:
            raise ValueError("SIP stream needs credentials and 1–40 valid ticker symbols.")
        self._key = key
        self._secret = secret
        self._lock = Lock()
        self._stop = Event()
        self._socket = None
        self._thread = None
        self._status = "Not started"
        self._prints = {s: {} for s in self.symbols}

    def _set_status(self, status):
        with self._lock:
            self._status = status

    @property
    def status(self):
        with self._lock:
            return self._status

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def start(self):
        if not self.running and not self._stop.is_set():
            self._thread = Thread(target=self._run, name="alpaca-sip-watchlist", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        # Closing the socket unblocks recv promptly; no joins on the UI thread.
        ws = self._socket
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        self._set_status("Stopped")

    def _handle(self, msg):
        kind = msg.get("T")
        symbol = msg.get("S")
        if kind not in {"t", "q"} or symbol not in self._prints:
            return
        stamp = _parse_timestamp(msg.get("t"))
        if stamp is None:
            return
        key = "trade" if kind == "t" else "quote"
        with self._lock:
            existing = self._prints[symbol].get(key, {})
            if existing.get("utc") and stamp < existing["utc"]:
                return
            if kind == "t":
                price = msg.get("p")
                if not isinstance(price, (float, int)) or price <= 0:
                    return
                self._prints[symbol][key] = {"utc": stamp, "price": float(price)}
            else:
                self._prints[symbol][key] = {
                    "utc": stamp, "bid": msg.get("bp"), "ask": msg.get("ap")
                }

    def _receive(self, ws, authenticating=False):
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            return False
        if not raw:
            raise ConnectionError("Socket closed")
        for msg in json.loads(raw):
            kind = msg.get("T")
            if kind == "error":
                self._set_status("Alpaca denied SIP stream access or subscription; verify paid SIP entitlement.")
                return None
            if kind == "success" and msg.get("msg") == "authenticated":
                return True
            if kind == "subscription":
                self._set_status("Connected — receiving SIP trades and quotes when available")
            self._handle(msg)
        return False

    def _run(self):
        while not self._stop.is_set():
            ws = None
            denied = False
            try:
                self._set_status("Connecting to real-time consolidated SIP…")
                ws = websocket.create_connection(_URL, timeout=10, enable_multithread=True)
                ws.settimeout(3)
                self._socket = ws
                ws.send(json.dumps({"action": "auth", "key": self._key, "secret": self._secret}))
                authenticated = False
                # Wait for explicit auth acknowledgement, without indefinite blocking.
                for _ in range(5):
                    if self._stop.is_set():
                        break
                    result = self._receive(ws, authenticating=True)
                    if result is None:
                        denied = True
                        break
                    if result is True:
                        authenticated = True
                        break
                if denied:
                    return
                if not authenticated:
                    raise ConnectionError("Alpaca did not confirm authorization")
                ws.send(json.dumps({
                    "action": "subscribe",
                    "trades": list(self.symbols),
                    "quotes": list(self.symbols),
                }))
                self._set_status("Authenticated — waiting for SIP subscription…")
                while not self._stop.is_set():
                    if self._receive(ws) is None:
                        denied = True
                        break
                if denied:
                    return
            except Exception:
                if not self._stop.is_set():
                    self._set_status("SIP connection interrupted — attempting to reconnect")
            finally:
                self._socket = None
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:
                        pass
            if not self._stop.is_set():
                self._stop.wait(4)
        self._set_status("Stopped")

    def snapshot(self, now=None):
        """Present only same-day, same-session prints as fresh; no simulated ticks."""
        now = now or datetime.now(timezone.utc)
        current_session, local = market_session(now)
        with self._lock:
            cached = {sym: dict(fields) for sym, fields in self._prints.items()}
        rows = []
        for symbol in self.symbols:
            data = cached.get(symbol, {})
            t = data.get("trade", {})
            q = data.get("quote", {})
            stamp = t.get("utc")
            age = ((now - stamp).total_seconds() / 60 if stamp else None)
            observed, printed_et = market_session(stamp) if stamp else ("Unknown", None)
            active = bool(
                current_session in SESSION_CLOCK and printed_et is not None
                and local is not None and printed_et.date() == local.date()
                and observed == current_session
            )
            live = bool(active and age is not None and 0 <= age <= 2)
            bid, ask = q.get("bid"), q.get("ask")
            spread = (100 * (ask - bid) / ((ask + bid) / 2)
                      if isinstance(bid, (int, float)) and isinstance(ask, (int, float))
                      and bid > 0 and ask >= bid else None)
            quote_stamp = q.get("utc")
            quote_age = ((now - quote_stamp).total_seconds() / 60 if quote_stamp else None)
            rows.append({
                "Ticker": symbol,
                "Last SIP trade $": round(t["price"], 4) if "price" in t else None,
                "Trade time ET": printed_et.strftime("%I:%M:%S %p") if printed_et else "No trade yet",
                "Trade age (min)": round(age, 2) if age is not None else None,
                "Bid $": bid, "Ask $": ask,
                "Spread %": round(spread, 2) if spread is not None else None,
                "Quote age (min)": round(quote_age, 2) if quote_age is not None else None,
                "Status": ("LIVE session print" if live else
                           "Stale / prior session" if stamp else "Awaiting SIP trade"),
            })
        return rows
