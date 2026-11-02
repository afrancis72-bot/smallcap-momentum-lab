"""No-network checks for live consolidated SIP display and session safety."""
from datetime import datetime, timezone

from live_sip import SIPLiveStream


def test_afterhours_live_trade_is_fresh_and_session_matched():
    watch = SIPLiveStream("fake", "fake", ["PERI"])
    watch._handle({"T": "t", "S": "PERI", "p": 11.25, "t": "2026-11-02T22:59:30Z"})
    watch._handle({"T": "q", "S": "PERI", "bp": 11.2, "ap": 11.3,
                   "t": "2026-11-02T22:59:31Z"})
    row = watch.snapshot(datetime(2026, 11, 2, 23, 0, tzinfo=timezone.utc))[0]
    assert row["Status"] == "LIVE session print"
    assert row["Last SIP trade $"] == 11.25
    assert row["Spread %"] is not None


def test_regular_trade_is_not_afterhours_live_even_when_recent():
    watch = SIPLiveStream("fake", "fake", ["PERI"])
    watch._handle({"T": "t", "S": "PERI", "p": 11.25, "t": "2026-11-02T20:59:30Z"})
    row = watch.snapshot(datetime(2026, 11, 2, 21, 0, tzinfo=timezone.utc))[0]
    assert row["Status"] == "Stale / prior session"


def test_no_streamed_trade_is_not_live():
    watch = SIPLiveStream("fake", "fake", ["PERI"])
    row = watch.snapshot(datetime(2026, 11, 2, 23, 0, tzinfo=timezone.utc))[0]
    assert row["Last SIP trade $"] is None
    assert row["Status"] == "Awaiting SIP trade"


def test_older_trade_cannot_overwrite_a_newer_trade():
    watch = SIPLiveStream("fake", "fake", ["PERI"])
    watch._handle({"T": "t", "S": "PERI", "p": 4.5, "t": "2026-11-02T22:59:30Z"})
    watch._handle({"T": "t", "S": "PERI", "p": 1, "t": "2026-11-02T22:58:30Z"})
    row = watch.snapshot(datetime(2026, 11, 2, 23, 0, tzinfo=timezone.utc))[0]
    assert row["Last SIP trade $"] == 4.5
