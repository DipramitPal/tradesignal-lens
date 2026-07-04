"""
4-regime market classification engine with transition smoothing.

Regimes:
  TRENDING_UP   — ADX > 25, EMA50 > EMA200, Supertrend bullish
  TRENDING_DOWN — ADX > 25, EMA50 < EMA200, Supertrend bearish
  RANGE_BOUND   — ADX < 20, BB width below median, sideways price
  VOLATILE      — ATR spike > 1.5×, BB width > 2× median

Each regime maps to a different signal weight table.
Transition smoothing: 3-candle confirmation before switching regimes,
with 50/50 weight blending during the transition window.
"""

import pandas as pd
import numpy as np

# --- Regime-adaptive weight tables ---
# Keys are signal names, values are weights per regime.
# Each table sums to ~1.0 (some regimes intentionally under-weight).

WEIGHT_TABLES = {
    "TRENDING_UP": {
        "macd_cross_15m": 0.15, "rsi_oversold_15m": 0.08, "stoch_rsi_os_15m": 0.05,
        "price_above_vwap_15m": 0.10, "supertrend_bull_daily": 0.15,
        "ichimoku_above_cloud": 0.12, "ema50_above_200": 0.10,
        "volume_surge": 0.05, "cmf_positive": 0.05, "squeeze_fire": 0.05,
        "rsi_divergence": 0.05, "obv_divergence": 0.03, "pivot_bounce": 0.02,
    },
    "TRENDING_DOWN": {
        "macd_cross_15m": 0.05, "rsi_oversold_15m": 0.05, "stoch_rsi_os_15m": 0.03,
        "price_above_vwap_15m": 0.05, "supertrend_bull_daily": 0.03,
        "ichimoku_above_cloud": 0.03, "ema50_above_200": 0.03,
        "volume_surge": 0.05, "cmf_positive": 0.03, "squeeze_fire": 0.05,
        "rsi_divergence": 0.15, "obv_divergence": 0.12, "pivot_bounce": 0.03,
    },
    "RANGE_BOUND": {
        "macd_cross_15m": 0.10, "rsi_oversold_15m": 0.18, "stoch_rsi_os_15m": 0.12,
        "price_above_vwap_15m": 0.10, "supertrend_bull_daily": 0.05,
        "ichimoku_above_cloud": 0.03, "ema50_above_200": 0.02,
        "volume_surge": 0.10, "cmf_positive": 0.08, "squeeze_fire": 0.12,
        "rsi_divergence": 0.05, "obv_divergence": 0.03, "pivot_bounce": 0.12,
    },
    "VOLATILE": {
        "macd_cross_15m": 0.08, "rsi_oversold_15m": 0.10, "stoch_rsi_os_15m": 0.08,
        "price_above_vwap_15m": 0.06, "supertrend_bull_daily": 0.06,
        "ichimoku_above_cloud": 0.05, "ema50_above_200": 0.04,
        "volume_surge": 0.12, "cmf_positive": 0.06, "squeeze_fire": 0.15,
        "rsi_divergence": 0.10, "obv_divergence": 0.06, "pivot_bounce": 0.04,
    },
}

TRANSITION_CONFIRMATION_CANDLES = 3


class RegimeClassifier:
    """Stateful regime classifier. Use one instance per instrument."""

    def __init__(self, initial_regime: str = "RANGE_BOUND"):
        self._state = {
            "candidate_regime": None,
            "candidate_count": 0,
            "confirmed_regime": initial_regime,
            "previous_regime": initial_regime,
            "in_transition": False,
        }

    def classify(self, df_daily: pd.DataFrame) -> str:
        """Classify regime from daily DataFrame. Same logic as module-level classify_regime()."""
        if df_daily.empty or len(df_daily) < 20:
            return self._state["confirmed_regime"]
        
        raw_regime = self._detect_raw_regime(df_daily)
        return self._apply_transition_smoothing(raw_regime)

    def _detect_raw_regime(self, df_daily: pd.DataFrame) -> str:
        """Detect raw regime without smoothing."""
        latest = df_daily.iloc[-1]

        adx = float(latest.get("adx", 0))
        ema50 = float(latest.get("ema_50", 0))
        ema200 = float(latest.get("ema_200", 0))
        supertrend_dir = float(latest.get("supertrend_direction", 0))

        # BB width analysis
        bb_width = float(latest.get("bb_width", 0))
        bb_width_series = df_daily["bb_width"] if "bb_width" in df_daily.columns else None
        bb_width_median = float(bb_width_series.rolling(50).median().iloc[-1]) if (
            bb_width_series is not None and len(bb_width_series) >= 50
        ) else bb_width

        # ATR spike detection
        atr_current = float(latest.get("atr", 0))
        if "atr" in df_daily.columns and len(df_daily) >= 20:
            atr_avg = float(df_daily["atr"].rolling(20).mean().iloc[-1])
            atr_ratio = atr_current / (atr_avg + 1e-10)
        else:
            atr_ratio = 1.0

        # --- Raw regime detection ---
        raw_regime = self._state["confirmed_regime"]

        # Volatile (check first — overrides)
        if atr_ratio > 1.5 or (bb_width_median > 0 and bb_width > 2 * bb_width_median):
            raw_regime = "VOLATILE"
        # Trending UP
        elif adx > 25 and ema50 > ema200 and supertrend_dir == 1:
            raw_regime = "TRENDING_UP"
        # Trending DOWN
        elif adx > 25 and ema50 < ema200 and supertrend_dir == -1:
            raw_regime = "TRENDING_DOWN"
        # Range-bound
        elif adx < 20 and (bb_width_median == 0 or bb_width < bb_width_median):
            raw_regime = "RANGE_BOUND"
        # Transition zone
        elif adx > 20 and ema50 > ema200:
            raw_regime = "TRENDING_UP"
        elif adx > 20 and ema50 < ema200:
            raw_regime = "TRENDING_DOWN"

        return raw_regime

    def _apply_transition_smoothing(self, raw_regime: str) -> str:
        """Apply 3-candle confirmation before switching regimes."""
        current_confirmed = self._state["confirmed_regime"]

        if raw_regime == current_confirmed:
            # No change — reset any pending transition
            self._state["candidate_regime"] = None
            self._state["candidate_count"] = 0
            self._state["in_transition"] = False
            return current_confirmed

        # New candidate or continuation of existing candidate
        if raw_regime == self._state["candidate_regime"]:
            self._state["candidate_count"] += 1
        else:
            self._state["candidate_regime"] = raw_regime
            self._state["candidate_count"] = 1
            self._state["in_transition"] = True

        # Check if confirmation threshold reached
        if self._state["candidate_count"] >= TRANSITION_CONFIRMATION_CANDLES:
            self._state["previous_regime"] = current_confirmed
            self._state["confirmed_regime"] = raw_regime
            self._state["candidate_regime"] = None
            self._state["candidate_count"] = 0
            self._state["in_transition"] = False
            return raw_regime

        # Still in transition — return confirmed (old) regime
        return current_confirmed

    def is_in_transition(self) -> bool:
        """Check if the regime classifier is currently in a transition window."""
        return self._state["in_transition"]

    def get_transition_info(self) -> dict:
        """Get current transition state for diagnostics."""
        return dict(self._state)

    def reset(self):
        """Reset transition state."""
        self._state = {
            "candidate_regime": None,
            "candidate_count": 0,
            "confirmed_regime": "RANGE_BOUND",
            "previous_regime": "RANGE_BOUND",
            "in_transition": False,
        }

    def get_weight_table(self, regime: str) -> dict[str, float]:
        """
        Return the signal weight table for the given regime.
        If in a transition window, blends 50/50 between old and candidate regime.
        """
        if self._state["in_transition"] and self._state["candidate_regime"]:
            return get_blended_weight_table(
                regime, self._state["candidate_regime"], blend_ratio=0.5
            )
        return WEIGHT_TABLES.get(regime, WEIGHT_TABLES["RANGE_BOUND"])


def get_blended_weight_table(
    regime_a: str, regime_b: str, blend_ratio: float = 0.5
) -> dict[str, float]:
    """Blend two regime weight tables."""
    table_a = WEIGHT_TABLES.get(regime_a, WEIGHT_TABLES["RANGE_BOUND"])
    table_b = WEIGHT_TABLES.get(regime_b, WEIGHT_TABLES["RANGE_BOUND"])

    all_keys = set(table_a.keys()) | set(table_b.keys())
    blended = {}
    for key in all_keys:
        w_a = table_a.get(key, 0.0)
        w_b = table_b.get(key, 0.0)
        blended[key] = round(w_a * (1 - blend_ratio) + w_b * blend_ratio, 4)

    return blended


# Module-level singleton for backward compatibility with existing callers
_default_classifier = RegimeClassifier()

def classify_regime(df_daily: pd.DataFrame, prev_regime: str = "RANGE_BOUND") -> str:
    """Backward-compatible wrapper. Uses module singleton."""
    return _default_classifier.classify(df_daily)

def reset_transition_state():
    """Reset default singleton (for tests)."""
    _default_classifier.reset()

def is_in_transition() -> bool:
    return _default_classifier.is_in_transition()

def get_transition_info() -> dict:
    return _default_classifier.get_transition_info()

def get_weight_table(regime: str) -> dict[str, float]:
    return _default_classifier.get_weight_table(regime)

