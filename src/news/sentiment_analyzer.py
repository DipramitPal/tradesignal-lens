"""
Sentiment analysis for financial news and text.
Uses VADER (Valence Aware Dictionary and sEntiment Reasoner) which is
well-suited for social media and financial text.
"""

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer


class SentimentAnalyzer:
    """Analyzes sentiment of financial news headlines and articles."""

    # Financial-domain boosters: words that should amplify sentiment in market context
    FINANCIAL_POSITIVE = {
        "bullish", "rally", "surge", "breakout", "upgrade", "outperform",
        "beat", "exceeded", "profit", "dividend", "bonus", "buyback",
        "growth", "recovery", "rebound", "record high", "all-time high",
        "strong results", "robust", "expansion",
    }

    FINANCIAL_NEGATIVE = {
        "bearish", "crash", "plunge", "downgrade", "underperform",
        "miss", "missed", "loss", "deficit", "debt", "default",
        "fraud", "scam", "investigation", "penalty", "fine",
        "bankruptcy", "selloff", "correction", "recession",
        "weak results", "disappointing", "contraction",
    }

    def __init__(self):
        self.analyzer = SentimentIntensityAnalyzer()

    def analyze_text(self, text: str) -> dict:
        """
        Analyze sentiment of a single text.

        Returns:
            dict with keys: compound, positive, negative, neutral, label
            compound ranges from -1 (most negative) to +1 (most positive)
        """
        if not text:
            return {
                "compound": 0.0,
                "positive": 0.0,
                "negative": 0.0,
                "neutral": 1.0,
                "label": "neutral",
            }

        scores = self.analyzer.polarity_scores(text)

        # Apply financial domain boosting
        compound = scores["compound"]
        text_lower = text.lower()

        financial_boost = 0.0
        for word in self.FINANCIAL_POSITIVE:
            if word in text_lower:
                financial_boost += 0.1

        for word in self.FINANCIAL_NEGATIVE:
            if word in text_lower:
                financial_boost -= 0.1

        # Blend VADER score with financial boost (capped to [-1, 1])
        compound = max(-1.0, min(1.0, compound + financial_boost * 0.5))

        label = self._score_to_label(compound)

        return {
            "compound": round(compound, 4),
            "positive": round(scores["pos"], 4),
            "negative": round(scores["neg"], 4),
            "neutral": round(scores["neu"], 4),
            "label": label,
        }

    def analyze_articles(self, articles: list[dict]) -> dict:
        """
        Analyze sentiment across multiple news articles.

        Args:
            articles: List of article dicts with 'title' and 'description' keys

        Returns:
            dict with overall_sentiment, article_sentiments, and summary stats
        """
        if not articles:
            return {
                "overall_compound": 0.0,
                "overall_label": "neutral",
                "num_articles": 0,
                "positive_count": 0,
                "negative_count": 0,
                "neutral_count": 0,
                "article_sentiments": [],
            }

        sentiments = []
        for article in articles:
            # Combine title + description for analysis (title weighted more)
            text = article.get("title", "")
            desc = article.get("description", "")
            if desc:
                text = f"{text}. {desc}"

            sentiment = self.analyze_text(text)
            sentiment["title"] = article.get("title", "")
            sentiment["source"] = article.get("source", "")
            sentiments.append(sentiment)

        # Calculate overall sentiment
        compounds = [s["compound"] for s in sentiments]
        overall = sum(compounds) / len(compounds) if compounds else 0.0

        pos_count = sum(1 for s in sentiments if s["label"] == "positive")
        neg_count = sum(1 for s in sentiments if s["label"] == "negative")
        neu_count = sum(1 for s in sentiments if s["label"] == "neutral")

        return {
            "overall_compound": round(overall, 4),
            "overall_label": self._score_to_label(overall),
            "num_articles": len(sentiments),
            "positive_count": pos_count,
            "negative_count": neg_count,
            "neutral_count": neu_count,
            "article_sentiments": sentiments,
        }

    def _score_to_label(self, compound: float) -> str:
        """Convert compound score to human-readable label."""
        if compound >= 0.05:
            return "positive"
        elif compound <= -0.05:
            return "negative"
        return "neutral"
