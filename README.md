# TradeSignal Lens

AI-powered Indian stock market trading bot that combines technical analysis, news sentiment, and social media trends to generate actionable trade suggestions for NSE/BSE stocks.

## Features

- **Indian Market Data** - Real-time and historical data for BSE stocks via Alpha Vantage (blue chips + custom watchlists)
- **Technical Analysis** - RSI, MACD, Bollinger Bands, EMA, momentum, volatility indicators with signal generation
- **News Sentiment** - Financial news analysis from Google News RSS and NewsAPI with VADER-based sentiment scoring, boosted for financial terminology
- **Social Media Trends** - Reddit sentiment from Indian stock subreddits (r/IndianStockMarket, r/IndianStreetBets, etc.) with ticker extraction
- **AI-Powered Insights** - LLM analysis (Claude / GPT) that combines all signals into intelligent buy/sell/hold recommendations
- **Signal Combiner** - Weighted scoring system merging technical (70%) and sentiment (30%) signals with confidence assessment
- **Market Awareness** - IST timezone, NSE trading hours (9:15 AM - 3:30 PM), holiday calendar, market status checks
- **Budget Advisor Web UI** - Flask-based dashboard: enter a budget and risk tolerance, get suggestions across single stocks, index funds/ETFs, diversified batches, and stock+ETF hybrid mixes
- **Scheduler Foundation** - Pre-built scheduling infrastructure for future 24/7 autonomous bot mode

## Project Structure

```
tradesignal-lens/
├── main.py                          # CLI entry point
├── requirements.txt                 # Python dependencies
├── .env.example                     # Environment config template
├── src/
│   ├── settings.py                  # Centralized config from .env
│   ├── fetch_data.py                # Alpha Vantage data fetcher
│   ├── feature_engineering.py       # Technical indicators
│   ├── signal_generator.py          # Rule-based signal generation
│   ├── market_data/
│   │   ├── indian_market.py         # BSE data via Alpha Vantage
│   │   └── market_utils.py          # Market hours, holidays, IST utils
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
│       └── scheduler.py             # Autonomous mode scheduler (future)
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
# Edit .env with your API keys
```

### Required API Keys

| Service | Required? | Get it from |
|---------|-----------|-------------|
| Alpha Vantage | **Required** | [alphavantage.co](https://www.alphavantage.co/support/#api-key) (free tier: 25 req/day) |
| Anthropic (Claude) | Recommended | [console.anthropic.com](https://console.anthropic.com) |
| OpenAI (GPT) | Alternative | [platform.openai.com](https://platform.openai.com) |
| NewsAPI | Optional | [newsapi.org](https://newsapi.org) |
| Reddit | Optional | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) |

The bot requires an Alpha Vantage API key for stock data. Without LLM keys it falls back to rule-based analysis. News uses Google News RSS by default (no key needed).

## Usage

```bash
# Download stock data
python main.py fetch                             # all watchlist stocks
python main.py fetch --symbol RELIANCE.BSE       # single stock

# Analyze a single stock
python main.py analyze RELIANCE.BSE

# Scan your watchlist
python main.py watchlist
python main.py watchlist --symbols "TCS.BSE,INFY.BSE,SBIN.BSE"

# Daily market brief
python main.py brief

# Check market status
python main.py status

# News analysis for a stock
python main.py news RELIANCE.BSE

# Trending tickers on social media
python main.py trending

# Stock info
python main.py info HDFCBANK.BSE

# Save reports to data/reports/
python main.py analyze RELIANCE.BSE --save
python main.py watchlist --save

# Launch the budget advisor web UI
python main.py ui
python main.py ui --port 8080
```

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

1. **Data Collection** - Fetches OHLCV data from Alpha Vantage, news from multiple sources, social media posts from Reddit
2. **Technical Analysis** - Computes 10+ technical indicators and generates rule-based buy/sell signals
3. **Sentiment Analysis** - VADER sentiment scoring enhanced with financial domain vocabulary
4. **Signal Fusion** - Weighted combination of technical (70%) and sentiment (30%) scores with confidence assessment
5. **AI Analysis** - LLM synthesizes all data into a recommendation with reasoning, risk factors, and price levels

## Future Roadmap

- [ ] 24/7 autonomous mode with the scheduler
- [ ] Broker API integration (Zerodha Kite, Angel One) for live order placement
- [ ] Portfolio tracking and P&L monitoring
- [ ] Telegram/Discord alerts
- [ ] Intraday analysis with 5m/15m intervals
- [ ] Options chain analysis
- [ ] FII/DII flow tracking
- [ ] Backtesting engine
- [x] Web dashboard (budget advisor UI)

## Disclaimer

This is an AI-powered analysis tool for educational and research purposes. It does **not** constitute financial advice. Always consult a SEBI-registered investment advisor before making trading decisions. Past performance of any analysis does not guarantee future results.
