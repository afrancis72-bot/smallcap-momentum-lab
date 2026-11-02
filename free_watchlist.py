"""Personal-use, read-only Finnhub free trade-stream watchlist.

Free coverage is NOT guaranteed to be consolidated, nor complete pre/postmarket.
No broker orders; all observed prints are timestamped and session-verified.
"""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Event, Lock, Thread
from urllib.parse import quote
import json
import re
import websocket

from sessions import market_session, SESSION_CLOCK

_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,19}$")


class FreeWatchlist:
    """Keep a small explicit watchlist; never manufacture missing prices."""

    def __init__(self, token, symbols):
        unique = list(dict.fromkeys(str(x).upper().strip() for x in symbols))
        self.symbols = tuple(x for x in unique if _SYMBOL.fullmatch(x))[:40]
        if not token or not self.symbols:
            raise ValueError("Provide a free Finnhub API key and 1–40 valid symbols.")
        self._token = str(token).strip()
        self._stop = Event()
        self._lock = Lock()
        self._thread = None
        self._ws = None
        self._status = "Not started"
        self._last = {}

    def _set(self, status):
        with self._lock:
            self._status = status

    @property
    def status(self):
        with self._lock:
            return self._status

    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = Thread(target=self._run, name="free-finnhub-personal", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
        self._set("Stopped")

    def ingest(self, event):
        if event.get("type") != "trade":
            return
        for data in event.get("data", []):
            sym = data.get("s")
            if sym not in self.symbols:
                continue
            try:
                when = datetime.fromtimestamp(float(data["t"]) / 1000, tz=timezone.utc)
                price = float(data["p"])
                volume = float(data.get("v") or 0)
            except (TypeError, KeyError, ValueError, OverflowError):
                continue
            if not 0 < price < 10**9:
                continue
            with self._lock:
                previous = self._last.get(sym)
                if previous is None or when >= previous["timestamp"]:
                    self._last[sym] = {
                        "timestamp": when, "price": price, "shares": volume
                    }

    def _run(self):
        while not self._stop.is_set():
            self._set("Connecting to Finnhub free stream…")
            def on_open(ws):
                self._set("Connected — awaiting actual trades")
                for s in self.symbols:
                    ws.send(json.dumps({"type": "subscribe", "symbol": s}))
            def on_message(ws, raw):
                try:
                    event = json.loads(raw)
                    if event.get("type") == "error":
                        self._set("Free feed rejected subscription or entitlement")
                    else:
                        self.ingest(event)
                except (ValueError, TypeError):
                    pass
            def on_error(ws, error):
                # Never expose the secret-bearing WebSocket URL or stack trace.
                self._set("Free stream interrupted — reconnecting")
            try:
                # Key is sent only over secure WebSocket, never logged by this app.
                ws = websocket.WebSocketApp(
                    "wss://ws.finnhub.io?token=" + quote(self._token, safe=""),
                    on_open=on_open, on_message=on_message, on_error=on_error,
                )
                self._ws = ws
                ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception:
                self._set("Free stream connection failed")
            finally:
                self._ws = None
            if not self._stop.is_set():
                self._stop.wait(6)
        self._set("Stopped")

    def snapshot(self, now=None):
        now = now or datetime.now(timezone.utc)
        session, local = market_session(now)
        with self._lock:
            data = dict(self._last)
        rows = []
        for sym in self.symbols:
            info = data.get(sym)
            stamp = info["timestamp"] if info else None
            observed, local_print = market_session(stamp) if stamp else ("Unknown", None)
            age = (now - stamp).total_seconds() / 60 if stamp else None
            current = bool(
                session in SESSION_CLOCK and observed == session and local_print
                and local_print.date() == local.date()
                and age is not None and 0 <= age <= 2
            )
            rows.append({
                "Ticker": sym,
                "Last free-feed trade $": round(info["price"], 4) if info else None,
                "Event session": observed if stamp else "Unknown",
                "Last trade ET": local_print.strftime("%m/%d %I:%M:%S %p") if local_print else "",
                "Age (min)": round(age, 2) if age is not None else None,
                "Trade shares": info["shares"] if info else None,
                "Status": ("Fresh current-session print (partial feed)" if current else
                           "Stale / different session" if info else
                           "No trade received"),
            })
        return rows
