#!/usr/bin/env python3
"""
TradeSignal Lens - AI-Powered Indian Stock Market Trading Bot

Usage:
    python main.py fetch                        # Download data via yfinance
    python main.py analyze RELIANCE.NS          # Analyze a single stock
    python main.py watchlist                    # Scan full watchlist
    python main.py monitor                      # Live monitoring with buy/sell/SL advice
    python main.py scan                         # One-shot full quant scan (15m + daily MTF)
    python main.py portfolio                    # View your portfolio
    python main.py portfolio add RELIANCE.NS 10 2500
    python main.py portfolio remove RELIANCE.NS
    python main.py brief                        # Daily market brief
    python main.py trending                     # Trending tickers on social media
    python main.py news RELIANCE.NS             # News for a stock
    python main.py status                       # Market status
    python main.py info RELIANCE.NS             # Stock info
    python main.py ui                           # Launch budget advisor web UI
"""

import argparse
import json
import sys
import os

# Ensure src/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from settings import STOCK_SYMBOLS, MONITOR_SYMBOLS, MONITOR_INTERVAL_MINUTES, DEFAULT_ACCOUNT_VALUE, SCAN_UNIVERSE


def cmd_fetch(args):
    """Fetch stock data from yfinance and save to CSV."""
    from fetch_data import fetch_multiple_stocks, fetch_daily_stock_data, save_to_csv

    symbols = args.symbols.split(",") if args.symbols else STOCK_SYMBOLS

    if args.symbol:
        # Fetch a single symbol
        print(f"Fetching {args.symbol}...")
        df = fetch_daily_stock_data(args.symbol, period=args.period)
        if not df.empty:
            save_to_csv(df, args.symbol)
    else:
        # Fetch all configured symbols
        print(f"Fetching {len(symbols)} stocks from yfinance...")
        print("(No rate limit — yfinance is free and unlimited)\n")
        fetch_multiple_stocks(symbols, period=args.period)

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


def cmd_monitor(args):
    """Live monitoring with buy/sell/hold/stop-loss advice."""
    from quant.live_monitor import LiveMonitor

    symbols = args.symbols.split(",") if args.symbols else MONITOR_SYMBOLS
    interval = args.interval or MONITOR_INTERVAL_MINUTES

    monitor = LiveMonitor(symbols=symbols, interval_minutes=interval)

    # Add any pre-existing positions
    if args.positions:
        for pos_str in args.positions.split(","):
            parts = pos_str.strip().split("@")
            if len(parts) == 2:
                sym = parts[0].strip()
                price = float(parts[1].strip())
                monitor.add_position(sym, price)

    if args.once:
        # Single scan, no loop
        monitor.run_once()
    else:
        # Continuous monitoring
        monitor.start()


def cmd_scan(args):
    """One-shot full quant scan using 15m + daily MTF pipeline."""
    from quant.live_monitor import LiveMonitor
    from quant.universe_scanner import UniverseScanner
    from portfolio.portfolio_manager import PortfolioManager

    account = getattr(args, 'account', DEFAULT_ACCOUNT_VALUE)
    use_universe = getattr(args, 'universe', False)

    # Load portfolio to use account value
    portfolio = PortfolioManager()
    if portfolio.account_value and portfolio.account_value != DEFAULT_ACCOUNT_VALUE:
        account = portfolio.account_value

    if use_universe:
        print("\n  Running universe pre-screen...")
        scanner = UniverseScanner()
        from market_data.data_cache import DataCache
        cache = DataCache()
        cache.warm_cache(SCAN_UNIVERSE[:50], daily_period='1mo', intraday_days=2)
        passed = scanner.scan_lightweight(cache.daily_cache)
        symbols = passed[:20] if passed else MONITOR_SYMBOLS
        print(f"  Using {len(symbols)} symbols from universe scan")
    else:
        symbols = args.symbols.split(",") if args.symbols else MONITOR_SYMBOLS

    monitor = LiveMonitor(symbols=symbols, account_value=account)
    # Portfolio positions auto-loaded by LiveMonitor
    results = monitor.run_once()
    print(f"\n  Scan complete. {len(results)} symbols analyzed.")


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


def cmd_advisor(args):
    """Portfolio intelligence advisor — TSL, averaging, tax harvest."""
    from portfolio.portfolio_advisor import PortfolioAdvisor

    advisor = PortfolioAdvisor()

    section = getattr(args, 'section', 'all')
    force = getattr(args, 'force', False)

    if section in ('all', 'tsl'):
        advisor.print_tsl_advice()

    if section in ('all', 'average'):
        advisor.print_averaging_advice(force_override=force)

    if section in ('all', 'harvest'):
        advisor.print_tax_harvest()


def cmd_weekly_report(args):
    """Weekly portfolio performance summary."""
    from portfolio.portfolio_advisor import PortfolioAdvisor

    advisor = PortfolioAdvisor()
    advisor.print_weekly_report()

    if getattr(args, 'save', False):
        filepath = advisor.save_weekly_report()
        if filepath:
            print(f"\n  Report saved to: {filepath}")
        else:
            print(f"\n  Could not save report (portfolio empty).")


def cmd_portfolio(args):
    """Manage your stock portfolio."""
    from portfolio.portfolio_manager import PortfolioManager

    portfolio = PortfolioManager()
    action = getattr(args, 'portfolio_action', None)

    if action == 'add':
        symbol = args.symbol
        qty = args.qty
        price = args.price
        sl = getattr(args, 'sl', 0) or 0
        target = getattr(args, 'target', 0) or 0
        notes = getattr(args, 'notes', '') or ''

        portfolio.add_holding(
            symbol=symbol, qty=qty, avg_price=price,
            stop_loss=sl, target=target, notes=notes,
        )
        invested = qty * price
        print(f"\n  Added: {symbol} | {qty} shares @ Rs.{price:,.2f} = Rs.{invested:,.0f}")
        if sl > 0:
            print(f"  SL: Rs.{sl:.2f}")
        if target > 0:
            print(f"  Target: Rs.{target:.2f}")
        print(f"  Total portfolio: {len(portfolio.holdings)} stocks")

    elif action == 'remove':
        symbol = args.symbol
        if portfolio.remove_holding(symbol):
            print(f"\n  Removed: {symbol}")
            print(f"  Remaining: {len(portfolio.holdings)} stocks")
        else:
            print(f"\n  {symbol} not found in portfolio.")

    elif action == 'update':
        symbol = args.symbol
        updates = {}
        if args.qty is not None:
            updates['qty'] = args.qty
        if args.price is not None:
            updates['avg_price'] = args.price
        if args.sl is not None:
            updates['stop_loss'] = args.sl
        if args.target is not None:
            updates['target'] = args.target
        if args.notes is not None:
            updates['notes'] = args.notes

        if portfolio.update_holding(symbol, **updates):
            print(f"\n  Updated: {symbol}")
            h = portfolio.get_holding(symbol)
            print(f"  Qty: {h['qty']} | Price: Rs.{h['avg_price']:,.2f} | "
                  f"SL: {h.get('stop_loss', 0):.2f} | Target: {h.get('target', 0):.2f}")
        else:
            print(f"\n  {symbol} not found in portfolio.")

    elif action == 'set-account':
        portfolio.set_account_value(args.value)
        print(f"\n  Account value set to Rs.{args.value:,.0f}")
        print(f"  Invested: Rs.{portfolio.get_total_invested():,.0f}")
        print(f"  Available: Rs.{portfolio.get_available_capital():,.0f}")

    else:
        # Default: show portfolio
        # Optionally fetch live prices
        current_prices = {}
        if not portfolio.is_empty():
            try:
                import yfinance as yf
                symbols = portfolio.get_symbols()
                print("\n  Fetching live prices...")
                for sym in symbols:
                    try:
                        ticker = yf.Ticker(sym)
                        hist = ticker.history(period='1d')
                        if not hist.empty:
                            current_prices[sym] = float(hist['Close'].iloc[-1])
                    except Exception:
                        pass
            except ImportError:
                pass
        portfolio.print_portfolio(current_prices=current_prices if current_prices else None)


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
        print(f"    Price:       {tech.get('close', 0):.2f}")
        print(f"    RSI:         {tech.get('rsi', 0):.2f}")
        print(f"    MACD:        {tech.get('macd', 0):.4f}")
        print(f"    Signal:      {tech.get('signal', 'N/A')}")
        print(f"    Momentum:    {tech.get('momentum_5', 0):.2f}")
        print(f"    ADX:         {tech.get('adx', 0):.1f}")
        print(f"    ATR:         {tech.get('atr', 0):.2f}")
        st = "Bullish" if tech.get("supertrend_direction", 0) == 1 else "Bearish"
        print(f"    Supertrend:  {st}")
        print(f"    Support:     {tech.get('support', 0):.2f}")
        print(f"    Resistance:  {tech.get('resistance', 0):.2f}")

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
  python main.py fetch --symbol RELIANCE.NS      # download one stock
  python main.py analyze RELIANCE.NS             # analyze a stock
  python main.py watchlist --symbols "RELIANCE.NS,TCS.NS,INFY.NS"
  python main.py monitor                         # live monitor (every 15 min)
  python main.py monitor --interval 30           # custom interval
  python main.py monitor --symbols "RELIANCE.NS,TCS.NS" --once
  python main.py portfolio                       # view portfolio
  python main.py portfolio add RELIANCE.NS 10 2500.00
  python main.py portfolio add TCS.NS 5 3800 --sl 3700 --target 4200
  python main.py portfolio remove RELIANCE.NS
  python main.py portfolio update TCS.NS --qty 10 --sl 3650
  python main.py portfolio set-account 500000    # set account value
  python main.py scan                            # scan uses portfolio
  python main.py brief
  python main.py news TCS.NS --limit 20
  python main.py status
  python main.py info HDFCBANK.NS
  python main.py ui                              # launch web UI
  python main.py ui --port 8080                  # custom port
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # fetch
    p_fetch = subparsers.add_parser("fetch", help="Download stock data from yfinance")
    p_fetch.add_argument("--symbol", help="Single symbol to fetch (e.g. RELIANCE.NS)")
    p_fetch.add_argument("--symbols", help="Comma-separated symbols (overrides default)")
    p_fetch.add_argument("--period", default="1y",
                         help="Data period: 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,max (default: 1y)")

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="Analyze a single stock")
    p_analyze.add_argument("symbol", help="Stock symbol (e.g. RELIANCE.NS)")
    p_analyze.add_argument("--period", default="6mo", help="Data period (default: 6mo)")
    p_analyze.add_argument("--save", action="store_true", help="Save report to file")

    # watchlist
    p_watchlist = subparsers.add_parser("watchlist", help="Scan watchlist")
    p_watchlist.add_argument("--symbols", help="Comma-separated symbols (overrides default)")
    p_watchlist.add_argument("--period", default="6mo", help="Data period (default: 6mo)")
    p_watchlist.add_argument("--save", action="store_true", help="Save report to file")

    # monitor
    p_monitor = subparsers.add_parser("monitor", help="Live monitoring with trading advice")
    p_monitor.add_argument("--symbols", help="Comma-separated symbols to monitor")
    p_monitor.add_argument("--interval", type=int, default=None,
                           help=f"Refresh interval in minutes (default: {MONITOR_INTERVAL_MINUTES})")
    p_monitor.add_argument("--positions",
                           help='Stocks you already own: "SYM@price,SYM@price" (e.g. "RELIANCE.NS@2500")')
    p_monitor.add_argument("--once", action="store_true",
                           help="Run a single scan instead of continuous monitoring")

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

    # scan
    p_scan = subparsers.add_parser("scan", help="One-shot full quant scan (15m + daily MTF)")
    p_scan.add_argument("--symbols", type=str, default="",
                        help="Comma-separated list of symbols to scan")
    p_scan.add_argument("--universe", action="store_true",
                        help="Enable dynamic universe scanning (NIFTY 200 pre-screen)")
    p_scan.add_argument("--account", type=float, default=DEFAULT_ACCOUNT_VALUE,
                        help=f"Account value for position sizing (default: {DEFAULT_ACCOUNT_VALUE:.0f})")

    # ui
    p_ui = subparsers.add_parser("ui", help="Launch budget advisor web UI")
    p_ui.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")
    p_ui.add_argument("--debug", action="store_true", help="Enable Flask debug mode")

    # advisor
    p_advisor = subparsers.add_parser("advisor", help="Portfolio intelligence advisor")
    p_advisor.add_argument("--section", choices=["all", "tsl", "average", "harvest"],
                           default="all", help="Which advisor section to show (default: all)")
    p_advisor.add_argument("--force", action="store_true",
                           help="Override downtrend safety gate for averaging (with warnings)")

    # weekly-report
    p_weekly = subparsers.add_parser("weekly-report", help="Weekly portfolio performance summary")
    p_weekly.add_argument("--save", action="store_true", help="Save report to data/reports/")

    # portfolio
    p_portfolio = subparsers.add_parser("portfolio", help="Manage your stock portfolio")
    portfolio_sub = p_portfolio.add_subparsers(dest="portfolio_action")

    # portfolio add
    p_pf_add = portfolio_sub.add_parser("add", help="Add a stock to portfolio")
    p_pf_add.add_argument("symbol", help="Stock symbol (e.g. RELIANCE.NS)")
    p_pf_add.add_argument("qty", type=int, help="Number of shares")
    p_pf_add.add_argument("price", type=float, help="Average buy price")
    p_pf_add.add_argument("--sl", type=float, default=0, help="Stop-loss price")
    p_pf_add.add_argument("--target", type=float, default=0, help="Target price")
    p_pf_add.add_argument("--notes", type=str, default="", help="Trade notes")

    # portfolio remove
    p_pf_rm = portfolio_sub.add_parser("remove", help="Remove a stock from portfolio")
    p_pf_rm.add_argument("symbol", help="Stock symbol to remove")

    # portfolio update
    p_pf_up = portfolio_sub.add_parser("update", help="Update a holding")
    p_pf_up.add_argument("symbol", help="Stock symbol")
    p_pf_up.add_argument("--qty", type=int, default=None, help="New quantity")
    p_pf_up.add_argument("--price", type=float, default=None, help="New avg price")
    p_pf_up.add_argument("--sl", type=float, default=None, help="New stop-loss")
    p_pf_up.add_argument("--target", type=float, default=None, help="New target")
    p_pf_up.add_argument("--notes", type=str, default=None, help="Update notes")

    # portfolio set-account
    p_pf_acc = portfolio_sub.add_parser("set-account", help="Set total account value")
    p_pf_acc.add_argument("value", type=float, help="Account value in Rs")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "fetch": cmd_fetch,
        "analyze": cmd_analyze,
        "watchlist": cmd_watchlist,
        "monitor": cmd_monitor,
        "scan": cmd_scan,
        "brief": cmd_brief,
        "trending": cmd_trending,
        "news": cmd_news,
        "status": cmd_status,
        "info": cmd_info,
        "ui": cmd_ui,
        "portfolio": cmd_portfolio,
        "advisor": cmd_advisor,
        "weekly-report": cmd_weekly_report,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
