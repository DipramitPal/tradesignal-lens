"""
Reddit sentiment analyzer for Indian stock market discussions.
Monitors relevant subreddits for stock mentions, sentiment, and trending tickers.
"""

import os
import re
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import (
    REDDIT_CLIENT_ID,
    REDDIT_CLIENT_SECRET,
    REDDIT_USER_AGENT,
    REDDIT_SUBREDDITS,
)


class RedditAnalyzer:
    """Analyzes Indian stock market sentiment from Reddit."""

    # Common NSE stock tickers that are also common English words - exclude these
    # to avoid false positives
    TICKER_BLACKLIST = {
        "IT", "BE", "OR", "AM", "SO", "DO", "GO", "NO", "UP",
        "ALL", "CAN", "HAS", "HAD", "THE", "FOR", "ARE", "BUT",
        "NOT", "YOU", "HER", "WAS", "ONE", "OUR", "OUT", "DAY",
        "GET", "HIS", "HOW", "ITS", "MAY", "NEW", "NOW", "OLD",
        "SEE", "WAY", "WHO", "DID", "LET", "SAY", "SHE", "TOO",
        "USE", "BUY", "RUN", "IPO", "ETF", "SIP", "FII", "DII",
        "PE", "EPS", "ATH",
    }

    # Common NSE tickers to look for
    KNOWN_TICKERS = {
        "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
        "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
        "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "TITAN",
        "SUNPHARMA", "WIPRO", "TATAMOTORS", "TATASTEEL", "ADANIENT",
        "BAJFINANCE", "HCLTECH", "NESTLEIND", "ULTRACEMCO", "POWERGRID",
        "NTPC", "ONGC", "COALINDIA", "JSWSTEEL", "TECHM",
        "ZOMATO", "PAYTM", "NYKAA", "DMART", "IRCTC",
        "ADANIGREEN", "ADANIPORTS", "TATAPOWER", "VEDL", "SAIL",
    }

    def __init__(self):
        self.reddit = None
        self._init_reddit()

    def _init_reddit(self):
        """Initialize Reddit API client (PRAW)."""
        if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
            print("  Reddit API credentials not configured. Reddit analysis will be limited.")
            return

        try:
            import praw
            self.reddit = praw.Reddit(
                client_id=REDDIT_CLIENT_ID,
                client_secret=REDDIT_CLIENT_SECRET,
                user_agent=REDDIT_USER_AGENT,
            )
        except ImportError:
            print("  praw not installed. Install with: pip install praw")
        except Exception as e:
            print(f"  Error initializing Reddit client: {e}")

    def get_trending_tickers(
        self,
        subreddits: list[str] | None = None,
        time_filter: str = "day",
        limit: int = 50,
    ) -> list[dict]:
        """
        Find trending stock tickers mentioned across Indian finance subreddits.

        Args:
            subreddits: List of subreddits to scan
            time_filter: "hour", "day", "week", "month"
            limit: Number of posts to scan per subreddit

        Returns:
            List of dicts with ticker, mention_count, sample_titles
        """
        if not self.reddit:
            return self._fallback_trending()

        subreddits = subreddits or REDDIT_SUBREDDITS
        ticker_mentions = Counter()
        ticker_posts = {}

        for sub_name in subreddits:
            try:
                subreddit = self.reddit.subreddit(sub_name)
                for post in subreddit.hot(limit=limit):
                    tickers = self._extract_tickers(post.title + " " + (post.selftext or ""))
                    for ticker in tickers:
                        ticker_mentions[ticker] += 1
                        if ticker not in ticker_posts:
                            ticker_posts[ticker] = []
                        if len(ticker_posts[ticker]) < 3:
                            ticker_posts[ticker].append({
                                "title": post.title,
                                "score": post.score,
                                "num_comments": post.num_comments,
                                "url": f"https://reddit.com{post.permalink}",
                            })
            except Exception as e:
                print(f"  Error scanning r/{sub_name}: {e}")

        # Sort by mention count
        results = []
        for ticker, count in ticker_mentions.most_common(20):
            results.append({
                "ticker": ticker,
                "mention_count": count,
                "sample_posts": ticker_posts.get(ticker, []),
            })

        return results

    def get_stock_sentiment(
        self,
        symbol: str,
        subreddits: list[str] | None = None,
        limit: int = 25,
    ) -> dict:
        """
        Get sentiment for a specific stock from Reddit discussions.

        Args:
            symbol: Stock symbol (e.g. "RELIANCE" or "RELIANCE.NS")
            subreddits: Subreddits to search
            limit: Number of posts to analyze

        Returns:
            dict with sentiment scores and relevant posts
        """
        clean_symbol = symbol.replace(".NS", "").replace(".BO", "")

        if not self.reddit:
            return {
                "symbol": clean_symbol,
                "status": "reddit_not_configured",
                "posts_analyzed": 0,
                "sentiment": "neutral",
                "score": 0.0,
            }

        subreddits = subreddits or REDDIT_SUBREDDITS
        relevant_posts = []

        for sub_name in subreddits:
            try:
                subreddit = self.reddit.subreddit(sub_name)
                for post in subreddit.search(clean_symbol, limit=limit, time_filter="month"):
                    relevant_posts.append({
                        "title": post.title,
                        "text": (post.selftext or "")[:500],
                        "score": post.score,
                        "num_comments": post.num_comments,
                        "created": datetime.fromtimestamp(post.created_utc).isoformat(),
                        "url": f"https://reddit.com{post.permalink}",
                    })
            except Exception as e:
                print(f"  Error searching r/{sub_name}: {e}")

        if not relevant_posts:
            return {
                "symbol": clean_symbol,
                "posts_analyzed": 0,
                "sentiment": "neutral",
                "score": 0.0,
                "posts": [],
            }

        # Simple sentiment heuristic based on post engagement
        # High upvotes generally indicate agreement with the thesis
        total_score = sum(p["score"] for p in relevant_posts)
        avg_score = total_score / len(relevant_posts) if relevant_posts else 0

        # Use VADER for text sentiment if available
        try:
            from news.sentiment_analyzer import SentimentAnalyzer
            sa = SentimentAnalyzer()
            text_sentiments = []
            for post in relevant_posts:
                combined = f"{post['title']} {post['text']}"
                s = sa.analyze_text(combined)
                text_sentiments.append(s["compound"])

            avg_sentiment = sum(text_sentiments) / len(text_sentiments)
        except Exception:
            avg_sentiment = 0.0

        label = "positive" if avg_sentiment > 0.05 else ("negative" if avg_sentiment < -0.05 else "neutral")

        return {
            "symbol": clean_symbol,
            "posts_analyzed": len(relevant_posts),
            "sentiment": label,
            "score": round(avg_sentiment, 4),
            "avg_upvotes": round(avg_score, 1),
            "posts": relevant_posts[:5],  # Top 5 posts
        }

    def _extract_tickers(self, text: str) -> set[str]:
        """Extract potential NSE ticker symbols from text."""
        # Match uppercase words that look like tickers (2-15 chars)
        candidates = re.findall(r'\b([A-Z]{2,15})\b', text)

        tickers = set()
        for candidate in candidates:
            if candidate in self.TICKER_BLACKLIST:
                continue
            if candidate in self.KNOWN_TICKERS:
                tickers.add(candidate)

        return tickers

    def _fallback_trending(self) -> list[dict]:
        """Fallback when Reddit API is not configured."""
        return [{
            "ticker": "N/A",
            "mention_count": 0,
            "sample_posts": [],
            "note": "Reddit API not configured. Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env",
        }]
