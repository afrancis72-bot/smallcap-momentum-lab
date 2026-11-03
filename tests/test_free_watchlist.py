"""Offline free-stream validation. Does not call a Finnhub API."""
from datetime import datetime, timezone
from free_watchlist import FreeWatchlist


def trade(symbol, price, utc):
    dt = datetime.fromisoformat(utc.replace("Z", "+00:00"))
    return {"type": "trade", "data": [{
        "s": symbol, "p": price, "t": int(dt.timestamp()*1000), "v": 100
    }]}


def test_free_stream_afterhours_requires_real_current_session_trade():
    watch = FreeWatchlist("not-real-key", ["PERI"])
    watch.ingest(trade("PERI", 11.45, "2026-11-02T22:59:30Z"))
    row = watch.snapshot(datetime(2026, 11, 2, 23, tzinfo=timezone.utc))[0]
    assert row["Last free-feed trade $"] == 11.45
    assert row["Status"] == "Fresh current-session print (partial feed)"


def test_old_regular_session_trade_not_accepted_as_live_afterhours():
    watch = FreeWatchlist("not-real-key", ["PERI"])
    watch.ingest(trade("PERI", 11.4, "2026-11-02T20:59:30Z"))
    row = watch.snapshot(datetime(2026, 11, 2, 21, tzinfo=timezone.utc))[0]
    assert row["Status"] == "Stale / different session"


def test_no_trades_means_no_unverified_fallback():
    watch = FreeWatchlist("not-real-key", ["PERI", "VCIG"])
    rows = watch.snapshot(datetime(2026, 11, 2, 23, tzinfo=timezone.utc))
    assert all(row["Status"] == "No trade received" for row in rows)
    assert all(row["Last free-feed trade $"] is None for row in rows)


def test_out_of_order_trade_does_not_replace_price():
    watch = FreeWatchlist("not-real-key", ["PERI"])
    watch.ingest(trade("PERI", 11.4, "2026-11-02T22:59:30Z"))
    watch.ingest(trade("PERI", 10.0, "2026-11-02T22:58:30Z"))
    row = watch.snapshot(datetime(2026, 11, 2, 23, tzinfo=timezone.utc))[0]
    assert row["Last free-feed trade $"] == 11.4



def test_rest_quote_from_regular_market_is_not_live_in_afterhours():
    from free_watchlist import _rest_quote_row
    stamp = int(datetime(2026, 11, 2, 20, 59, 30, tzinfo=timezone.utc).timestamp())
    result = _rest_quote_row("BRAI", {"c": 2.1, "pc": 2.0, "t": stamp},
                             datetime(2026, 11, 2, 21, tzinfo=timezone.utc))
    assert result["Status"] == "Stale / other session"
    assert result["Quote session"] == "Regular"


def test_rest_quote_without_valid_price_cannot_be_fresh():
    from free_watchlist import _rest_quote_row
    stamp = int(datetime(2026, 11, 2, 23, 0, tzinfo=timezone.utc).timestamp())
    result = _rest_quote_row("SEGG", {"c": 0, "pc": 1, "t": stamp},
                             datetime(2026, 11, 2, 23, tzinfo=timezone.utc))
    assert result["Status"] == "No valid quote"


def test_rest_quote_current_afterhours_session_is_fresh_if_age_is_under_two_min():
    from free_watchlist import _rest_quote_row
    stamp = int(datetime(2026, 11, 2, 23, 0, tzinfo=timezone.utc).timestamp())
    result = _rest_quote_row("PARA", {"c": 5.3, "pc": 5.0, "t": stamp},
                             datetime(2026, 11, 2, 23, 1, tzinfo=timezone.utc))
    assert result["Status"] == "Recent current-session quote (partial feed)"
