"""
LLM-powered analysis engine.
Uses Claude (Anthropic) or GPT (OpenAI) to generate intelligent trading
insights by combining technical indicators, news sentiment, and social trends.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import ANTHROPIC_API_KEY, OPENAI_API_KEY, LLM_PROVIDER, LLM_MODEL


class LLMAnalyzer:
    """Uses LLMs to generate trading insights from multi-source data."""

    SYSTEM_PROMPT = """You are an expert Indian stock market analyst and trading advisor.
You analyze stocks listed on NSE/BSE for retail Indian investors.

Your analysis should consider:
- Technical indicators (RSI, MACD, Bollinger Bands, momentum)
- News sentiment and recent developments
- Social media buzz and retail investor sentiment
- Indian market-specific factors (FII/DII flows, RBI policies, sectoral trends)
- Risk management principles

Always provide:
1. A clear BUY / SELL / HOLD recommendation
2. Confidence level (LOW / MEDIUM / HIGH)
3. Key reasoning (2-3 bullet points)
4. Risk factors to watch
5. Suggested entry/exit price levels when applicable

Important: Always include a disclaimer that this is AI-generated analysis
and not certified financial advice. The user should consult a SEBI-registered
advisor before making investment decisions."""

    def __init__(self):
        self.provider = LLM_PROVIDER
        self.model = LLM_MODEL
        self.client = None
        self._init_client()

    def _init_client(self):
        """Initialize the LLM client based on provider setting."""
        if self.provider == "anthropic" and ANTHROPIC_API_KEY:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            except ImportError:
                print("  anthropic package not installed. Install with: pip install anthropic")
        elif self.provider == "openai" and OPENAI_API_KEY:
            try:
                import openai
                self.client = openai.OpenAI(api_key=OPENAI_API_KEY)
            except ImportError:
                print("  openai package not installed. Install with: pip install openai")
        else:
            print(f"  LLM provider '{self.provider}' not configured. Set API key in .env")

    def analyze_stock(
        self,
        symbol: str,
        technical_data: dict,
        news_sentiment: dict,
        social_sentiment: dict,
        stock_info: dict | None = None,
    ) -> dict:
        """
        Generate AI-powered analysis for a stock combining all data sources.

        Args:
            symbol: Stock symbol
            technical_data: Technical indicators and signals
            news_sentiment: News sentiment analysis results
            social_sentiment: Social media sentiment results
            stock_info: Basic stock info (sector, price, etc.)

        Returns:
            dict with recommendation, confidence, reasoning, risks
        """
        if not self.client:
            return self._fallback_analysis(
                symbol, technical_data, news_sentiment, social_sentiment
            )

        prompt = self._build_analysis_prompt(
            symbol, technical_data, news_sentiment, social_sentiment, stock_info
        )

        try:
            response_text = self._call_llm(prompt)
            return {
                "symbol": symbol,
                "ai_analysis": response_text,
                "model": self.model,
                "provider": self.provider,
                "status": "success",
            }
        except Exception as e:
            print(f"  LLM analysis failed for {symbol}: {e}")
            return self._fallback_analysis(
                symbol, technical_data, news_sentiment, social_sentiment
            )

    def generate_market_brief(
        self,
        market_data: dict,
        trending_tickers: list[dict],
        market_news: list[dict],
    ) -> dict:
        """Generate a daily market brief using AI."""
        if not self.client:
            return {
                "status": "llm_not_configured",
                "brief": "Configure an LLM provider to get AI-generated market briefs.",
            }

        prompt = self._build_market_brief_prompt(
            market_data, trending_tickers, market_news
        )

        try:
            response_text = self._call_llm(prompt)
            return {
                "brief": response_text,
                "model": self.model,
                "status": "success",
            }
        except Exception as e:
            return {"status": "error", "brief": f"Failed to generate brief: {e}"}

    def _call_llm(self, prompt: str) -> str:
        """Call the configured LLM provider."""
        if self.provider == "anthropic":
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text

        elif self.provider == "openai":
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=2048,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            return response.choices[0].message.content

        raise ValueError(f"Unknown provider: {self.provider}")

    def _build_analysis_prompt(
        self, symbol, technical_data, news_sentiment, social_sentiment, stock_info
    ) -> str:
        """Build a detailed analysis prompt for a single stock."""
        parts = [f"Analyze the following data for {symbol} and provide a trading recommendation.\n"]

        if stock_info:
            parts.append("## Stock Info")
            parts.append(json.dumps(stock_info, indent=2, default=str))

        parts.append("\n## Technical Indicators")
        parts.append(json.dumps(technical_data, indent=2, default=str))

        parts.append("\n## News Sentiment")
        parts.append(json.dumps(news_sentiment, indent=2, default=str))

        parts.append("\n## Social Media Sentiment")
        parts.append(json.dumps(social_sentiment, indent=2, default=str))

        parts.append(
            "\nBased on all the above data, provide your analysis with:"
            "\n1. Recommendation (BUY/SELL/HOLD)"
            "\n2. Confidence level"
            "\n3. Key reasoning"
            "\n4. Risk factors"
            "\n5. Suggested price levels if applicable"
        )

        return "\n".join(parts)

    def _build_market_brief_prompt(
        self, market_data, trending_tickers, market_news
    ) -> str:
        """Build prompt for daily market brief."""
        parts = ["Generate a concise daily Indian stock market brief.\n"]

        parts.append("## Market Data")
        parts.append(json.dumps(market_data, indent=2, default=str))

        if trending_tickers:
            parts.append("\n## Trending Tickers on Social Media")
            for t in trending_tickers[:10]:
                parts.append(f"- {t['ticker']}: {t['mention_count']} mentions")

        if market_news:
            parts.append("\n## Recent Market News Headlines")
            for n in market_news[:10]:
                parts.append(f"- [{n['source']}] {n['title']}")

        parts.append(
            "\nProvide:"
            "\n1. Market mood summary (1-2 lines)"
            "\n2. Key sectors to watch"
            "\n3. Top 3 stocks to watch today with reasoning"
            "\n4. Key risk events for the day"
        )

        return "\n".join(parts)

    def _fallback_analysis(
        self, symbol, technical_data, news_sentiment, social_sentiment
    ) -> dict:
        """Rule-based fallback when LLM is not available."""
        recommendation = "HOLD"
        confidence = "LOW"
        reasons = []

        # Technical signal
        tech_signal = technical_data.get("signal", "Hold")
        if "Buy" in tech_signal:
            recommendation = "BUY"
            reasons.append(f"Technical signal: {tech_signal}")
        elif "Sell" in tech_signal:
            recommendation = "SELL"
            reasons.append(f"Technical signal: {tech_signal}")

        # RSI
        rsi = technical_data.get("rsi", 50)
        if rsi < 30:
            reasons.append(f"RSI oversold at {rsi:.1f}")
            if recommendation != "SELL":
                recommendation = "BUY"
        elif rsi > 70:
            reasons.append(f"RSI overbought at {rsi:.1f}")
            if recommendation != "BUY":
                recommendation = "SELL"

        # News sentiment
        news_score = news_sentiment.get("overall_compound", 0)
        if news_score > 0.2:
            reasons.append(f"Positive news sentiment ({news_score:.2f})")
            confidence = "MEDIUM"
        elif news_score < -0.2:
            reasons.append(f"Negative news sentiment ({news_score:.2f})")
            confidence = "MEDIUM"

        # Social sentiment
        social_score = social_sentiment.get("score", 0)
        if social_score > 0.1:
            reasons.append(f"Positive social media buzz ({social_score:.2f})")
        elif social_score < -0.1:
            reasons.append(f"Negative social media sentiment ({social_score:.2f})")

        if not reasons:
            reasons.append("No strong signals detected")

        return {
            "symbol": symbol,
            "recommendation": recommendation,
            "confidence": confidence,
            "reasoning": reasons,
            "risks": ["This is a rule-based fallback analysis. Configure an LLM for deeper insights."],
            "status": "fallback",
            "disclaimer": "This is AI-generated analysis, not financial advice. Consult a SEBI-registered advisor.",
        }
