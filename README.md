# TradeSignal Lens

AI-powered Indian stock market trading bot that combines technical analysis, news sentiment, and social media trends to generate actionable trade suggestions for NSE/BSE stocks.

## Features

- **Indian Market Data** - Real-time and historical data for NSE/BSE stocks via yfinance (Nifty 50 blue chips + custom watchlists)
- **Technical Analysis** - RSI, MACD, Bollinger Bands, EMA, momentum, volatility indicators with signal generation
- **News Sentiment** - Financial news analysis from Google News RSS and NewsAPI with VADER-based sentiment scoring, boosted for financial terminology
- **Social Media Trends** - Reddit sentiment from Indian stock subreddits (r/IndianStockMarket, r/IndianStreetBets, etc.) with ticker extraction
- **AI-Powered Insights** - LLM analysis (Claude / GPT) that combines all signals into intelligent buy/sell/hold recommendations
- **Signal Combiner** - Weighted scoring system merging technical (70%) and sentiment (30%) signals with confidence assessment
- **Market Awareness** - IST timezone, NSE trading hours (9:15 AM - 3:30 PM), holiday calendar, market status checks
- **Scheduler Foundation** - Pre-built scheduling infrastructure for future 24/7 autonomous bot mode

## Project Structure

```
tradesignal-lens/
├── main.py                          # CLI entry point
├── requirements.txt                 # Python dependencies
├── .env.example                     # Environment config template
├── src/
│   ├── settings.py                  # Centralized config from .env
│   ├── fetch_data.py                # Alpha Vantage fetcher (legacy)
│   ├── feature_engineering.py       # Technical indicators
│   ├── signal_generator.py          # Rule-based signal generation
│   ├── market_data/
│   │   ├── indian_market.py         # NSE/BSE data via yfinance
│   │   └── market_utils.py          # Market hours, holidays, IST utils
│   ├── news/
│   │   ├── news_fetcher.py          # Google News RSS + NewsAPI
│   │   └── sentiment_analyzer.py    # VADER sentiment with financial boosting
│   ├── social/
│   │   └── reddit_analyzer.py       # Reddit ticker extraction & sentiment
│   ├── ai_engine/
│   │   ├── llm_analyzer.py          # Claude/GPT powered stock analysis
│   │   └── signal_combiner.py       # Multi-source signal fusion
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
| Anthropic (Claude) | Recommended | [console.anthropic.com](https://console.anthropic.com) |
| OpenAI (GPT) | Alternative | [platform.openai.com](https://platform.openai.com) |
| NewsAPI | Optional | [newsapi.org](https://newsapi.org) |
| Reddit | Optional | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) |

The bot works without any API keys (using Google News RSS + rule-based analysis) but LLM integration provides significantly richer insights.

## Usage

```bash
# Analyze a single stock
python main.py analyze RELIANCE.NS

# Scan your watchlist
python main.py watchlist
python main.py watchlist --symbols "TCS.NS,INFY.NS,SBIN.NS"

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
```

## How It Works

1. **Data Collection** - Fetches OHLCV data from yfinance, news from multiple sources, social media posts from Reddit
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
- [ ] Web dashboard

## Disclaimer

This is an AI-powered analysis tool for educational and research purposes. It does **not** constitute financial advice. Always consult a SEBI-registered investment advisor before making trading decisions. Past performance of any analysis does not guarantee future results.
