"""
4-regime market classification engine.

Regimes:
  TRENDING_UP   — ADX > 25, EMA50 > EMA200, Supertrend bullish
  TRENDING_DOWN — ADX > 25, EMA50 < EMA200, Supertrend bearish
  RANGE_BOUND   — ADX < 20, BB width below median, sideways price
  VOLATILE      — ATR spike > 1.5×, BB width > 2× median

Each regime maps to a different signal weight table.
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


def classify_regime(df_daily: pd.DataFrame, prev_regime: str = "RANGE_BOUND") -> str:
    """
    Classify the current market regime based on daily indicators.

    Args:
        df_daily: daily DataFrame with indicators (adx, bb_width, ema_50,
                  ema_200, supertrend_direction, atr)
        prev_regime: fallback if in a transition zone

    Returns:
        One of: TRENDING_UP, TRENDING_DOWN, RANGE_BOUND, VOLATILE
    """
    if df_daily.empty or len(df_daily) < 20:
        return prev_regime

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

    # --- Volatile regime (check first — it overrides) ---
    if atr_ratio > 1.5 or (bb_width_median > 0 and bb_width > 2 * bb_width_median):
        return "VOLATILE"

    # --- Trending UP ---
    if adx > 25 and ema50 > ema200 and supertrend_dir == 1:
        return "TRENDING_UP"

    # --- Trending DOWN ---
    if adx > 25 and ema50 < ema200 and supertrend_dir == -1:
        return "TRENDING_DOWN"

    # --- Range-bound ---
    if adx < 20 and (bb_width_median == 0 or bb_width < bb_width_median):
        return "RANGE_BOUND"

    # Transition zone — mild trend that doesn't fully qualify
    if adx > 20 and ema50 > ema200:
        return "TRENDING_UP"
    elif adx > 20 and ema50 < ema200:
        return "TRENDING_DOWN"

    return prev_regime


def get_weight_table(regime: str) -> dict[str, float]:
    """Return the signal weight table for the given regime."""
    return WEIGHT_TABLES.get(regime, WEIGHT_TABLES["RANGE_BOUND"])
