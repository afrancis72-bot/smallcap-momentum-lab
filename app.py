"""Small-cap research dashboard. No real or simulated brokerage API orders."""
import os
from datetime import datetime, timezone
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from alpaca_feed import AlpacaReadOnly, DataError
from research_engine import snapshot_table, prepare_bars, vwap_bars, backtest_opening_range, trade_summary

st.set_page_config(page_title="Momentum Lab", page_icon="📈", layout="wide")
st.title("📈 Small-Cap Momentum Lab")
st.caption("Exchange-listed discovery · $0.10 floor · Source-linked news · Rule-based paper research")
st.warning("Prototype, not a live trading-alert system. Free Alpaca IEX quotes and volume represent ONE exchange, not total U.S. trading. Historical bars may lag by 15+ minutes. No real orders or guaranteed edge.")

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
    st.caption("These keys only authorize GET market data and asset discovery in this app.")
    st.divider()
    st.subheader("Discovery filters")
    min_price = st.number_input("Min price ($)", min_value=0.10, max_value=25.0, value=0.10, step=0.10)
    max_price = st.number_input("Max price ($)", min_value=0.10, max_value=100.0, value=25.0, step=1.0)
    min_gap = st.slider("Minimum move from previous close (%)", 0, 30, 5)
    min_turnover = st.number_input("Minimum IEX dollar turnover ($)", 0, 1_000_000, 15_000, 5_000)
    max_spread = st.slider("Maximum IEX spread (%)", 0.25, 10.0, 1.0, 0.25)

client = AlpacaReadOnly(key, secret, feed) if key and secret else None
if client is None:
    st.info("Enter Alpaca paper account API keys in the sidebar to activate scanning, ticker charts, and news. The CSV backtest and paper journal work without keys.")

scan_tab, ticker_tab, replay_tab, journal_tab = st.tabs(
    ["🔎 Automatic scanner", "📊 Ticker research", "🧪 Backtest", "📝 Paper journal"])

with scan_tab:
    st.subheader("Market discovery (on-demand)")
    st.write("Scans Alpaca's **active exchange-listed stock universe**, then requests price snapshots in batches. No ticker list required. Click again to refresh; there is no background scanner or automatic alerting yet.")
    if st.button("Scan exchange-listed market", type="primary", disabled=not client):
        if min_price > max_price:
            st.error("Minimum price must not exceed maximum price.")
        else:
            with st.spinner("Loading exchange-listed universe and snapshot batches..."):
                try:
                    assets = st.session_state.get("assets")
                    if assets is None:
                        assets = client.assets()
                        st.session_state["assets"] = assets
                    symbols = [a["symbol"] for a in assets]
                    snapshots, requested, errors = client.snapshots(symbols)
                    settings = {"min_price": min_price, "max_price": max_price,
                                "min_gap": min_gap, "min_dollar_volume": min_turnover,
                                "max_spread": max_spread,
                                "max_age_minutes": 25 if feed == "delayed_sip" else 10}
                    frame = snapshot_table(assets, snapshots, settings)
                    st.session_state["scan_result"] = (frame, len(symbols), requested,
                                                       len(snapshots), errors,
                                                       datetime.now(timezone.utc).isoformat(), feed)
                except DataError as exc:
                    st.error(str(exc))
    if "scan_result" in st.session_state:
        frame, universe, requested, received, errors, ts, source = st.session_state["scan_result"]
        passing = frame[frame["Status"] == "Review"] if not frame.empty else frame
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Universe", f"{universe:,}")
        c2.metric("Requested", f"{requested:,}")
        c3.metric("Received", f"{received:,}")
        c4.metric("Passing filters", f"{len(passing):,}")
        st.caption(f"Requested at {ts} UTC · {source} · Research ranking, NOT win probabilities.")
        if errors:
            st.error("Partial scan: " + "; ".join(errors[:4]))
        if received < requested or requested < universe:
            st.warning("Data incomplete: not every requested ticker returned a usable snapshot.")
        st.write("**Candidates**")
        st.dataframe(passing, use_container_width=True, hide_index=True)
        st.write("**All inspected symbols, including excluded names**")
        st.dataframe(frame, use_container_width=True, hide_index=True)
        st.download_button("Download scan CSV", frame.to_csv(index=False),
                           "smallcap_scan.csv", mime="text/csv")
    else:
        st.caption("No market scan yet. No invented candidates will be shown.")
    st.info("V1 excludes OTC/pink sheets. Exchange-listed sub-dollar stocks are supported if Alpaca supplies quotes. A large price move or high IEX volume alone is not a buy signal.")

with ticker_tab:
    st.subheader("Manual ticker research")
    ticker = st.text_input("Ticker symbol", max_chars=20).upper().strip()
    days = st.slider("Lookback (calendar days)", 2, 30, 7)
    if st.button("Load ticker", disabled=not (client and ticker)):
        try:
            snapshot, _, errors = client.snapshots([ticker])
            raw_bars, truncated = client.bars(ticker, days)
            try:
                news, news_error = client.news(ticker), ""
            except DataError as exc:
                news, news_error = [], str(exc)
            st.session_state["ticker_result"] = (ticker, snapshot.get(ticker),
                                                 raw_bars, truncated, news, errors,
                                                 news_error, feed, datetime.now(timezone.utc).isoformat())
            st.session_state["latest_bars"] = raw_bars
        except DataError as exc:
            st.error(str(exc))
    if "ticker_result" in st.session_state:
        symbol, snap, raw_bars, truncated, news, errors, news_error, source, timestamp = st.session_state["ticker_result"]
        snap = snap or {}
        trade, quote = snap.get("latestTrade") or {}, snap.get("latestQuote") or {}
        previous = snap.get("prevDailyBar") or {}
        st.caption(f"{symbol} · fetched {timestamp} UTC · feed {source}; historical bars end at least 16 minutes before request.")
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
            bars = vwap_bars(bars)
            x = bars["timestamp"].dt.tz_convert("America/New_York")
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=x, open=bars["open"], high=bars["high"],
                                         low=bars["low"], close=bars["close"], name="Candles"))
            fig.add_trace(go.Scatter(x=x, y=bars["vwap"], mode="lines", name="Session VWAP"))
            fig.update_layout(height=500, xaxis_rangeslider_visible=False,
                              xaxis_title="US Eastern time", yaxis_title="Price ($)")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("No minute bars returned; ticker may be untraded on this feed.")
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
    st.caption("Build 9:30–9:34 opening range. Enter at next minute open after first completed candle closes above both the range and VWAP. Long only; conservative stop-first rule.")
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
                                                max_hold=max_hold, slippage_bps=slip)
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
    st.caption("Important limitations: minute bars cannot reproduce quotes, actual fills, halts, gap risk, stock selection survivorship, or market impact. Backtest results are hypothetical, not forward-validated.")

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
