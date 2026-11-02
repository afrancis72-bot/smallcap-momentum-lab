"""US equity session labels and intraday summary helpers (Eastern Time)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd

EASTERN = ZoneInfo("America/New_York")

SESSION_CLOCK = {
    "Premarket": (240, 570),    # 04:00 - 09:29 ET
    "Regular": (570, 960),      # 09:30 - 15:59 ET
    "After-hours": (960, 1200), # 16:00 - 19:59 ET
}
SESSION_ORDER = ["Premarket", "Regular", "After-hours"]


def session_from_minutes(minutes, weekday=None):
    """Return session for timestamp's Eastern clock; weekends are closed."""
    if weekday is not None and weekday >= 5:
        return "Closed"
    for label, (start, end) in SESSION_CLOCK.items():
        if start <= minutes < end:
            return label
    return "Closed / overnight"


def market_session(value=None):
    """Parse datetime or ISO timestamp and return (session, ET timestamp).

    This app deliberately does not blend Alpaca's distinct overnight/BOATS feed.
    """
    if value is None:
        value = datetime.now(EASTERN)
    elif isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return "Unknown", None
    if not isinstance(value, datetime) or value.tzinfo is None:
        return "Unknown", None
    local = value.astimezone(EASTERN)
    clock = local.hour * 60 + local.minute
    return session_from_minutes(clock, local.weekday()), local


def label_bars_by_session(bars):
    """Append session labels to timestamped prepared OHLCV bars."""
    frame = bars.copy()
    if frame.empty:
        frame["session"] = pd.Series(dtype=str)
        return frame
    if "clock" not in frame or "day" not in frame or "timestamp" not in frame:
        raise ValueError("Use prepare_bars before labeling sessions.")
    local = frame["timestamp"].dt.tz_convert(EASTERN)
    frame["session"] = [
        session_from_minutes(int(m), int(d))
        for m, d in zip(frame["clock"], local.dt.weekday)
    ]
    return frame


def session_vwap(bars):
    """VWAP is independently reset per date AND per session.

    Session volume is volume returned by the selected feed; IEX is not SIP.
    """
    frame = label_bars_by_session(bars)
    if frame.empty:
        frame["session_vwap"] = pd.Series(dtype=float)
        return frame
    valid = frame["session"].isin(SESSION_ORDER)
    groups = [frame["day"], frame["session"]]
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3
    pv = ((typical * frame["volume"]).where(valid, 0)).groupby(groups).cumsum()
    vv = frame["volume"].where(valid, 0).groupby(groups).cumsum()
    frame["session_vwap"] = (pv / vv.where(vv > 0)).where(valid)
    return frame


def session_summary(bars):
    """Daily per-session OHLC, IEX/SIP feed-specific volume, and intra-session move."""
    frame = session_vwap(bars)
    frame = frame[frame["session"].isin(SESSION_ORDER)]
    if frame.empty:
        return pd.DataFrame(columns=["Date", "Session", "Open", "High", "Low",
                                     "Close", "Move within session %", "Feed shares",
                                     "Feed dollar volume", "Last session VWAP",
                                     "Last bar ET"])
    rows = []
    for (day, session), df in frame.groupby(["day", "session"], sort=True):
        df = df.sort_values("timestamp")
        opening = float(df["open"].iloc[0])
        close = float(df["close"].iloc[-1])
        rows.append({
            "Date": str(day), "Session": session,
            "Open": round(opening, 4),
            "High": round(float(df["high"].max()), 4),
            "Low": round(float(df["low"].min()), 4),
            "Close": round(close, 4),
            "Move within session %": round(100 * (close / opening - 1), 2) if opening > 0 else None,
            "Feed shares": int(df["volume"].sum()),
            "Feed dollar volume": round(float((df["volume"] * df["close"]).sum()), 2),
            "Last session VWAP": round(float(df["session_vwap"].iloc[-1]), 4)
                                if pd.notna(df["session_vwap"].iloc[-1]) else None,
            "Last bar ET": df["timestamp"].iloc[-1].tz_convert(EASTERN).strftime("%I:%M %p"),
        })
    return pd.DataFrame(rows).sort_values(["Date", "Session"], ascending=[False, True]).reset_index(drop=True)



def feed_market_active(feed, when=None):
    """Whether the feed's exchange/session is OPERATING, not a data entitlement test.

    IEX exchange opens 8:00 a.m. and closes 5:00 p.m. ET. SIP includes
    consolidated extended-hours trading 4:00 a.m. to 8:00 p.m. ET.
    """
    session, local = market_session(when)
    if local is None or local.weekday() >= 5:
        return False
    clock = local.hour * 60 + local.minute
    if feed == "iex":
        return 480 <= clock < 1020
    if feed in {"sip", "delayed_sip"}:
        return 240 <= clock < 1200
    return False
