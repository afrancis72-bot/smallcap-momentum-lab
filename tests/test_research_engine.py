"""Deterministic smoke tests for research logic; these are NOT live API tests."""
from datetime import datetime, timezone
import pandas as pd

from research_engine import prepare_bars, snapshot_table, backtest_opening_range, trade_summary


def sample_bars(breakout=True):
    # Eastern DST (October 30, 2026).
    prices = [
        (2.00, 2.01, 1.98, 2.00),
        (2.00, 2.02, 1.99, 2.01),
        (2.01, 2.03, 2.00, 2.01),
        (2.01, 2.02, 1.99, 2.00),
        (2.00, 2.02, 1.99, 2.01),
        (2.02, 2.08, 2.01, 2.07) if breakout else (2.02, 2.02, 2.00, 2.01),
        (2.07, 2.40, 1.90, 2.05) if breakout else (2.01, 2.02, 2.00, 2.01),
    ]
    data = []
    for i, (o, h, l, c) in enumerate(prices):
        stamp = pd.Timestamp("2026-10-30T09:30:00-04:00") + pd.Timedelta(minutes=i)
        data.append({"t": stamp.isoformat(), "o": o, "h": h, "l": l,
                     "c": c, "v": 10000})
    return prepare_bars(data)


def test_opening_range_requires_next_bar_and_stop_wins_same_bar():
    result = backtest_opening_range(sample_bars(), slippage_bps=0, target_r=1.5)
    assert len(result) == 1
    assert result.iloc[0]["Signal time ET"] == "09:35"
    assert result.iloc[0]["Entry"] == 2.07  # next-minute open
    assert result.iloc[0]["Exit"] == 1.98  # stop even with target touched
    assert result.iloc[0]["Exit reason"] == "Stop (conservative)"
    assert result.iloc[0]["R multiple"] == -1.0


def test_no_breakout_no_trade():
    assert backtest_opening_range(sample_bars(False)).empty


def test_no_trade_on_opening_range_missing_minute():
    bars = sample_bars().drop(index=2)
    assert backtest_opening_range(bars).empty


def test_summary_empty_has_no_spurious_win_rate():
    result = trade_summary(pd.DataFrame())
    assert result["Trades"] == 0
    assert result["Win rate"] is None


def test_snapshot_rejects_wide_spread_and_preserves_penny_floor():
    assets = [{"symbol": "ZZTEST", "name": "Synthetic", "exchange": "NASDAQ"}]
    snapshot = {"ZZTEST": {
        "latestTrade": {"p": 0.25},
        "latestQuote": {"bp": 0.24, "ap": 0.26, "t": datetime.now(timezone.utc).isoformat()},
        "dailyBar": {"v": 200000},
        "prevDailyBar": {"c": 0.2}
    }}
    settings = dict(min_price=0.10, max_price=25, min_gap=5,
                    min_dollar_volume=100, max_spread=1.0)
    result = snapshot_table(assets, snapshot, settings)
    assert len(result) == 1
    assert result.iloc[0]["Price"] == 0.25
    assert result.iloc[0]["Status"] == "Exclude"
    assert "Spread too wide" in result.iloc[0]["Reason"]


def test_after_hours_recent_session_watchlist_not_live_signal():
    # 18:08 ET, with a same-day 16:00 ET trade/quote.
    now = datetime(2026, 11, 2, 23, 8, tzinfo=timezone.utc)
    asset = [{"symbol": "DEMO", "name": "Illustrative Ordinary Shares", "exchange": "NASDAQ"}]
    snapshot = {"DEMO": {
        "latestTrade": {"p": 2.40, "t": "2026-11-02T21:00:01Z"},
        "dailyBar": {"v": 100_000, "t": "2026-11-02T21:00:00Z"},
        "prevDailyBar": {"c": 2.00},
        "latestQuote": {"bp": 2.39, "ap": 2.41, "t": "2026-11-02T21:00:00Z"},
    }}
    settings = dict(min_price=0.10, max_price=25, min_gap=5,
                    min_dollar_volume=15_000, max_spread=1,
                    max_age_minutes=36 * 60, now=now)
    after_hours = snapshot_table(asset, snapshot, settings)
    assert after_hours.iloc[0]["Status"] == "Review"
    assert after_hours.iloc[0]["Price age (min)"] >= 120
    # The same data MUST NOT be marked usable by the intraday mode.
    settings["max_age_minutes"] = 10
    intraday = snapshot_table(asset, snapshot, settings)
    assert intraday.iloc[0]["Status"] == "Exclude"
    assert "too old" in intraday.iloc[0]["Reason"]


def test_missing_quote_remains_explicit_watch_not_liquid_review():
    now = datetime(2026, 11, 2, 23, 8, tzinfo=timezone.utc)
    assets = [{"symbol": "DEMO", "name": "Ordinary Shares", "exchange": "NASDAQ"}]
    snapshot = {"DEMO": {
        "latestTrade": {"p": 2.40, "t": "2026-11-02T21:00:00Z"},
        "dailyBar": {"v": 100_000},
        "prevDailyBar": {"c": 2.00},
    }}
    row = snapshot_table(assets, snapshot,
                         dict(min_price=0.10, max_price=25, min_gap=5,
                              min_dollar_volume=10000, max_spread=1,
                              max_age_minutes=2160, now=now)).iloc[0]
    assert row["Status"] == "Watch — verify quote"
    assert "Bid/ask unavailable" in row["Reason"]


def test_unlisted_instruments_removed_but_subdollar_common_stock_kept():
    from alpaca_feed import is_common_equity_asset
    common = {"symbol": "DEMO", "name": "Demo Inc. Class A Ordinary Shares",
              "exchange": "NASDAQ", "class": "us_equity",
              "status": "active", "tradable": True}
    assert is_common_equity_asset(common)
    for name in ("Demo Inc Warrant", "Demo Corp. Rights", "Demo Units",
                 "Demo Index ETF"):
        assert not is_common_equity_asset({**common, "name": name})
    assert not is_common_equity_asset({**common, "symbol": "DEMO.WS"})



def test_session_classifier_in_eastern_time_and_weekends():
    from sessions import market_session
    checks = [
        ("2026-11-03T08:59:00Z", "Closed / overnight"),  # 3:59 a.m. ET
        ("2026-11-03T09:00:00Z", "Premarket"),  # 4:00 a.m. ET
        ("2026-11-03T14:29:00Z", "Premarket"),
        ("2026-11-03T14:30:00Z", "Regular"),
        ("2026-11-03T21:00:00Z", "After-hours"),
        ("2026-11-04T00:59:00Z", "After-hours"),
        ("2026-11-04T01:00:00Z", "Closed / overnight"),
        ("2026-11-07T18:00:00Z", "Closed"),
    ]
    for stamp, expected in checks:
        assert market_session(stamp)[0] == expected, (stamp, expected)


def _bars_for_session(session_start):
    original = sample_bars()
    source = []
    base = pd.Timestamp(session_start)
    for i, row in original.iterrows():
        source.append({
            "t": (base + pd.Timedelta(minutes=i)).isoformat(),
            "o": row["open"], "h": row["high"], "l": row["low"],
            "c": row["close"], "v": row["volume"]
        })
    return prepare_bars(source)


def test_premarket_breakout_replay_never_borrows_regular_candles():
    bars = _bars_for_session("2026-10-30T04:00:00-04:00")
    premarket = backtest_opening_range(bars, session="Premarket", slippage_bps=0)
    regular = backtest_opening_range(bars, session="Regular", slippage_bps=0)
    assert len(premarket) == 1
    assert premarket.iloc[0]["Session"] == "Premarket"
    assert premarket.iloc[0]["Signal time ET"] == "04:05"
    assert regular.empty


def test_after_hours_breakout_respects_4pm_open():
    bars = _bars_for_session("2026-10-30T16:00:00-04:00")
    result = backtest_opening_range(bars, session="After-hours", slippage_bps=0)
    assert len(result) == 1
    assert result.iloc[0]["Signal time ET"] == "16:05"


def test_session_volume_vwap_resets_at_4pm():
    from sessions import session_summary, session_vwap
    regular = prepare_bars([
        {"t": "2026-10-30T13:30:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 100},
        {"t": "2026-10-30T20:00:00Z", "o": 3, "h": 3, "l": 3, "c": 3, "v": 5},
    ])
    vwaps = session_vwap(regular)
    assert vwaps.iloc[0]["session_vwap"] == 1
    assert vwaps.iloc[1]["session_vwap"] == 3
    summary = session_summary(regular)
    assert set(summary["Session"]) == {"Regular", "After-hours"}
    assert summary["Feed shares"].sum() == 105


def test_afterhours_scan_rejects_regular_trade_despite_recent_age():
    # At 4:05 p.m., a 3:59 p.m. trade is 6 minutes old, but it is NOT
    # an after-hours trade and must never pass an active-session scan.
    now = datetime(2026, 11, 2, 21, 5, tzinfo=timezone.utc)
    asset = [{"symbol": "DEMO", "name": "Demo Common Shares", "exchange": "NASDAQ"}]
    snapshot = {"DEMO": {
        "latestTrade": {"p": 2.50, "t": "2026-11-02T20:59:00Z"},
        "dailyBar": {"v": 100_000}, "prevDailyBar": {"c": 2.00},
        "latestQuote": {"bp": 2.49, "ap": 2.51, "t": "2026-11-02T20:59:00Z"},
    }}
    frame = snapshot_table(asset, snapshot, dict(
        min_price=0.10, max_price=25, min_gap=5, min_dollar_volume=10_000,
        max_spread=1, max_age_minutes=20, now=now,
        require_active_session=True,
    ))
    row = frame.iloc[0]
    assert row["Status"] == "Exclude"
    assert row["Price session ET"] == "Regular"
    assert "No price reported in active session" in row["Reason"]


def test_recent_minute_bar_outweighs_stale_trade_in_extended_hours():
    now = datetime(2026, 11, 2, 21, 31, tzinfo=timezone.utc)
    asset = [{"symbol": "DEMO", "name": "Demo Common Shares", "exchange": "NASDAQ"}]
    snapshot = {"DEMO": {
        "latestTrade": {"p": 3.00, "t": "2026-11-02T19:55:00Z"},
        "minuteBar": {"c": 3.40, "t": "2026-11-02T21:30:00Z"},
        "dailyBar": {"v": 100_000},
        "prevDailyBar": {"c": 2.50},
        "latestQuote": {"bp": 3.39, "ap": 3.41, "t": "2026-11-02T21:30:00Z"},
    }}
    frame = snapshot_table(asset, snapshot, dict(
        min_price=0.10, max_price=25, min_gap=5, min_dollar_volume=10_000,
        max_spread=1, max_age_minutes=20, now=now,
        require_active_session=True,
    ))
    row = frame.iloc[0]
    assert row["Price"] == 3.40
    assert row["Price source"] == "Minute bar"
    assert row["Price session ET"] == "After-hours"
    assert row["Matches active session"]
    assert row["Status"] == "Review"
