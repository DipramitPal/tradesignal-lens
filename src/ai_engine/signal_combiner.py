"""
Signal combiner: merges technical, news, and social signals into
a unified trading recommendation with confidence scoring.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import SENTIMENT_WEIGHT, TECHNICAL_WEIGHT


class SignalCombiner:
    """Combines signals from multiple sources into a unified recommendation."""

    def combine(
        self,
        technical_signals: dict,
        news_sentiment: dict,
        social_sentiment: dict,
        mtf_score: float | None = None,
        regime: str = "",
    ) -> dict:
        """
        Combine technical, news, and social signals into a unified signal.

        Args:
            technical_signals: dict with keys like rsi, macd, signal, etc.
            news_sentiment: dict with overall_compound, overall_label
            social_sentiment: dict with score, sentiment
            mtf_score: pre-computed MTF confluence score (if available)
            regime: market regime string (if available)

        Returns:
            dict with combined_score, recommendation, confidence, breakdown
        """
        # --- Technical score (-1 to +1) ---
        if mtf_score is not None:
            tech_score = max(-1.0, min(1.0, mtf_score))
        else:
            tech_score = self._compute_technical_score(technical_signals)

        # --- News sentiment score (-1 to +1) ---
        news_score = news_sentiment.get("overall_compound", 0.0)

        # --- Social sentiment score (-1 to +1) ---
        social_score = social_sentiment.get("score", 0.0)

        # --- Weighted combination ---
        sentiment_score = (news_score + social_score) / 2  # Average of sentiment sources
        combined = (
            TECHNICAL_WEIGHT * tech_score
            + SENTIMENT_WEIGHT * sentiment_score
        )

        # --- Determine recommendation ---
        recommendation = self._score_to_recommendation(combined)
        confidence = self._compute_confidence(
            tech_score, news_score, social_score, combined
        )

        return {
            "combined_score": round(combined, 4),
            "recommendation": recommendation,
            "confidence": confidence,
            "breakdown": {
                "technical_score": round(tech_score, 4),
                "technical_weight": TECHNICAL_WEIGHT,
                "news_sentiment_score": round(news_score, 4),
                "social_sentiment_score": round(social_score, 4),
                "sentiment_weight": SENTIMENT_WEIGHT,
            },
            "signal_agreement": self._check_agreement(tech_score, news_score, social_score),
        }

    def _compute_technical_score(self, signals: dict) -> float:
        """Convert technical indicators into a single score from -1 to +1."""
        score = 0.0
        factors = 0

        # RSI component
        rsi = signals.get("rsi")
        if rsi is not None:
            if rsi < 30:
                score += 0.8  # Strongly oversold = bullish
            elif rsi < 40:
                score += 0.4
            elif rsi > 70:
                score -= 0.8  # Strongly overbought = bearish
            elif rsi > 60:
                score -= 0.4
            factors += 1

        # MACD component
        macd = signals.get("macd")
        macd_signal = signals.get("macd_signal")
        if macd is not None and macd_signal is not None:
            if macd > macd_signal:
                score += 0.5  # Bullish crossover
            else:
                score -= 0.5  # Bearish crossover
            factors += 1

        # MACD histogram direction
        macd_hist = signals.get("macd_hist")
        if macd_hist is not None:
            if macd_hist > 0:
                score += 0.3
            else:
                score -= 0.3
            factors += 1

        # Bollinger Bands
        close = signals.get("close")
        bb_low = signals.get("bb_low")
        bb_high = signals.get("bb_high")
        if close is not None and bb_low is not None and bb_high is not None:
            if close <= bb_low:
                score += 0.6  # Price at lower band = potential bounce
            elif close >= bb_high:
                score -= 0.6  # Price at upper band = potential reversal
            factors += 1

        # Momentum
        momentum = signals.get("momentum_5")
        if momentum is not None:
            if momentum > 0:
                score += 0.3
            else:
                score -= 0.3
            factors += 1

        # Existing signal from signal_generator
        signal_text = signals.get("signal", "")
        if "Buy" in signal_text:
            score += 0.5
            factors += 1
        elif "Sell" in signal_text:
            score -= 0.5
            factors += 1

        # Normalize
        if factors > 0:
            score = score / factors

        return max(-1.0, min(1.0, score))

    def _score_to_recommendation(self, score: float) -> str:
        """Convert combined score to recommendation."""
        if score >= 0.3:
            return "STRONG BUY"
        elif score >= 0.1:
            return "BUY"
        elif score <= -0.3:
            return "STRONG SELL"
        elif score <= -0.1:
            return "SELL"
        return "HOLD"

    def _compute_confidence(
        self, tech: float, news: float, social: float, combined: float
    ) -> str:
        """
        Compute confidence level based on signal agreement.
        High confidence when all sources agree on direction.
        """
        signals = [tech, news, social]
        non_zero = [s for s in signals if abs(s) > 0.05]

        if not non_zero:
            return "LOW"

        # Check if all signals agree on direction
        all_positive = all(s > 0 for s in non_zero)
        all_negative = all(s < 0 for s in non_zero)

        if (all_positive or all_negative) and len(non_zero) >= 2:
            if abs(combined) >= 0.3:
                return "HIGH"
            return "MEDIUM"

        # Mixed signals
        if abs(combined) >= 0.2:
            return "MEDIUM"

        return "LOW"

    def _check_agreement(
        self, tech: float, news: float, social: float
    ) -> str:
        """Check if signals from different sources agree."""
        directions = []
        if abs(tech) > 0.05:
            directions.append("bullish" if tech > 0 else "bearish")
        if abs(news) > 0.05:
            directions.append("bullish" if news > 0 else "bearish")
        if abs(social) > 0.05:
            directions.append("bullish" if social > 0 else "bearish")

        if not directions:
            return "NO_SIGNAL"
        if len(set(directions)) == 1:
            return f"ALIGNED_{directions[0].upper()}"
        return "MIXED"
