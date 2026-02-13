"""
Main trading bot orchestrator.
Ties together market data, news, social, and AI analysis
into a unified workflow for Indian stock market analysis.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import STOCK_SYMBOLS, REPORTS_DIR


class TradingBot:
    """Orchestrates the full analysis pipeline."""

    def __init__(self, symbols: list[str] | None = None):
        self.symbols = symbols or STOCK_SYMBOLS
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        # Lazy-loaded components
        self._market_data = None
        self._news_fetcher = None
        self._sentiment_analyzer = None
        self._reddit_analyzer = None
        self._llm_analyzer = None
        self._signal_combiner = None

    @property
    def market_data(self):
        if self._market_data is None:
            from market_data.indian_market import IndianMarketData
            self._market_data = IndianMarketData(self.symbols)
        return self._market_data

    @property
    def news_fetcher(self):
        if self._news_fetcher is None:
            from news.news_fetcher import NewsFetcher
            self._news_fetcher = NewsFetcher()
        return self._news_fetcher

    @property
    def sentiment_analyzer(self):
        if self._sentiment_analyzer is None:
            from news.sentiment_analyzer import SentimentAnalyzer
            self._sentiment_analyzer = SentimentAnalyzer()
        return self._sentiment_analyzer

    @property
    def reddit_analyzer(self):
        if self._reddit_analyzer is None:
            from social.reddit_analyzer import RedditAnalyzer
            self._reddit_analyzer = RedditAnalyzer()
        return self._reddit_analyzer

    @property
    def llm_analyzer(self):
        if self._llm_analyzer is None:
            from ai_engine.llm_analyzer import LLMAnalyzer
            self._llm_analyzer = LLMAnalyzer()
        return self._llm_analyzer

    @property
    def signal_combiner(self):
        if self._signal_combiner is None:
            from ai_engine.signal_combiner import SignalCombiner
            self._signal_combiner = SignalCombiner()
        return self._signal_combiner

    def analyze_stock(self, symbol: str, period: str = "6mo") -> dict:
        """
        Run full analysis pipeline for a single stock.

        Returns comprehensive analysis combining technical indicators,
        news sentiment, social sentiment, and AI-generated insights.
        """
        print(f"\n{'='*60}")
        print(f"  ANALYZING: {symbol}")
        print(f"{'='*60}")

        result = {"symbol": symbol, "timestamp": datetime.now().isoformat()}

        # 1. Fetch market data
        print("\n[1/5] Fetching market data...")
        df = self.market_data.fetch_stock(symbol, period=period)
        if df.empty:
            result["error"] = "No market data available"
            return result

        # 2. Add technical indicators
        print("[2/5] Computing technical indicators...")
        from feature_engineering import add_technical_indicators
        df_tech = add_technical_indicators(df.copy())

        # Get latest row as the current state
        latest = df_tech.iloc[-1]
        technical_data = {
            "close": float(latest["close"]),
            "rsi": float(latest.get("rsi", 50)),
            "macd": float(latest.get("macd", 0)),
            "macd_signal": float(latest.get("macd_signal", 0)),
            "macd_hist": float(latest.get("macd_hist", 0)),
            "bb_high": float(latest.get("bb_high", 0)),
            "bb_low": float(latest.get("bb_low", 0)),
            "momentum_5": float(latest.get("momentum_5", 0)),
            "volume": float(latest.get("volume", 0)),
            "ema_12": float(latest.get("ema_12", 0)),
            "ema_26": float(latest.get("ema_26", 0)),
        }

        # Generate signal from existing signal_generator
        from signal_generator import generate_signals
        df_signals = generate_signals(df_tech.copy())
        latest_signal = df_signals.iloc[-1].get("Signal", "Hold")
        technical_data["signal"] = latest_signal
        result["technical"] = technical_data

        # 3. Fetch and analyze news
        print("[3/5] Analyzing news sentiment...")
        stock_info = self.market_data.get_stock_info(symbol)
        company_name = stock_info.get("name", "")
        articles = self.news_fetcher.fetch_stock_news(symbol, company_name)
        news_sentiment = self.sentiment_analyzer.analyze_articles(articles)
        result["news_sentiment"] = {
            "overall_compound": news_sentiment["overall_compound"],
            "overall_label": news_sentiment["overall_label"],
            "num_articles": news_sentiment["num_articles"],
            "positive_count": news_sentiment["positive_count"],
            "negative_count": news_sentiment["negative_count"],
        }

        # 4. Social media sentiment
        print("[4/5] Analyzing social media sentiment...")
        social_sentiment = self.reddit_analyzer.get_stock_sentiment(symbol)
        result["social_sentiment"] = {
            "sentiment": social_sentiment.get("sentiment", "neutral"),
            "score": social_sentiment.get("score", 0.0),
            "posts_analyzed": social_sentiment.get("posts_analyzed", 0),
        }

        # 5. Combine signals + AI analysis
        print("[5/5] Generating AI-powered analysis...")
        combined = self.signal_combiner.combine(
            technical_data, news_sentiment, social_sentiment
        )
        result["combined_signal"] = combined

        # LLM deep analysis
        ai_analysis = self.llm_analyzer.analyze_stock(
            symbol, technical_data, news_sentiment, social_sentiment, stock_info
        )
        result["ai_analysis"] = ai_analysis

        # Stock info
        result["stock_info"] = stock_info

        return result

    def scan_watchlist(self, period: str = "6mo") -> list[dict]:
        """Run analysis on all stocks in the watchlist."""
        results = []
        for symbol in self.symbols:
            try:
                analysis = self.analyze_stock(symbol, period=period)
                results.append(analysis)
            except Exception as e:
                print(f"Error analyzing {symbol}: {e}")
                results.append({"symbol": symbol, "error": str(e)})

        # Sort by combined score (strongest signals first)
        results.sort(
            key=lambda x: abs(x.get("combined_signal", {}).get("combined_score", 0)),
            reverse=True,
        )

        return results

    def daily_brief(self) -> dict:
        """Generate a daily market brief with trending stocks and analysis."""
        from market_data.market_utils import market_status

        print("\n" + "=" * 60)
        print("  DAILY MARKET BRIEF")
        print("=" * 60)

        status = market_status()
        print(f"\nMarket Status: {'OPEN' if status['is_open'] else 'CLOSED'}")
        print(f"Time: {status['ist_time']}")

        # Fetch index data
        print("\nFetching index data...")
        indices = self.market_data.fetch_indices(period="5d")
        index_summary = {}
        for name, df in indices.items():
            if not df.empty:
                latest = df.iloc[-1]
                prev = df.iloc[-2] if len(df) > 1 else latest
                change_pct = ((latest["close"] - prev["close"]) / prev["close"]) * 100
                index_summary[name] = {
                    "close": round(float(latest["close"]), 2),
                    "change_pct": round(float(change_pct), 2),
                }

        # Trending tickers from social media
        print("Scanning social media trends...")
        trending = self.reddit_analyzer.get_trending_tickers()

        # Market news
        print("Fetching market news...")
        news = self.news_fetcher.fetch_market_news()
        news_sentiment = self.sentiment_analyzer.analyze_articles(news)

        brief = {
            "timestamp": datetime.now().isoformat(),
            "market_status": status,
            "indices": index_summary,
            "market_news_sentiment": {
                "overall": news_sentiment["overall_label"],
                "score": news_sentiment["overall_compound"],
            },
            "trending_tickers": [
                {"ticker": t["ticker"], "mentions": t["mention_count"]}
                for t in trending[:10]
            ],
            "top_headlines": [
                {"title": n["title"], "source": n["source"]}
                for n in news[:5]
            ],
        }

        # AI-generated brief
        ai_brief = self.llm_analyzer.generate_market_brief(
            index_summary, trending, news
        )
        brief["ai_brief"] = ai_brief

        return brief

    def save_report(self, data: dict | list, report_name: str = "analysis"):
        """Save analysis results to a JSON report."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{report_name}_{timestamp}.json"
        filepath = REPORTS_DIR / filename

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, default=str)

        print(f"\nReport saved to: {filepath}")
        return filepath
