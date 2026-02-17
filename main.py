#!/usr/bin/env python3
"""
TradeSignal Lens - AI-Powered Indian Stock Market Trading Bot

Usage:
    python main.py fetch                        # Download data via Alpha Vantage
    python main.py analyze RELIANCE.BSE         # Analyze a single stock
    python main.py watchlist                    # Scan full watchlist
    python main.py brief                        # Daily market brief
    python main.py trending                     # Trending tickers on social media
    python main.py news RELIANCE.BSE            # News for a stock
    python main.py status                       # Market status
    python main.py info RELIANCE.BSE            # Stock info
    python main.py ui                           # Launch budget advisor web UI
"""

import argparse
import json
import sys
import os

# Ensure src/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from settings import STOCK_SYMBOLS


def cmd_fetch(args):
    """Fetch stock data from Alpha Vantage and save to CSV."""
    from fetch_data import fetch_multiple_stocks, fetch_daily_stock_data, save_to_csv

    symbols = args.symbols.split(",") if args.symbols else STOCK_SYMBOLS

    if args.symbol:
        # Fetch a single symbol
        print(f"Fetching {args.symbol}...")
        df = fetch_daily_stock_data(args.symbol, output_size=args.output_size)
        if not df.empty:
            save_to_csv(df, args.symbol)
    else:
        # Fetch all configured symbols
        print(f"Fetching {len(symbols)} stocks from Alpha Vantage...")
        print("(15s delay between requests to respect rate limits)\n")
        fetch_multiple_stocks(symbols)

    print("\nDone. CSVs saved to data/raw/")


def cmd_analyze(args):
    """Analyze a single stock."""
    from bot.orchestrator import TradingBot

    bot = TradingBot()
    result = bot.analyze_stock(args.symbol, period=args.period)
    _print_analysis(result)

    if args.save:
        bot.save_report(result, f"analysis_{args.symbol.replace('.', '_')}")


def cmd_watchlist(args):
    """Scan the full watchlist."""
    from bot.orchestrator import TradingBot

    symbols = args.symbols.split(",") if args.symbols else None
    bot = TradingBot(symbols=symbols)

    print(f"Scanning {len(bot.symbols)} stocks...")
    results = bot.scan_watchlist(period=args.period)

    print(f"\n{'='*70}")
    print(f"  WATCHLIST SCAN RESULTS ({len(results)} stocks)")
    print(f"{'='*70}\n")

    for r in results:
        if "error" in r:
            print(f"  {r['symbol']}: ERROR - {r['error']}")
            continue

        combined = r.get("combined_signal", {})
        rec = combined.get("recommendation", "N/A")
        conf = combined.get("confidence", "N/A")
        score = combined.get("combined_score", 0)
        price = r.get("technical", {}).get("close", 0)

        direction = "+" if score > 0 else ""
        print(f"  {r['symbol']:<20} | {rec:<12} | Confidence: {conf:<6} | Score: {direction}{score:.3f} | Price: {price:.2f}")

    if args.save:
        bot.save_report(results, "watchlist_scan")


def cmd_brief(args):
    """Generate daily market brief."""
    from bot.orchestrator import TradingBot

    bot = TradingBot()
    brief = bot.daily_brief()

    print(f"\n{'='*60}")
    print(f"  DAILY MARKET BRIEF")
    print(f"{'='*60}")

    status = brief.get("market_status", {})
    print(f"\n  Time: {status.get('ist_time', 'N/A')}")
    print(f"  Market: {'OPEN' if status.get('is_open') else 'CLOSED'}")

    indices = brief.get("indices", {})
    if indices:
        print(f"\n  Indices:")
        for name, data in indices.items():
            direction = "+" if data["change_pct"] > 0 else ""
            print(f"    {name:<12} {data['close']:>10,.2f}  ({direction}{data['change_pct']:.2f}%)")

    sentiment = brief.get("market_news_sentiment", {})
    print(f"\n  Market Sentiment: {sentiment.get('overall', 'N/A')} ({sentiment.get('score', 0):.3f})")

    headlines = brief.get("top_headlines", [])
    if headlines:
        print(f"\n  Top Headlines:")
        for h in headlines:
            print(f"    - [{h['source']}] {h['title']}")

    trending = brief.get("trending_tickers", [])
    if trending and trending[0].get("ticker") != "N/A":
        print(f"\n  Trending Tickers:")
        for t in trending:
            print(f"    {t['ticker']}: {t['mentions']} mentions")

    ai_brief = brief.get("ai_brief", {})
    if ai_brief.get("status") == "success":
        print(f"\n  AI Market Brief:")
        print(f"  {ai_brief['brief']}")

    if args.save:
        bot = TradingBot()
        bot.save_report(brief, "daily_brief")


def cmd_trending(args):
    """Show trending tickers on social media."""
    from social.reddit_analyzer import RedditAnalyzer

    analyzer = RedditAnalyzer()
    trending = analyzer.get_trending_tickers(limit=args.limit)

    print(f"\n{'='*50}")
    print(f"  TRENDING TICKERS (Social Media)")
    print(f"{'='*50}\n")

    if not trending or trending[0].get("ticker") == "N/A":
        print("  Reddit API not configured.")
        print("  Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env")
        return

    for t in trending:
        print(f"  {t['ticker']:<15} | {t['mention_count']} mentions")
        for post in t.get("sample_posts", []):
            print(f"    -> {post['title'][:60]}... (score: {post['score']})")


def cmd_news(args):
    """Fetch news for a stock."""
    from news.news_fetcher import NewsFetcher
    from news.sentiment_analyzer import SentimentAnalyzer

    fetcher = NewsFetcher()
    analyzer = SentimentAnalyzer()

    print(f"\nFetching news for {args.symbol}...")
    articles = fetcher.fetch_stock_news(args.symbol, max_results=args.limit)
    sentiment = analyzer.analyze_articles(articles)

    print(f"\n{'='*60}")
    print(f"  NEWS ANALYSIS: {args.symbol}")
    print(f"{'='*60}")
    print(f"\n  Overall Sentiment: {sentiment['overall_label']} ({sentiment['overall_compound']:.3f})")
    print(f"  Articles: {sentiment['num_articles']} total | {sentiment['positive_count']} positive | {sentiment['negative_count']} negative")
    print()

    for s in sentiment.get("article_sentiments", []):
        icon = "+" if s["label"] == "positive" else ("-" if s["label"] == "negative" else "~")
        print(f"  [{icon}] [{s['source']}] {s['title']}")
        print(f"       Sentiment: {s['compound']:.3f} ({s['label']})")


def cmd_status(args):
    """Show market status."""
    from market_data.market_utils import market_status

    status = market_status()
    print(f"\n{'='*40}")
    print(f"  MARKET STATUS")
    print(f"{'='*40}")
    print(f"\n  IST Time:      {status['ist_time']}")
    print(f"  Market Open:   {'YES' if status['is_open'] else 'NO'}")
    print(f"  Trading Day:   {'YES' if status['is_trading_day'] else 'NO'}")
    print(f"  Market Hours:  {status['market_hours']}")
    print(f"  Next Open:     {status['next_open']}")


def cmd_info(args):
    """Show stock info."""
    from market_data.indian_market import IndianMarketData

    market = IndianMarketData()
    info = market.get_stock_info(args.symbol)

    print(f"\n{'='*50}")
    print(f"  STOCK INFO: {args.symbol}")
    print(f"{'='*50}")

    for key, value in info.items():
        if key == "market_cap" and isinstance(value, (int, float)) and value > 0:
            # Format in Crores for Indian audience
            crores = value / 1e7
            value = f"{crores:,.0f} Cr"
        print(f"  {key:<18} {value}")


def cmd_ui(args):
    """Launch the budget advisor web UI."""
    from web.app import create_app

    app = create_app()
    print(f"\n  TradeSignal Lens — Budget Advisor UI")
    print(f"  Running at http://localhost:{args.port}")
    print(f"  Press Ctrl+C to stop\n")
    app.run(host="0.0.0.0", port=args.port, debug=args.debug)


def _print_analysis(result: dict):
    """Pretty-print stock analysis results."""
    print(f"\n{'='*60}")
    print(f"  ANALYSIS REPORT: {result.get('symbol', 'N/A')}")
    print(f"{'='*60}")

    if "error" in result:
        print(f"\n  Error: {result['error']}")
        return

    # Stock info
    info = result.get("stock_info", {})
    if info.get("name"):
        print(f"\n  Company: {info['name']}")
        print(f"  Sector:  {info.get('sector', 'N/A')}")
        cap = info.get("market_cap", 0)
        if cap:
            print(f"  Mkt Cap: {cap/1e7:,.0f} Cr")

    # Technical
    tech = result.get("technical", {})
    if tech:
        print(f"\n  Technical Indicators:")
        print(f"    Price:      {tech.get('close', 0):.2f}")
        print(f"    RSI:        {tech.get('rsi', 0):.2f}")
        print(f"    MACD:       {tech.get('macd', 0):.4f}")
        print(f"    Signal:     {tech.get('signal', 'N/A')}")
        print(f"    Momentum:   {tech.get('momentum_5', 0):.2f}")

    # News
    news = result.get("news_sentiment", {})
    if news:
        print(f"\n  News Sentiment: {news.get('overall_label', 'N/A')} ({news.get('overall_compound', 0):.3f})")
        print(f"    Articles: {news.get('num_articles', 0)} | +{news.get('positive_count', 0)} / -{news.get('negative_count', 0)}")

    # Social
    social = result.get("social_sentiment", {})
    if social:
        print(f"\n  Social Sentiment: {social.get('sentiment', 'N/A')} ({social.get('score', 0):.3f})")
        print(f"    Posts analyzed: {social.get('posts_analyzed', 0)}")

    # Combined signal
    combined = result.get("combined_signal", {})
    if combined:
        print(f"\n  {'='*40}")
        print(f"  RECOMMENDATION: {combined.get('recommendation', 'N/A')}")
        print(f"  Confidence:     {combined.get('confidence', 'N/A')}")
        print(f"  Combined Score: {combined.get('combined_score', 0):.4f}")
        print(f"  Signal Agree:   {combined.get('signal_agreement', 'N/A')}")

    # AI Analysis
    ai = result.get("ai_analysis", {})
    if ai.get("status") == "success":
        print(f"\n  AI Analysis ({ai.get('provider', '')} / {ai.get('model', '')}):")
        print(f"  {ai.get('ai_analysis', '')}")
    elif ai.get("status") == "fallback":
        print(f"\n  Rule-Based Analysis (LLM not configured):")
        print(f"    Recommendation: {ai.get('recommendation', 'N/A')}")
        print(f"    Confidence:     {ai.get('confidence', 'N/A')}")
        for reason in ai.get("reasoning", []):
            print(f"    - {reason}")

    print(f"\n  Disclaimer: This is AI-generated analysis, not financial advice.")
    print(f"  Consult a SEBI-registered advisor before making investment decisions.")


def main():
    parser = argparse.ArgumentParser(
        description="TradeSignal Lens - AI-Powered Indian Stock Market Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py fetch                           # download data for all stocks
  python main.py fetch --symbol RELIANCE.BSE     # download one stock
  python main.py analyze RELIANCE.BSE            # analyze a stock
  python main.py watchlist --symbols "RELIANCE.BSE,TCS.BSE,INFY.BSE"
  python main.py brief
  python main.py news TCS.BSE --limit 20
  python main.py status
  python main.py info HDFCBANK.BSE
  python main.py ui                              # launch web UI
  python main.py ui --port 8080                  # custom port
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # fetch
    p_fetch = subparsers.add_parser("fetch", help="Download stock data from Alpha Vantage")
    p_fetch.add_argument("--symbol", help="Single symbol to fetch (e.g. RELIANCE.BSE)")
    p_fetch.add_argument("--symbols", help="Comma-separated symbols (overrides default)")
    p_fetch.add_argument("--output-size", default="compact", choices=["compact", "full"],
                         help="compact=100 days, full=20+ years (default: compact)")

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="Analyze a single stock")
    p_analyze.add_argument("symbol", help="Stock symbol (e.g. RELIANCE.BSE)")
    p_analyze.add_argument("--period", default="6mo", help="Data period (default: 6mo)")
    p_analyze.add_argument("--save", action="store_true", help="Save report to file")

    # watchlist
    p_watchlist = subparsers.add_parser("watchlist", help="Scan watchlist")
    p_watchlist.add_argument("--symbols", help="Comma-separated symbols (overrides default)")
    p_watchlist.add_argument("--period", default="6mo", help="Data period (default: 6mo)")
    p_watchlist.add_argument("--save", action="store_true", help="Save report to file")

    # brief
    p_brief = subparsers.add_parser("brief", help="Daily market brief")
    p_brief.add_argument("--save", action="store_true", help="Save report to file")

    # trending
    p_trending = subparsers.add_parser("trending", help="Trending tickers on social media")
    p_trending.add_argument("--limit", type=int, default=50, help="Posts to scan per subreddit")

    # news
    p_news = subparsers.add_parser("news", help="News analysis for a stock")
    p_news.add_argument("symbol", help="Stock symbol")
    p_news.add_argument("--limit", type=int, default=10, help="Max articles to fetch")

    # status
    subparsers.add_parser("status", help="Show market status")

    # info
    p_info = subparsers.add_parser("info", help="Show stock info")
    p_info.add_argument("symbol", help="Stock symbol")

    # ui
    p_ui = subparsers.add_parser("ui", help="Launch budget advisor web UI")
    p_ui.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")
    p_ui.add_argument("--debug", action="store_true", help="Enable Flask debug mode")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "fetch": cmd_fetch,
        "analyze": cmd_analyze,
        "watchlist": cmd_watchlist,
        "brief": cmd_brief,
        "trending": cmd_trending,
        "news": cmd_news,
        "status": cmd_status,
        "info": cmd_info,
        "ui": cmd_ui,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
