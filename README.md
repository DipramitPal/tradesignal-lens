# TradeSignal Lens

AI-powered Indian stock market trading bot that combines technical analysis, news sentiment, and social media trends to generate actionable trade suggestions for NSE/BSE stocks.

## Features

- **Indian Market Data** - Real-time and historical data for NSE/BSE stocks via yfinance (free, no API key needed)
- **Technical Analysis** - RSI, MACD, Bollinger Bands, EMA (12/26/50/200), ATR, ADX, VWAP, Supertrend, support/resistance, momentum, volatility
- **Live Monitoring** - Configurable interval (15-30 min) scanning with plain-English BUY/SELL/HOLD advice, ATR-based stop-loss, trailing stops, and P&L tracking
- **News Sentiment** - Financial news analysis from Google News RSS and NewsAPI with VADER-based sentiment scoring, boosted for financial terminology
- **Social Media Trends** - Reddit sentiment from Indian stock subreddits (r/IndianStockMarket, r/IndianStreetBets, etc.) with ticker extraction
- **AI-Powered Insights** - LLM analysis (Claude / GPT) that combines all signals into intelligent buy/sell/hold recommendations
- **Signal Combiner** - Weighted scoring system merging technical (70%) and sentiment (30%) signals with confidence assessment
- **Market Awareness** - IST timezone, NSE trading hours (9:15 AM - 3:30 PM), holiday calendar, market status checks
- **Budget Advisor Web UI** - Flask-based dashboard: enter a budget and risk tolerance, get suggestions across single stocks, index funds/ETFs, diversified batches, and stock+ETF hybrid mixes
- **Scheduler** - Scheduling infrastructure for autonomous monitoring aligned with market hours

## Project Structure

```
tradesignal-lens/
├── main.py                          # CLI entry point (10 commands)
├── requirements.txt                 # Python dependencies
├── .env.example                     # Environment config template
├── src/
│   ├── settings.py                  # Centralized config from .env
│   ├── fetch_data.py                # yfinance data fetcher
│   ├── feature_engineering.py       # Technical indicators (15+)
│   ├── signal_generator.py          # Advanced signal generation
│   ├── market_data/
│   │   ├── indian_market.py         # NSE/BSE data via yfinance
│   │   └── market_utils.py          # Market hours, holidays, IST utils
│   ├── quant/
│   │   └── live_monitor.py          # Live monitoring engine
│   ├── news/
│   │   ├── news_fetcher.py          # Google News RSS + NewsAPI
│   │   └── sentiment_analyzer.py    # VADER sentiment with financial boosting
│   ├── social/
│   │   └── reddit_analyzer.py       # Reddit ticker extraction & sentiment
│   ├── ai_engine/
│   │   ├── llm_analyzer.py          # Claude/GPT powered stock analysis
│   │   └── signal_combiner.py       # Multi-source signal fusion
│   ├── portfolio/
│   │   └── budget_advisor.py        # Budget-based portfolio suggestions
│   ├── web/
│   │   ├── app.py                   # Flask web application
│   │   ├── templates/index.html     # Budget advisor UI
│   │   └── static/                  # CSS & JS assets
│   └── bot/
│       ├── orchestrator.py          # Main analysis pipeline
│       └── scheduler.py             # Market-hours-aware scheduler
```

## Setup

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd tradesignal-lens

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your API keys (stock data works without any key!)
```

### API Keys

| Service | Required? | Get it from |
|---------|-----------|-------------|
| yfinance | **No key needed** | Stock data works out of the box |
| Anthropic (Claude) | Recommended | [console.anthropic.com](https://console.anthropic.com) |
| OpenAI (GPT) | Alternative | [platform.openai.com](https://platform.openai.com) |
| NewsAPI | Optional | [newsapi.org](https://newsapi.org) |
| Reddit | Optional | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) |

Stock data via yfinance requires **no API key** and has **no rate limits**. Without LLM keys the bot falls back to rule-based analysis. News uses Google News RSS by default (no key needed).

## Usage

```bash
# Download stock data
python main.py fetch                             # all watchlist stocks
python main.py fetch --symbol RELIANCE.NS        # single stock

# Analyze a single stock
python main.py analyze RELIANCE.NS

# Scan your watchlist
python main.py watchlist
python main.py watchlist --symbols "TCS.NS,INFY.NS,SBIN.NS"

# Live monitoring (the main feature!)
python main.py monitor                                          # monitor default watchlist every 15 min
python main.py monitor --symbols "RELIANCE.NS,TCS.NS" --interval 30   # custom stocks, 30-min interval
python main.py monitor --positions "RELIANCE.NS@2500,TCS.NS@3800"     # track stocks you already own
python main.py monitor --once                                   # single scan, no loop

# Daily market brief
python main.py brief

# Check market status
python main.py status

# News analysis for a stock
python main.py news RELIANCE.NS

# Trending tickers on social media
python main.py trending

# Stock info
python main.py info HDFCBANK.NS

# Save reports to data/reports/
python main.py analyze RELIANCE.NS --save
python main.py watchlist --save

# Launch the budget advisor web UI
python main.py ui
python main.py ui --port 8080
```

### Live Monitor

The `monitor` command is the primary feature for active traders. It:

1. **Fetches live data** for your stock list at a configurable interval (default: every 15 minutes)
2. **Computes 15+ technical indicators** including RSI, MACD, ADX, ATR, Supertrend, Bollinger Bands, support/resistance
3. **Assesses momentum and trend** using multiple confirming signals
4. **Tells you in plain English** what to do:
   - **BUY** — with confidence level, reasons, and where to set your stop-loss
   - **HOLD** — with updated trailing stop-loss that protects your gains
   - **SELL** — when stop-loss is hit, trend reverses, or profit targets are reached
   - **AVOID** — when a stock is in a downtrend or overbought
   - **WAIT** — when there's no clear signal

Example with positions you already hold:
```bash
python main.py monitor --symbols "RELIANCE.NS,TCS.NS,INFY.NS" \
    --positions "RELIANCE.NS@2500" --interval 15
```

The monitor tracks your entry price, calculates P&L, and automatically adjusts trailing stop-losses as the price moves in your favor.

### Budget Advisor Web UI

The web UI lets you enter an investment budget and risk tolerance, then generates four types of suggestions:

| Category | What you get |
|----------|-------------|
| **Single Stocks** | Top individual picks ranked by signal strength, with quantity and total cost |
| **Index Funds** | NSE ETFs (Nifty BeES, Bank BeES, Gold BeES, etc.) with units you can buy |
| **Batches** | Sector-diversified portfolios — conservative, balanced, and aggressive variants |
| **Mixes** | Hybrid stock + ETF allocations with configurable split ratios |

Launch with `python main.py ui` then open `http://localhost:5000` in your browser.

## How It Works

1. **Data Collection** - Fetches OHLCV data from yfinance (free, no limits), news from multiple sources, social media posts from Reddit
2. **Technical Analysis** - Computes 15+ technical indicators including ATR, ADX, Supertrend, VWAP, and generates advanced signals
3. **Sentiment Analysis** - VADER sentiment scoring enhanced with financial domain vocabulary
4. **Signal Fusion** - Weighted combination of technical (70%) and sentiment (30%) scores with confidence assessment
5. **AI Analysis** - LLM synthesizes all data into a recommendation with reasoning, risk factors, and price levels
6. **Live Monitoring** - Periodic re-scan with trailing stop-loss management and plain-English advice

## Technical Indicators

| Indicator | Purpose |
|-----------|---------|
| RSI (14) | Overbought/oversold detection |
| MACD | Momentum direction and crossovers |
| EMA 12/26 | Short-term trend |
| EMA 50/200 | Golden cross / death cross |
| Bollinger Bands | Volatility and mean reversion |
| ATR (14) | Stop-loss calculation |
| ADX (14) | Trend strength (> 25 = trending) |
| VWAP | Fair value reference |
| Supertrend | Trend direction with automatic flip detection |
| Support/Resistance | Price floor/ceiling (20-period) |
| Momentum (5-day) | Price acceleration |
| Volume Breakout | Unusual volume detection (> 2x avg) |

## Future Roadmap

- [ ] Broker API integration (Zerodha Kite, Angel One) for live order placement
- [ ] Portfolio tracking and P&L monitoring
- [ ] Telegram/Discord alerts
- [ ] Intraday analysis with 5m/15m intervals
- [ ] Options chain analysis
- [ ] FII/DII flow tracking
- [ ] Backtesting engine
- [x] Live monitoring with stop-loss tracking
- [x] Web dashboard (budget advisor UI)
- [x] yfinance migration (no API key needed)
- [x] Advanced quant indicators (ATR, ADX, Supertrend, VWAP)

## Disclaimer

This is an AI-powered analysis tool for educational and research purposes. It does **not** constitute financial advice. Always consult a SEBI-registered investment advisor before making trading decisions. Past performance of any analysis does not guarantee future results.
