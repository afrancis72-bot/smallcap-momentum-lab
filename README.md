# Small-Cap Momentum Lab

**Private educational market-research prototype** for parent-supervised, small-cap and exchange-listed penny-stock study. This project is completely separate from Team AI² Pro.

## What works in this prototype

- **On-demand automatic discovery.** With Alpaca *paper-account* API keys, the app requests the active, tradable exchange-listed U.S. stock universe and batched quote/price snapshots. No manual stock-symbol list needed. Default price filter **$0.10 to $25.00**. Filters include price move, IEX dollar turnover, quote spread and quote freshness.
- **Manual ticker research.** Read-only historical 1-minute candles, VWAP, bid/ask and original-source headlines. Last ~15 minutes of historical bars can be unavailable on the free tier.
- **Historical replay.** A transparent, long-only 5-minute opening-range breakout paper strategy using downloaded bars or a user-uploaded CSV.
- **Paper journal.** Record hypothetical entries/exits without any brokerage order access. Import/export CSV for a persistent backup.
- **Honest provenance.** IEX is only one exchange: the free scanner does NOT know consolidated trade volume or true whole-market relative volume, and its ranking is NOT a probability of winning.

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

The repo itself is **not deployed**. The private repository may require granting Streamlit Cloud GitHub access. Do not store credentials in source files.

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
