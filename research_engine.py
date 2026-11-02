"""Pure research calculations. No brokerage orders or trade recommendations."""
from __future__ import annotations
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import math
import pandas as pd

NY = ZoneInfo("America/New_York")


def num(value, default=None):
    try:
        f = float(value)
        return f if math.isfinite(f) else default
    except (ValueError, TypeError):
        return default


def snapshot_table(assets, snapshots, settings):
    """Process exchange-listed assets. IEX-only volumes are NEVER called consolidated RVOL."""
    rows = []
    lo, hi = settings["min_price"], settings["max_price"]
    for asset in assets:
        sym = asset.get("symbol", "")
        s = snapshots.get(sym) or {}
        trade = s.get("latestTrade") or {}
        quote = s.get("latestQuote") or {}
        daily = s.get("dailyBar") or {}
        previous = s.get("prevDailyBar") or {}
        minute = s.get("minuteBar") or {}
        price = num(trade.get("p")) or num(minute.get("c")) or num(daily.get("c"))
        prior = num(previous.get("c"))
        if price is None or prior is None or prior <= 0 or not (lo <= price <= hi):
            continue
        gap = 100 * (price / prior - 1)
        vol = num(daily.get("v"), 0)
        bid, ask = num(quote.get("bp")), num(quote.get("ap"))
        spread_pct = (100 * (ask - bid) / ((ask + bid)/2)
                      if bid and ask and ask >= bid else None)
        turnover = price * vol
        quote_time = quote.get("t") or trade.get("t") or minute.get("t") or ""
        fresh = False
        if quote_time:
            try:
                t = datetime.fromisoformat(quote_time.replace("Z", "+00:00"))
                fresh = 0 <= (datetime.now(timezone.utc) - t).total_seconds() <= settings.get("max_age_minutes", 10) * 60
            except ValueError:
                pass
        reasons = []
        if gap < settings["min_gap"]:
            reasons.append("Gap below threshold")
        if turnover < settings["min_dollar_volume"]:
            reasons.append("IEX turnover below threshold")
        if spread_pct is None:
            reasons.append("No usable two-sided IEX quote")
        elif spread_pct > settings["max_spread"]:
            reasons.append("Spread too wide")
        if not fresh:
            reasons.append("Quote/trade may be stale")
        # Deliberately NOT a winning probability, RVOL, or a buy signal.
        gap_score = min(35.0, max(0.0, gap) * 2.0)
        turn_score = min(35.0, max(0.0, math.log10(max(turnover, 1)) - 3) * 10)
        spread_score = max(0.0, 30.0 * (1 - (spread_pct or 100) / max(settings["max_spread"], 0.01)))
        score = round(gap_score + turn_score + spread_score, 1)
        rows.append({
            "Ticker": sym, "Name": asset.get("name", ""), "Exchange": asset.get("exchange", ""),
            "Price": round(price, 4), "Change %": round(gap, 2),
            "IEX day shares": int(vol), "IEX turnover $": round(turnover, 2),
            "IEX spread %": round(spread_pct, 2) if spread_pct is not None else None,
            "Quote UTC": quote_time, "Fresh <=10m": fresh,
            "Research score": score, "Status": "Review" if not reasons else "Exclude",
            "Reason": "; ".join(reasons)
        })
    if not rows:
        return pd.DataFrame(columns=["Ticker", "Price", "Change %", "Status", "Reason"])
    return pd.DataFrame(rows).sort_values(["Status", "Research score"], ascending=[False, False]).reset_index(drop=True)


def prepare_bars(raw):
    """Alpaca bar dictionaries to Eastern-time bars, deduplicated and sorted."""
    if not raw:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "day", "clock"])
    frame = pd.DataFrame(raw)
    required = {"t", "o", "h", "l", "c", "v"}
    if not required.issubset(frame.columns):
        raise ValueError("Bars must include t,o,h,l,c,v")
    frame = frame.rename(columns={"t": "timestamp", "o": "open", "h": "high",
                                  "l": "low", "c": "close", "v": "volume"})
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
    frame = frame[(frame["low"] > 0) & (frame["volume"] >= 0)]
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    local = frame["timestamp"].dt.tz_convert(NY)
    frame["day"] = local.dt.date
    frame["clock"] = local.dt.hour * 60 + local.dt.minute
    return frame


def vwap_bars(bars):
    bars = bars.copy()
    if bars.empty:
        bars["vwap"] = pd.Series(dtype=float)
        return bars
    # Session VWAP resets at 9:30 ET; premarket volume must not bias it.
    regular = bars["clock"].between(570, 960)
    typical = (bars["high"] + bars["low"] + bars["close"]) / 3
    cum_pv = ((typical * bars["volume"]).where(regular, 0)).groupby(bars["day"]).cumsum()
    cum_v = bars["volume"].where(regular, 0).groupby(bars["day"]).cumsum()
    bars["vwap"] = (cum_pv / cum_v.where(cum_v > 0)).where(regular)
    return bars


def backtest_opening_range(bars, target_r=1.5, max_hold=45, slippage_bps=10,
                           fee_per_side=0.0, min_bars=6):
    """Conservative 1-minute-bar ORB replay, LONG paper trades only.

    First 5 min (9:30 through 9:34) establish opening high and low.
    Signal: subsequent completed bar closes strictly above the opening high AND VWAP.
    Entry: NEXT bar open with positive slippage.
    Stop: opening range low. Target: entry + target_r * initial risk.
    If stop & target touch the SAME minute, STOP wins. Overnight positions forbidden.
    No fills on days where the required bars are missing. Not a tick-level execution model.
    """
    if bars.empty:
        return pd.DataFrame()
    frame = vwap_bars(bars)
    trades = []
    for date, day in frame.groupby("day", sort=True):
        d = day[(day["clock"] >= 570) & (day["clock"] <= 960)].reset_index(drop=True)
        opening = d[(d["clock"] >= 570) & (d["clock"] <= 574)]
        if len(opening) != 5 or sorted(opening["clock"].tolist()) != list(range(570, 575)):
            continue
        opening_high = float(opening["high"].max())
        opening_low = float(opening["low"].min())
        if opening_low <= 0 or opening_high <= opening_low:
            continue
        for i in range(5, len(d) - 1):
            signal = d.iloc[i]
            if (signal["clock"] > 690 or signal["close"] <= opening_high
                or pd.isna(signal["vwap"]) or signal["close"] <= signal["vwap"]):
                continue
            prior = d.iloc[i - 1]
            if prior["close"] > opening_high:
                continue  # first crossing only; no later chasing
            entry_bar = d.iloc[i + 1]
            if entry_bar["clock"] != signal["clock"] + 1:
                continue
            entry = float(entry_bar["open"]) * (1 + slippage_bps / 10000)
            risk = entry - opening_low
            if risk <= 0:
                continue
            stop = opening_low
            target = entry + risk * target_r
            exit_price, exit_reason, last = None, None, None
            for j in range(i + 1, min(len(d), i + 1 + max_hold)):
                bar = d.iloc[j]
                if j > i + 1 and bar["clock"] != d.iloc[j - 1]["clock"] + 1:
                    exit_reason = "Data gap"
                    break
                last = bar
                if bar["low"] <= stop:
                    exit_price, exit_reason = stop * (1 - slippage_bps / 10000), "Stop (conservative)"
                    break
                if bar["high"] >= target:
                    exit_price, exit_reason = target * (1 - slippage_bps / 10000), "Target"
                    break
            if exit_price is None and last is not None:
                exit_price = float(last["close"]) * (1 - slippage_bps / 10000)
                exit_reason = exit_reason or "Timed exit"
            if exit_price is None:
                break
            pnl = exit_price - entry - 2 * fee_per_side
            trades.append({
                "Date": str(date), "Signal time ET": f"{int(signal['clock']//60):02d}:{int(signal['clock']%60):02d}",
                "Entry": round(entry, 5), "Exit": round(exit_price, 5),
                "Stop": round(stop, 5), "Target": round(target, 5),
                "Net P&L / share": round(pnl, 5),
                "R multiple": round(pnl / risk, 3), "Exit reason": exit_reason,
            })
            break  # at most one entry each symbol/day
    return pd.DataFrame(trades)


def trade_summary(trades):
    if trades.empty:
        return {"Trades": 0, "Win rate": None, "Average R": None,
                "Profit factor": None, "Worst R": None, "Total R": 0.0}
    r = pd.to_numeric(trades["R multiple"], errors="coerce").dropna()
    wins, losses = r[r > 0].sum(), -r[r < 0].sum()
    return {"Trades": len(r), "Win rate": round(100 * (r > 0).mean(), 1),
            "Average R": round(float(r.mean()), 3),
            "Profit factor": round(float(wins / losses), 3) if losses > 0 else None,
            "Worst R": round(float(r.min()), 3), "Total R": round(float(r.sum()), 3)}
