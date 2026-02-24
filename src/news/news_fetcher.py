"""
Financial news fetcher for Indian markets.
Supports NewsAPI and Google News RSS as sources.
"""

import os
import sys
from datetime import datetime, timedelta
from urllib.parse import quote

import feedparser
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import NEWS_API_KEY


class NewsFetcher:
    """Fetches financial news from multiple sources relevant to Indian markets."""

    GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
    NEWSAPI_URL = "https://newsapi.org/v2/everything"

    # Indian financial news domains for Google News filtering
    INDIAN_FINANCE_DOMAINS = [
        "economictimes.indiatimes.com",
        "moneycontrol.com",
        "livemint.com",
        "business-standard.com",
        "ndtv.com/business",
        "thehindubusinessline.com",
        "financialexpress.com",
        "zeebiz.com",
        "tickertape.in",
    ]

    def fetch_stock_news(
        self,
        symbol: str,
        company_name: str = "",
        max_results: int = 10,
    ) -> list[dict]:
        """
        Fetch news for a specific stock from available sources.

        Args:
            symbol: Stock symbol (e.g. "RELIANCE.NS")
            company_name: Full company name for better search
            max_results: Maximum number of articles to return

        Returns:
            List of dicts with keys: title, description, source, url, published
        """
        # Clean symbol for search (remove exchange suffix)
        clean_symbol = symbol.replace(".BSE", "").replace(".NS", "").replace(".BO", "")
        search_term = company_name or clean_symbol

        articles = []

        # Try NewsAPI first if key is available
        if NEWS_API_KEY:
            articles.extend(
                self._fetch_from_newsapi(search_term, max_results)
            )

        # Always supplement with Google News RSS (no API key needed)
        articles.extend(
            self._fetch_from_google_news(search_term, max_results)
        )

        # Deduplicate by title similarity
        seen_titles = set()
        unique = []
        for article in articles:
            title_key = article["title"][:50].lower()
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique.append(article)

        return unique[:max_results]

    def fetch_market_news(self, max_results: int = 15) -> list[dict]:
        """Fetch general Indian stock market news."""
        queries = [
            "Indian stock market NSE BSE",
            "Nifty Sensex today",
            "India share market",
        ]

        all_articles = []
        per_query = max(max_results // len(queries), 5)

        for query in queries:
            all_articles.extend(
                self._fetch_from_google_news(query, per_query)
            )

        # Deduplicate
        seen = set()
        unique = []
        for a in all_articles:
            key = a["title"][:50].lower()
            if key not in seen:
                seen.add(key)
                unique.append(a)

        return unique[:max_results]

    def _fetch_from_google_news(
        self, query: str, max_results: int
    ) -> list[dict]:
        """Fetch from Google News RSS feed."""
        try:
            url = f"{self.GOOGLE_NEWS_RSS}?q={quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
            feed = feedparser.parse(url)

            articles = []
            for entry in feed.entries[:max_results]:
                articles.append({
                    "title": entry.get("title", ""),
                    "description": entry.get("summary", ""),
                    "source": entry.get("source", {}).get("title", "Google News"),
                    "url": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "fetched_via": "google_news_rss",
                })

            return articles

        except Exception as e:
            print(f"  Error fetching Google News: {e}")
            return []

    def _fetch_from_newsapi(
        self, query: str, max_results: int
    ) -> list[dict]:
        """Fetch from NewsAPI (requires API key)."""
        if not NEWS_API_KEY:
            return []

        try:
            from_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

            params = {
                "q": query,
                "from": from_date,
                "sortBy": "relevancy",
                "language": "en",
                "pageSize": max_results,
                "apiKey": NEWS_API_KEY,
            }

            resp = requests.get(self.NEWSAPI_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            articles = []
            for item in data.get("articles", []):
                articles.append({
                    "title": item.get("title", ""),
                    "description": item.get("description", ""),
                    "source": item.get("source", {}).get("name", "Unknown"),
                    "url": item.get("url", ""),
                    "published": item.get("publishedAt", ""),
                    "fetched_via": "newsapi",
                })

            return articles

        except Exception as e:
            print(f"  Error fetching from NewsAPI: {e}")
            return []
