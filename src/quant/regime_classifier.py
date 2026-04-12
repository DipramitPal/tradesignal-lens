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

# Transition smoothing state (module-level for persistence across calls)
_transition_state = {
    "candidate_regime": None,
    "candidate_count": 0,
    "confirmed_regime": "RANGE_BOUND",
    "previous_regime": "RANGE_BOUND",
    "in_transition": False,
}

TRANSITION_CONFIRMATION_CANDLES = 3


def classify_regime(df_daily: pd.DataFrame, prev_regime: str = "RANGE_BOUND") -> str:
    """
    Classify the current market regime based on daily indicators.

    Uses 3-candle confirmation before committing to a new regime.

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

    # --- Raw regime detection ---
    raw_regime = prev_regime

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

    # --- Transition smoothing ---
    return _apply_transition_smoothing(raw_regime)


def _apply_transition_smoothing(raw_regime: str) -> str:
    """
    Apply 3-candle confirmation before switching regimes.

    Returns the confirmed regime (may lag the raw detection).
    """
    global _transition_state

    current_confirmed = _transition_state["confirmed_regime"]

    if raw_regime == current_confirmed:
        # No change — reset any pending transition
        _transition_state["candidate_regime"] = None
        _transition_state["candidate_count"] = 0
        _transition_state["in_transition"] = False
        return current_confirmed

    # New candidate or continuation of existing candidate
    if raw_regime == _transition_state["candidate_regime"]:
        _transition_state["candidate_count"] += 1
    else:
        _transition_state["candidate_regime"] = raw_regime
        _transition_state["candidate_count"] = 1
        _transition_state["in_transition"] = True

    # Check if confirmation threshold reached
    if _transition_state["candidate_count"] >= TRANSITION_CONFIRMATION_CANDLES:
        _transition_state["previous_regime"] = current_confirmed
        _transition_state["confirmed_regime"] = raw_regime
        _transition_state["candidate_regime"] = None
        _transition_state["candidate_count"] = 0
        _transition_state["in_transition"] = False
        return raw_regime

    # Still in transition — return confirmed (old) regime
    return current_confirmed


def is_in_transition() -> bool:
    """Check if the regime classifier is currently in a transition window."""
    return _transition_state["in_transition"]


def get_transition_info() -> dict:
    """Get current transition state for diagnostics."""
    return {
        "confirmed": _transition_state["confirmed_regime"],
        "candidate": _transition_state["candidate_regime"],
        "candidate_count": _transition_state["candidate_count"],
        "in_transition": _transition_state["in_transition"],
        "previous": _transition_state["previous_regime"],
    }


def get_weight_table(regime: str) -> dict[str, float]:
    """
    Return the signal weight table for the given regime.

    If in a transition window, blends 50/50 between old and candidate regime.
    """
    if _transition_state["in_transition"] and _transition_state["candidate_regime"]:
        return get_blended_weight_table(
            regime, _transition_state["candidate_regime"], blend_ratio=0.5
        )
    return WEIGHT_TABLES.get(regime, WEIGHT_TABLES["RANGE_BOUND"])


def get_blended_weight_table(
    regime_a: str, regime_b: str, blend_ratio: float = 0.5
) -> dict[str, float]:
    """
    Blend two regime weight tables.

    Args:
        regime_a: first regime
        regime_b: second regime
        blend_ratio: weight for regime_b (0 = pure A, 1 = pure B)

    Returns:
        Blended weight table
    """
    table_a = WEIGHT_TABLES.get(regime_a, WEIGHT_TABLES["RANGE_BOUND"])
    table_b = WEIGHT_TABLES.get(regime_b, WEIGHT_TABLES["RANGE_BOUND"])

    all_keys = set(table_a.keys()) | set(table_b.keys())
    blended = {}
    for key in all_keys:
        w_a = table_a.get(key, 0.0)
        w_b = table_b.get(key, 0.0)
        blended[key] = round(w_a * (1 - blend_ratio) + w_b * blend_ratio, 4)

    return blended


def reset_transition_state():
    """Reset transition state (useful for testing)."""
    global _transition_state
    _transition_state = {
        "candidate_regime": None,
        "candidate_count": 0,
        "confirmed_regime": "RANGE_BOUND",
        "previous_regime": "RANGE_BOUND",
        "in_transition": False,
    }
