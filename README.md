# Small-Cap Momentum Lab

**Educational market-research prototype** for parent-supervised, small-cap and exchange-listed penny-stock study. This project is completely separate from Team AI² Pro.

## What works in this prototype

- **On-demand automatic discovery.** With Alpaca *paper-account* API keys, the app requests the active, tradable exchange-listed U.S. stock universe and batched quote/price snapshots. No manual stock-symbol list needed. Default price filter **$0.10 to $25.00**. Filters include price move, IEX dollar turnover, quote spread and quote freshness.
- **Manual ticker research.** Read-only historical 1-minute candles with *premarket, regular and after-hours* filters, session-reset VWAP, session-level volume, bid/ask and original-source headlines. Last ~15 minutes of historical bars can be unavailable on the free tier.
- **Historical replay.** A transparent, long-only 5-minute opening-range breakout paper strategy with selectable premarket, regular or after-hours session, using downloaded bars or a user-uploaded CSV.
- **Paper journal.** Record hypothetical entries/exits without any brokerage order access. Import/export CSV for a persistent backup.
- **Honest provenance.** IEX is only one exchange: the free scanner does NOT know consolidated trade volume or true whole-market relative volume, and its ranking is NOT a probability of winning.


## Zero-cost workflow — recommended

No paid data plan is needed for the following *partial-market* watchlist workflow:

1. Open [TradingView's stock screener](https://www.tradingview.com/screener/). Use the **Extended Hours** fields to identify likely premarket or postmarket movers. The screen stays on TradingView; this app does not scrape or automate its data.
2. Sign up for a **free personal Finnhub API key** at [Finnhub](https://finnhub.io/). Enter the key under "Free live watchlist" in the Streamlit app sidebar or store it in private Streamlit Secrets as `FINNHUB_API_KEY = "..."`. Never commit a key to the public repository.
3. Paste up to **40** tickers in "Zero-cost extended-hours workflow" and select **Start FREE live ticker watch**. The app displays Finnhub WebSocket trade events, checking the event's actual date, session and age. A status of "Fresh current-session print" requires a real timestamp no more than two minutes old. This is NOT consolidated SIP and quotes/bid-ask are not provided; coverage during extended hours is not guaranteed, especially for illiquid stocks.
4. Use the existing **Alpaca free IEX** snapshots or historical SIP bars more than 15 minutes old to research candidates. Free IEX does not see the whole extended-hours market.

**Free Finnhub limitation confirmed:** Finnhub's US WebSocket trade documentation describes the stream as IEX trades. IEX does not provide all 4 a.m.–8 p.m. transactions, and is inactive after 5 p.m. ET. A connected WebSocket with no fresh trades after 5 p.m. does not prove the tickers were inactive. The app provides an on-demand **Check FREE quote timestamps** diagnostic that calls Finnhub's REST quote endpoint and reports the actual source timestamp, session and age. A stale result is not a live after-hours price. No provider here has been verified to offer exhaustive free consolidated 4 a.m.–8 p.m. trades. Avoid claiming otherwise.

**Important distinction:** a free *screening website* is not an API licensed for automated extraction. Real-time complete, exchange-consolidated 4 a.m.–8 p.m. coverage could not be verified as available at $0 for use inside this app. Finnhub's free stream is a best-effort watchlist experiment, not an exhaustive real-time market scanner. It only runs while Streamlit is awake; there is no trade placement. Check each ticker's quoted bid/ask, news, corporate actions, and order-book liquidity with an authorized brokerage source before any action.

## Real-time 4 a.m.–8 p.m. market monitoring (paid SIP)

**Real-time market-wide extended-hours discovery requires Alpaca Algo Trader Plus (SIP) entitlement**; IEX is partial-market and does not operate throughout extended hours. Choosing SIP in the app cannot grant a paid subscription. A successful free IEX key test is not proof that SIP is authorized.

In the scanner, select **SIP (paid)**. Run the **Scan exchange-listed market** button once to find current-session candidates. You may enable **Auto-discover SIP movers every 90 seconds** to repeat the full-universe snapshot scan while the app page stays open; this consumes API requests and stops when Streamlit isn't running. The scan remains a *periodic snapshot*—not an exchange-wide tick-by-tick stream.

For genuine event-driven prices, use **Start real-time SIP watch**. The app connects to `wss://stream.data.alpaca.markets/v2/sip` and receives trade/quote events for the top fresh scan candidates plus any symbols you type (maximum 40). The display refreshes every three seconds. It calls a trade **LIVE** only when its timestamp is from the current Eastern session and is at most two minutes old. If nothing trades, the entry is waiting or stale; it is never replaced with an invented price or today's regular-market close. Connection denial is displayed in the app, without falling back silently to IEX.

**Setup:** Keep API keys in Streamlit Secrets, not a public GitHub file. Check that your account is authorized for the paid SIP feed; no subscription is purchased by this code. Restrict access to the deployed app and review your exchange/vendor market-data redistribution terms before sharing consolidated live quotes with anyone else. The separate 8 p.m.–4 a.m. overnight feed is not supported here. This is read-only market research, not trading automation.

## Premarket and after-hours support (Nov 2026)

**Implemented:** price-session validation in the automatic stock scanner, per-ticker session-specific historical candlestick charts, session-level OHLC/volume/VWAP summaries, and distinct opening-range backtests for premarket, regular, and after-hours.

| Stock session (New York time) | Hours | Current feature |
|---|---|---|
| Premarket | 4:00–9:29 a.m. ET | Current-session snapshot candidates and historical session research |
| Regular | 9:30 a.m.–3:59 p.m. ET | Current-session snapshot candidates and historical session research |
| After-hours | 4:00–7:59 p.m. ET | Current-session snapshot candidates and historical session research |
| Overnight / closed | 8:00 p.m.–3:59 a.m. ET | **Retrospective scan only**, not supported by the current IEX/SIP session analytics |

Alpaca offers a distinct overnight/BOATS data feed for eligible securities, but **this app does not currently connect that feed or support overnight trading**.

**Data-feed boundary that matters:** The overall US market may be active 4:00 a.m.–8:00 p.m. ET, but the **free IEX exchange feed itself operates only from 8:00 a.m. to 5:00 p.m. ET**. Thus the IEX live scanner cannot discover movers from 4–8 a.m. or 5–8 p.m. and should not be treated as a full-market early/late scanner. For those windows, the app offers **Delayed SIP** as an optional snapshot feed (if your Alpaca account permits it). Delayed SIP is approximately 15 minutes behind, is unsuitable for live execution, and may be unavailable to some accounts. The separate historical bar endpoint uses `feed=sip` with an end timestamp at least 16 minutes in the past, because `feed=delayed_sip` is not a valid historical bars feed. Live consolidated SIP requires paid data access. Historical replays based on IEX cannot validate 4 a.m. setups it never observed.

The **Automatic** freshness mode requires a timestamped price printed during the **current Eastern-time session** when that session is open, and checks its age (10 minutes in regular hours, 20 minutes in extended hours on IEX, feed-dependent). **Historical snapshot review** allows older observations but never labels them live. The scanner calculates change from Alpaca's provider-reported previous daily close, **not the 4 p.m. closing price**, and its daily volume/turnover are **not isolated to the selected extended session**. To examine actual per-session volume and price changes, use Ticker research, which partitions each 1-minute bar by Eastern-time session.

On the ticker chart choose **All sessions**, **Premarket**, **Regular**, or **After-hours**. The session summary includes each session's observed opening price, high, low, last price, volume *from the feed*, and a session-reset VWAP. In the backtest, choose the session to evaluate; the first five minute bars from 4 a.m., 9:30 a.m., or 4 p.m. must all exist, or that date has no replay signal. This is intentionally conservative: free IEX minute data can be extremely sparse outside regular hours.

**Liquidity caution:** premarket and after-hours trading can have much wider spreads, fewer available shares, gap risk, and halts. Our app neither places any orders nor guarantees that paper-trading fills could have occurred. Results need reliable consolidated data and quote-level execution modeling before any claims of an advantage.

References: [Alpaca extended hours](https://alpaca.markets/support/extended-hours-trading), [Alpaca overnight data](https://docs.alpaca.markets/us/docs/245-trading-for-trading-api).

## Start locally

Requires Python 3.11+.

~~~bash
git clone https://github.com/afrancis72-bot/smallcap-momentum-lab.git
cd smallcap-momentum-lab
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS or Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
~~~

### Data setup

1. Obtain free **paper account** API credentials from https://alpaca.markets/.
2. Either enter those credentials into the app sidebar password fields, OR copy .streamlit/secrets.toml.example to .streamlit/secrets.toml and replace the placeholders.
3. Click **Scan exchange-listed market** in the Automatic scanner tab to request the current active universe and batch snapshots. Check the coverage counters and warnings.
4. Enter a symbol in Ticker research to load a one-minute chart and linked articles.
5. Use Backtest for exploratory historical replay; use Paper journal to save hypothetical trades. Export any results before closing the browser session.

**Never commit your real API keys to GitHub.** This application only makes authenticated GET calls. It never calls a trading order endpoint.

### Host on Streamlit Community Cloud

Create a new Streamlit Cloud deployment, select this repository and its main branch, choose app.py as the entrypoint, and add the two keys in **App settings → Secrets**:

~~~toml
APCA_API_KEY_ID = "your-paper-key"
APCA_API_SECRET_KEY = "your-paper-secret"
~~~

Deployment is managed separately in Streamlit Cloud. Do not store credentials in source files or expose your private subscription through an unrestricted public app.

## Scanner and data limitations

The scanner uses GET /v2/assets?status=active&asset_class=us_equity and GET /v2/stocks/snapshots with explicit exchange feed. The default feed is free **IEX-only**. To scan more comprehensively, use SIP subscription data; delayed SIP trades off accuracy/timeliness. The app excludes OTC/pink-sheet names because a reliable OTC-wide scanner needs a dedicated data feed; exchange-listed sub-dollar symbols can qualify.

The snapshot feed may contain sparse or stale quotes, especially in very thinly traded securities; there is no guarantee of finding every moving penny stock. The filters may exclude all names outside market hours because quotes are stale. Snapshot turnover is **IEX-only**, not consolidated. A $0.01 bid/ask spread on a $0.10 share equals 10%—not a trivial transaction cost. Moving rapidly is NOT evidence of a positive expected return.

Discovery is **on-demand**, not a continuous background service or automated trade alert. No real trading, shorts, options, leverage, or order submissions.

## Backtest format

Historical CSV must contain columns t,o,h,l,c,v with t in timezone-aware ISO format (one row per minute, OHLCV price data). For example:

~~~csv
t,o,h,l,c,v
2026-10-30T13:30:00Z,2.00,2.02,1.99,2.01,12500
2026-10-30T13:31:00Z,2.01,2.03,2.00,2.02,13500
~~~

The first five minutes (9:30–9:34 Eastern) set the opening range. The first subsequent candle closing above the range and session VWAP generates a hypothetical signal. Entry occurs at the next bar's open plus assumed slippage. A predefined opening-low stop and configurable profit target are checked conservatively: stop wins if both are touched within the same minute.

This is **not** proof of any trading edge. Without consolidated tick/quote data and realistic order execution, it cannot correctly simulate bid/ask fills, stock halts, price gaps, market depth, partial fills, delistings, corporate actions, or survivorship bias. A few days of bars and one ticker provide no statistically reliable evidence. Before considering real-money use: historical-universe reconstruction, as-of news, tick-quality data, walk-forward out-of-sample tests, transaction-cost calibration, and extended paper trading are required.

## Run the small test suite

~~~bash
python -m pytest -q
~~~

## Roadmap

- Evidence-based time-adjusted consolidated RVOL and dollar liquidity
- As-of-time news and SEC filing catalyst checks
- Reliable quote-level intraday replay, halt/market-depth/slippage rules
- Cross-sectional historical universe and walk-forward evaluation
- Persistent paper journal and opt-in supervised alerts (no auto orders)
- Calibrated probability models only after a real out-of-sample sample exists

## Sources

Alpaca official documentation:
- https://docs.alpaca.markets/us/reference/get-v2-assets-1
- https://docs.alpaca.markets/us/reference/stocksnapshots-1
- https://docs.alpaca.markets/us/reference/stockbarsingle-1
- https://docs.alpaca.markets/us/reference/news-3
- https://docs.alpaca.markets/us/docs/about-market-data-api

**Research and education only. Not investment advice or a live brokerage system.**
