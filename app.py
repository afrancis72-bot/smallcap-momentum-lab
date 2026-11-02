"""Small-cap research dashboard. No real or simulated brokerage API orders."""
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from alpaca_feed import AlpacaReadOnly, DataError, is_common_equity_asset
from research_engine import snapshot_table, prepare_bars, backtest_opening_range, trade_summary
from sessions import market_session, SESSION_CLOCK, session_vwap, session_summary, feed_market_active

st.set_page_config(page_title="Momentum Lab", page_icon="📈", layout="wide")
st.title("📈 Small-Cap Momentum Lab")
st.caption("Exchange-listed discovery · $0.10 floor · 4:00 a.m.–8:00 p.m. ET session research · Paper-only")
st.warning("Research prototype, not a live trading-alert system. Premarket 4:00–9:30 a.m. ET · Regular 9:30 a.m.–4:00 p.m. · After-hours 4:00–8:00 p.m. Free IEX is partial-market data. Historical bars intentionally lag at least 16 minutes; no orders or guaranteed edge.")

def secret_value(name):
    try:
        return str(st.secrets.get(name, "") or os.getenv(name, ""))
    except Exception:
        return str(os.getenv(name, ""))

with st.sidebar:
    st.header("Alpaca paper-data connection")
    key = st.text_input("API key", type="password", value=secret_value("APCA_API_KEY_ID"))
    secret = st.text_input("Secret key", type="password", value=secret_value("APCA_API_SECRET_KEY"))
    feed_name = st.selectbox("Data feed", ["Free IEX (partial coverage)", "SIP (paid)", "Delayed SIP"])
    feed = {"Free IEX (partial coverage)": "iex", "SIP (paid)": "sip",
            "Delayed SIP": "delayed_sip"}[feed_name]
    st.caption("IEX runs 8 a.m.–5 p.m. ET, not the full 4 a.m.–8 p.m. extended session. Delayed SIP snapshots may require account permission. This app only uses GET requests.")
    if st.button("Test Alpaca keys with one IEX stock", disabled=not (key and secret)):
        try:
            test = AlpacaReadOnly(key, secret, "iex").test_iex_connection("AAPL")
            if test:
                st.success("IEX data request authenticated. Keys worked; another feed may have different permissions.")
            else:
                st.warning("Request succeeded, but no AAPL snapshot came back. The API key was not explicitly rejected.")
        except DataError as exc:
            st.error(str(exc))
    st.divider()
    st.subheader("Discovery filters")
    min_price = st.number_input("Min price ($)", min_value=0.10, max_value=25.0, value=0.10, step=0.10)
    max_price = st.number_input("Max price ($)", min_value=0.10, max_value=100.0, value=25.0, step=1.0)
    min_gap = st.slider("Minimum move from previous close (%)", 0, 30, 5)
    min_turnover = st.number_input("Minimum IEX dollar turnover ($)", 0, 1_000_000, 15_000, 5_000)
    max_spread = st.slider("Maximum IEX spread (%)", 0.25, 10.0, 1.0, 0.25)
    st.divider()
    mode = st.selectbox("Snapshot freshness mode", [
        "Automatic (recommended)",
        "Intraday only (10 min)",
        "Recent-session research (36 hours)",
    ])
    st.caption("After-hours review can show closing-session data. It is never a live trade signal.")

now_et = datetime.now(ZoneInfo("America/New_York"))
current_session, _ = market_session(now_et)
session_open = current_session in SESSION_CLOCK
if mode == "Recent-session research (36 hours)":
    max_age_minutes = 36 * 60
elif mode == "Intraday only (10 min)":
    max_age_minutes = 25 if feed == "delayed_sip" else 10
else:
    # Extended-hours quotes are often sparser than normal-session quotes.
    max_age_minutes = (25 if feed == "delayed_sip" else
                       (10 if current_session == "Regular" else 20)) if session_open else 36 * 60
require_active_session = session_open and mode != "Recent-session research (36 hours)"
feed_market_open = feed_market_active(feed, now_et)


client = AlpacaReadOnly(key, secret, feed) if key and secret else None
if client is None:
    st.info("Enter Alpaca paper account API keys in the sidebar to activate scanning, ticker charts, and news. The CSV backtest and paper journal work without keys.")

scan_tab, ticker_tab, replay_tab, journal_tab = st.tabs(
    ["🔎 Automatic scanner", "📊 Ticker research", "🧪 Backtest", "📝 Paper journal"])

with scan_tab:
    st.subheader("Market discovery (on-demand)")
    st.write("Scans Alpaca's **active exchange-listed common-stock universe**, then requests price snapshots in batches. No ticker list required. Click again to refresh; there is no background scanner or automatic alerting yet.")
    st.caption("Current session: " + current_session + " · " +
               now_et.strftime("%a %b %d, %Y %I:%M %p ET") +
               " · Filter: " + mode + " · Max price age: " + str(max_age_minutes) + " minutes.")
    if session_open and not feed_market_open:
        st.error("**This data feed is inactive during part of extended hours.** Free IEX trades only 8:00 a.m.–5:00 p.m. ET, so it CANNOT discover 4–8 a.m. or 5–8 p.m. movers. Try delayed SIP if your account permits it; a blank IEX list does not mean there is no market activity.")
    if require_active_session:
        st.info("**Active " + current_session + " session:** only observations printed during this session today can pass. An older regular-market price cannot masquerade as an after-hours mover.")
    else:
        st.info("**Historical snapshot research only:** stale and previous-session data may appear; check the Price session ET and Price age columns before interpreting results.")
    st.caption("Price change is measured from Alpaca's *previous daily bar close*, not necessarily from today's 4:00 p.m. close. Full-session shares are NOT a premarket/after-hours volume measurement.")

    if st.button("Scan exchange-listed market", type="primary", disabled=not client):
        if min_price > max_price:
            st.error("Minimum price must not exceed maximum price.")
        else:
            with st.spinner("Loading exchange-listed universe and snapshot batches..."):
                try:
                    assets = st.session_state.get("assets")
                    if assets is None:
                        assets = client.assets()
                    assets = [a for a in assets if is_common_equity_asset(a)]
                    st.session_state["assets"] = assets
                    symbols = [a["symbol"] for a in assets]
                    snapshots, requested, errors = client.snapshots(symbols)
                    settings = {"min_price": min_price, "max_price": max_price,
                                "min_gap": min_gap, "min_dollar_volume": min_turnover,
                                "max_spread": max_spread,
                                "max_age_minutes": max_age_minutes,
                                "require_active_session": require_active_session}
                    frame = snapshot_table(assets, snapshots, settings)
                    st.session_state["scan_result"] = (frame, len(symbols), requested,
                                                       len(snapshots), errors,
                                                       datetime.now(timezone.utc).isoformat(), feed)
                except DataError as exc:
                    st.error(str(exc))
    if "scan_result" in st.session_state:
        frame, universe, requested, received, errors, ts, source = st.session_state["scan_result"]
        passing = frame[frame["Status"].isin(["Review", "Watch — verify quote"])] if not frame.empty else frame
        ready = frame[frame["Status"] == "Review"] if not frame.empty else frame
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Common-stock universe", f"{universe:,}")
        c2.metric("Requested", f"{requested:,}")
        c3.metric("Received", f"{received:,}")
        c4.metric("Research candidates", f"{len(passing):,}")
        c5.metric("Quotes also verified", f"{len(ready):,}")
        st.caption(f"Requested at {ts} UTC · {source} · Research ranking, NOT win probabilities. Confirm the as-of timestamps on every candidate.")
        if errors:
            st.error("Partial scan: " + "; ".join(errors[:4]))
        if received < requested or requested < universe:
            st.warning("Data incomplete: not every requested ticker returned a usable snapshot.")
        st.write("**Research candidates**")
        st.caption("Review = price, volume, and quote filters met. Watch — verify quote = momentum screen met, but bid/ask data is unavailable or outdated. Neither is a trading recommendation.")
        st.dataframe(passing, use_container_width=True, hide_index=True)
        if passing.empty:
            st.warning("No candidates met the current price-move, turnover, data-age and spread rules. Review the exclusion reasons below; relaxing any setting does NOT establish safety or profitability.")
        if not frame.empty:
            rejected = frame[frame["Status"] == "Exclude"]
            explanations = rejected["Reason"].str.split("; ").explode().value_counts().head(7)
            if not explanations.empty:
                st.write("**Most frequent exclusion checks**")
                st.dataframe(explanations.rename_axis("Check").reset_index(name="Symbols"), use_container_width=True, hide_index=True)
        st.write("**All inspected symbols, including excluded names**")
        st.dataframe(frame, use_container_width=True, hide_index=True)
        st.download_button("Download scan CSV", frame.to_csv(index=False),
                           "smallcap_scan.csv", mime="text/csv")
    else:
        st.caption("No market scan yet. No invented candidates will be shown.")
    st.info("OTC/pink sheets are excluded. IEX may have very few premarket/after-hours prints for active stocks on other venues. This is a manual refresh—not a streaming scanner. Alpaca's separate overnight (8 p.m.–4 a.m.) service is not included.")

with ticker_tab:
    st.subheader("Manual ticker research")
    ticker = st.text_input("Ticker symbol", max_chars=20).upper().strip()
    days = st.slider("Lookback (calendar days)", 2, 30, 7)
    chart_session = st.selectbox("Chart session (Eastern Time)", [
        "All sessions (4 a.m.–8 p.m.)", "Premarket", "Regular", "After-hours"
    ])
    history_source = st.selectbox("Historical 1-minute price/volume source", [
        "Consolidated SIP (15+ min delayed)", "IEX exchange (partial market)"
    ])
    historical_feed = "sip" if history_source.startswith("Consolidated") else "iex"
    st.caption("This is independent of the scanner feed. Alpaca generally permits historical SIP data older than 15 minutes on free accounts; check data entitlements if rejected.")
    if st.button("Load ticker", disabled=not (client and ticker)):
        try:
            # Snapshot access and historical SIP access are separate entitlements.
            # Use a universally accessible IEX snapshot to avoid a delayed SIP
            # snapshot permission failure blocking available historical research.
            snapshot, _, errors = AlpacaReadOnly(key, secret, "iex").snapshots([ticker])
            raw_bars, truncated = client.bars(ticker, days, historical_feed=historical_feed)
            try:
                news, news_error = client.news(ticker), ""
            except DataError as exc:
                news, news_error = [], str(exc)
            st.session_state["ticker_result"] = (ticker, snapshot.get(ticker),
                                                 raw_bars, truncated, news, errors,
                                                 news_error, feed, datetime.now(timezone.utc).isoformat())
            st.session_state["latest_bars"] = raw_bars
            st.session_state["ticker_history_feed"] = historical_feed
        except DataError as exc:
            st.error(str(exc))
    if "ticker_result" in st.session_state:
        symbol, snap, raw_bars, truncated, news, errors, news_error, source, timestamp = st.session_state["ticker_result"]
        snap = snap or {}
        trade, quote = snap.get("latestTrade") or {}, snap.get("latestQuote") or {}
        previous = snap.get("prevDailyBar") or {}
        history_feed_used = st.session_state.get("ticker_history_feed", "iex")
        st.caption(f"{symbol} · fetched {timestamp} UTC · snapshot source: IEX · historical bars: {history_feed_used.upper()} (at least 16 minutes delayed).")
        a, b, c = st.columns(3)
        a.metric("Last IEX/SIP trade", trade.get("p", "Unavailable"))
        b.metric("Previous close", previous.get("c", "Unavailable"))
        c.metric("Bid / ask", str(quote.get("bp", "?")) + " / " + str(quote.get("ap", "?")))
        if errors or news_error:
            st.warning("; ".join(errors) + " " + news_error)
        bars = prepare_bars(raw_bars)
        if truncated:
            st.warning("Bar pagination truncated; the replay may be incomplete.")
        if not bars.empty:
            st.subheader("Premarket, regular and after-hours session breakdown")
            st.caption("All session figures are from the HISTORICAL " + history_feed_used.upper() + " feed. IEX excludes other exchanges; SIP includes consolidated market prints. Session moves are measured from each session's FIRST observed bar.")
            st.dataframe(session_summary(bars), use_container_width=True, hide_index=True)
            session_bars = session_vwap(bars)
            if chart_session == "All sessions (4 a.m.–8 p.m.)":
                plot_bars = session_bars[session_bars["session"].isin(SESSION_CLOCK)]
            else:
                plot_bars = session_bars[session_bars["session"] == chart_session]
            if plot_bars.empty:
                st.warning("No 1-minute bars in the chosen session for this symbol and feed. This doesn't prove the stock was inactive elsewhere.")
            else:
                x = plot_bars["timestamp"].dt.tz_convert("America/New_York")
                fig = go.Figure()
                fig.add_trace(go.Candlestick(x=x, open=plot_bars["open"],
                                             high=plot_bars["high"], low=plot_bars["low"],
                                             close=plot_bars["close"], name="1-minute candles"))
                fig.add_trace(go.Scatter(x=x, y=plot_bars["session_vwap"],
                                         mode="lines", name="Session VWAP (resets by session)"))
                fig.update_layout(height=500, xaxis_rangeslider_visible=False,
                                  xaxis_title="Eastern time", yaxis_title="Price ($)")
                st.plotly_chart(fig, use_container_width=True)
                st.caption("Source: Alpaca historical " + history_feed_used.upper() + " · Session VWAP resets at each session. Charts are intentionally at least 16 minutes delayed.")
        else:
            st.warning("No minute bars returned for this ticker and lookback from the selected feed.")
        st.subheader("Original-source headlines")
        for item in news[:12]:
            st.write("**" + item.get("headline", "(No headline)") + "**")
            st.caption(str(item.get("source", "Unknown")) + " · " + str(item.get("created_at", "Unknown time")))
            url = item.get("url") or ""
            if url.startswith("https://"):
                st.link_button("Read article", url)
        if not news:
            st.caption("No headlines returned; this does not prove there is no catalyst.")

with replay_tab:
    st.subheader("1-minute opening-range breakout replay")
    session_test = st.selectbox("Session to replay", ["Regular", "Premarket", "After-hours"])
    st.caption("Start of opening range (Eastern): " +
               {"Regular": "9:30 a.m.", "Premarket": "4:00 a.m.", "After-hours": "4:00 p.m."}[session_test] +
               ". Entry is assumed at NEXT bar open after first completed close above both the opening range and session-specific VWAP. Long only.")
    upload = st.file_uploader("Optional historical 1-minute CSV (t,o,h,l,c,v; t is timezone-aware)", type="csv")
    choose_csv = st.checkbox("Use uploaded CSV instead of last loaded ticker", value=True)
    col1, col2, col3 = st.columns(3)
    target_r = col1.slider("Target in R", 1.0, 4.0, 1.5, 0.25)
    max_hold = col2.slider("Maximum holding minutes", 5, 120, 45, 5)
    slip = col3.slider("Slippage per side (basis points)", 0, 100, 10, 5)
    if st.button("Run replay"):
        try:
            raw = (pd.read_csv(upload).to_dict("records") if upload and choose_csv
                   else st.session_state.get("latest_bars", []))
            if not raw:
                st.error("Load ticker history or upload a historical CSV first.")
            else:
                bars = prepare_bars(raw)
                result = backtest_opening_range(bars, target_r=target_r,
                                                max_hold=max_hold, slippage_bps=slip,
                                                session=session_test)
                st.session_state["replay_result"] = (result, trade_summary(result),
                                                      len(bars), bars["day"].nunique())
        except (ValueError, KeyError, TypeError) as exc:
            st.error(f"Replay input error: {exc}")
    if "replay_result" in st.session_state:
        result, summary, count, sessions = st.session_state["replay_result"]
        st.caption(f"{count} one-minute bars · {sessions} trading dates · {summary['Trades']} simulated trades")
        a, b, c = st.columns(3)
        a.metric("Win rate", "N/A" if summary["Win rate"] is None else str(summary["Win rate"]) + "%")
        b.metric("Average R", summary["Average R"] if summary["Average R"] is not None else "N/A")
        c.metric("Total R", summary["Total R"])
        if summary["Trades"] < 30:
            st.warning("Fewer than 30 simulated trades. There is no evidence of a reliable trading edge.")
        st.dataframe(result, use_container_width=True, hide_index=True)
        st.download_button("Export simulated trades", result.to_csv(index=False),
                           "orb_replay.csv", mime="text/csv")
    st.caption("Premarket and after-hours tests require five consecutive observed opening minutes. Sparse IEX data often means NO replay trade, which is safer than inventing one. Minute bars cannot model bid/ask execution, halts, market depth, gaps or survivorship; results are hypothetical.")

with journal_tab:
    st.subheader("Paper-trade journal")
    st.warning("Session-only record; export CSV to keep it. No connection to a trading account.")
    if "journal" not in st.session_state:
        st.session_state["journal"] = []
    with st.form("journal_form"):
        a, b, c, d = st.columns(4)
        name = a.text_input("Ticker").upper().strip()
        entry = b.number_input("Paper entry ($)", 0.0001, value=1.0, format="%.4f")
        exit_value = c.number_input("Paper exit ($)", 0.0001, value=1.0, format="%.4f")
        qty = d.number_input("Paper share quantity", 1, value=100)
        note = st.text_input("Research thesis / what went wrong?")
        submit = st.form_submit_button("Add paper trade")
    if submit:
        if not name or not all(ch.isalnum() or ch in ".-" for ch in name):
            st.error("Enter a valid ticker.")
        else:
            st.session_state["journal"].append({
                "Recorded UTC": datetime.now(timezone.utc).isoformat(),
                "Ticker": name, "Entry": entry, "Exit": exit_value,
                "Shares": qty, "Gross hypothetical PnL": round((exit_value-entry)*qty, 2),
                "Notes": note})
            st.success("Added to paper journal.")
    import_file = st.file_uploader("Restore exported journal CSV", type="csv", key="import_journal")
    if import_file and st.button("Import journal"):
        try:
            j = pd.read_csv(import_file)
            if not {"Ticker", "Entry", "Exit", "Shares"}.issubset(j.columns):
                raise ValueError("Missing journal columns")
            st.session_state["journal"] = j.to_dict("records")
        except ValueError as exc:
            st.error(str(exc))
    ledger = pd.DataFrame(st.session_state["journal"])
    if not ledger.empty:
        st.dataframe(ledger, use_container_width=True, hide_index=True)
        pnl = pd.to_numeric(ledger["Gross hypothetical PnL"], errors="coerce").sum()
        st.metric("Gross hypothetical PnL, before costs", "USD " + f"{pnl:,.2f}")
        st.download_button("Download journal CSV", ledger.to_csv(index=False),
                           "paper_journal.csv", mime="text/csv")
    else:
        st.caption("No paper trades recorded.")

st.divider()
st.caption("Educational research only · No buy/sell instructions · No live trading · Parent/guardian supervision recommended for minors.")
