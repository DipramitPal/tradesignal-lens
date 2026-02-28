"""
Regime-adaptive weighted signal scoring engine (v2).

Replaces the previous overwriting signal logic with a proper
weighted scoring matrix that adapts to market regime.

Signal flow:
  1. Score 15m signals (entry timing)
  2. Score daily signals (trend context)
  3. Compute MTF confluence (60% 15m + 40% daily)
  4. Apply divergence boost, RVOL multiplier, sector adjustment
  5. Normalize to [-1, +1] range
"""

import pandas as pd
import numpy as np

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from feature_engineering import add_technical_indicators


# --- Backward-compatible functions ---

def compute_stop_loss(price: float, atr: float, multiplier: float = 2.0) -> float:
    """ATR-based stop-loss for a long position (backward compat)."""
    return round(price - multiplier * atr, 2)


def compute_trailing_stop(
    price: float, highest_since_buy: float, atr: float,
    multiplier: float = 2.0,
) -> float:
    """Trailing stop-loss (backward compat wrapper)."""
    new_high = max(price, highest_since_buy)
    return round(new_high - multiplier * atr, 2)


def resample_data(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resample OHLCV data to a different timeframe."""
    rule_map = {
        "daily": "D", "weekly": "W", "monthly": "M", "quarterly": "Q",
    }
    if timeframe not in rule_map:
        raise ValueError("Timeframe must be one of: daily, weekly, monthly, quarterly")

    ohlc_dict = {
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }
    return df.resample(rule_map[timeframe]).apply(ohlc_dict).dropna()


def analyze_stock(df: pd.DataFrame, timeframe: str = "weekly") -> pd.DataFrame:
    """Backward compat: resample + indicators + signals."""
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    df = resample_data(df, timeframe)
    df = add_technical_indicators(df)
    df = generate_signals(df)
    return df


# =====================================================================
# NEW: Weighted Signal Scoring Engine
# =====================================================================

def score_signals(
    df: pd.DataFrame,
    weight_table: dict[str, float],
    pivots: dict | None = None,
) -> float:
    """
    Score signals using the regime-adaptive weight table.

    Args:
        df: DataFrame with indicators (can be 15m or daily)
        weight_table: signal_name → weight mapping from regime_classifier
        pivots: optional pivot point levels dict

    Returns:
        Raw weighted score (not normalized).
    """
    if df.empty:
        return 0.0

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    score = 0.0

    # --- MACD Bullish Crossover (15m / daily) ---
    macd = float(latest.get("macd", 0))
    macd_signal_val = float(latest.get("macd_signal", 0))
    macd_prev = float(prev.get("macd", 0))
    macd_signal_prev = float(prev.get("macd_signal", 0))

    w = weight_table.get("macd_cross_15m", 0.10)
    if macd > macd_signal_val and macd_prev <= macd_signal_prev:
        score += w * 1.0  # bullish crossover
    elif macd < macd_signal_val and macd_prev >= macd_signal_prev:
        score -= w * 1.0  # bearish crossover

    # --- RSI Oversold / Overbought ---
    rsi = float(latest.get("rsi", 50))
    w_rsi = weight_table.get("rsi_oversold_15m", 0.10)
    if rsi < 30:
        score += w_rsi * 1.0
    elif rsi < 40:
        score += w_rsi * 0.5
    elif rsi > 70:
        score -= w_rsi * 1.0
    elif rsi > 60:
        score -= w_rsi * 0.5

    # --- Stochastic RSI ---
    stoch_k = float(latest.get("stoch_rsi_k", 50))
    w_stoch = weight_table.get("stoch_rsi_os_15m", 0.05)
    if stoch_k < 20:
        score += w_stoch * 0.8
    elif stoch_k > 80:
        score -= w_stoch * 0.8

    # --- Price vs VWAP ---
    price = float(latest["close"])
    vwap = float(latest.get("vwap", price))
    w_vwap = weight_table.get("price_above_vwap_15m", 0.10)
    if price > vwap:
        score += w_vwap * 0.6
    elif price < vwap:
        score -= w_vwap * 0.6

    # --- Supertrend Direction ---
    st_dir = float(latest.get("supertrend_direction", 0))
    w_st = weight_table.get("supertrend_bull_daily", 0.15)
    if st_dir == 1:
        score += w_st * 1.0
    elif st_dir == -1:
        score -= w_st * 1.0

    # --- Ichimoku Cloud ---
    w_ichi = weight_table.get("ichimoku_above_cloud", 0.10)
    senkou_a = float(latest.get("ichimoku_senkou_a", 0))
    senkou_b = float(latest.get("ichimoku_senkou_b", 0))
    tenkan = float(latest.get("ichimoku_tenkan", 0))
    kijun = float(latest.get("ichimoku_kijun", 0))
    cloud_top = max(senkou_a, senkou_b) if senkou_a and senkou_b else 0
    cloud_bottom = min(senkou_a, senkou_b) if senkou_a and senkou_b else 0

    if cloud_top > 0:
        if price > cloud_top and tenkan > kijun:
            score += w_ichi * 1.0
        elif price < cloud_bottom and tenkan < kijun:
            score -= w_ichi * 1.0
        # Inside cloud = no score (equilibrium)

    # --- EMA 50 vs 200 ---
    ema50 = float(latest.get("ema_50", 0))
    ema200 = float(latest.get("ema_200", 0))
    w_ema = weight_table.get("ema50_above_200", 0.10)
    if ema50 > 0 and ema200 > 0:
        if ema50 > ema200:
            score += w_ema * 0.9
        else:
            score -= w_ema * 0.9

    # --- Volume Surge (RVOL proxy) ---
    vol = float(latest.get("volume", 0))
    vol_avg = df["volume"].rolling(20).mean().iloc[-1] if len(df) >= 20 else vol
    rvol = vol / (vol_avg + 1e-10)
    w_vol = weight_table.get("volume_surge", 0.10)
    if rvol > 2.0:
        direction = 1 if price > float(prev["close"]) else -1
        score += w_vol * 0.8 * direction
    elif rvol > 1.5:
        direction = 1 if price > float(prev["close"]) else -1
        score += w_vol * 0.4 * direction

    # --- Chaikin Money Flow ---
    cmf = float(latest.get("cmf", 0))
    w_cmf = weight_table.get("cmf_positive", 0.05)
    if cmf > 0.10:
        score += w_cmf * 0.7
    elif cmf < -0.10:
        score -= w_cmf * 0.7

    # --- BB Squeeze Fire ---
    squeeze_fire = int(latest.get("squeeze_fire", 0))
    w_squeeze = weight_table.get("squeeze_fire", 0.10)
    if squeeze_fire:
        # Direction based on momentum
        momentum = float(latest.get("momentum_5", 0))
        direction = 1 if momentum > 0 else -1
        score += w_squeeze * 0.9 * direction

    # --- Pivot Point Bounce (if pivots provided) ---
    if pivots:
        w_pivot = weight_table.get("pivot_bounce", 0.05)
        s3 = pivots.get("s3", 0)
        r3 = pivots.get("r3", 0)
        if s3 > 0 and abs(price - s3) / (price + 1e-10) < 0.015:
            score += w_pivot * 0.8  # near support → bullish
        if r3 > 0 and abs(price - r3) / (price + 1e-10) < 0.015:
            score -= w_pivot * 0.8  # near resistance → bearish

    # --- Bollinger Band extremes ---
    bb_low = float(latest.get("bb_low", 0))
    bb_high = float(latest.get("bb_high", 0))
    if bb_low > 0 and price <= bb_low:
        score += 0.03  # small bonus for band touch
    elif bb_high > 0 and price >= bb_high:
        score -= 0.03

    # --- MFI extremes ---
    mfi = float(latest.get("mfi", 50))
    if mfi < 20:
        score += 0.03
    elif mfi > 80:
        score -= 0.03

    # --- Williams %R ---
    wr = float(latest.get("williams_r", -50))
    if wr < -80:
        score += 0.02  # deeply oversold
    elif wr > -20:
        score -= 0.02  # overbought

    # --- Parabolic SAR direction ---
    psar_dir = float(latest.get("psar_direction", 0))
    if psar_dir == 1:
        score += 0.02
    elif psar_dir == -1:
        score -= 0.02

    return score


def compute_mtf_confluence(
    score_15m: float, score_daily: float,
    weight_15m: float = 0.60, weight_daily: float = 0.40,
) -> float:
    """
    Combine multi-timeframe scores.

    15m gets 60% weight (entry timing), daily gets 40% (trend context).
    """
    return score_15m * weight_15m + score_daily * weight_daily


def apply_divergence_boost(score: float, divergence_direction: str) -> float:
    """Apply 25% confidence boost if divergence confirms signal direction."""
    if divergence_direction == "BULLISH" and score > 0:
        return score * 1.25
    elif divergence_direction == "BEARISH" and score < 0:
        return score * 1.25
    elif divergence_direction == "BULLISH" and score < 0:
        return score * 0.80  # divergence contradicts — dampen
    elif divergence_direction == "BEARISH" and score > 0:
        return score * 0.80
    return score


def apply_rvol_multiplier(score: float, rvol: float) -> float:
    """Apply RVOL as a multiplier: high volume = more conviction."""
    multiplier = max(0.5, min(rvol / 2.0, 1.5))
    return score * multiplier


def apply_sector_adjustment(score: float, sector_multiplier: float) -> float:
    """Apply sector rotation adjustment."""
    return score * sector_multiplier


def normalize_score(raw_score: float, max_possible: float = 1.0) -> float:
    """Normalize to [-1, +1] range."""
    if max_possible <= 0:
        return 0.0
    return max(-1.0, min(1.0, raw_score / max_possible))


def score_to_recommendation(score: float) -> str:
    """Convert normalized score to recommendation text."""
    if score >= 0.65:
        return "STRONG BUY"
    elif score >= 0.40:
        return "BUY"
    elif score >= 0.20:
        return "BUY (Watchlist)"
    elif score <= -0.46:
        return "STRONG SELL"
    elif score <= -0.20:
        return "SELL"
    return "HOLD"


def score_to_confidence(score: float) -> str:
    """Convert score magnitude to confidence level."""
    abs_score = abs(score)
    if abs_score >= 0.55:
        return "HIGH"
    elif abs_score >= 0.30:
        return "MEDIUM"
    return "LOW"


# =====================================================================
# BACKWARD COMPAT: Legacy generate_signals
# =====================================================================

def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Legacy signal generation (kept for backward compatibility).
    Adds Signal, stop_loss, signal_strength columns.
    """
    df["Signal"] = "Hold"
    df["signal_strength"] = 0.0

    # ATR-based stop-loss
    if "atr" in df.columns:
        df["stop_loss"] = df["close"] - 2 * df["atr"]
    else:
        df["stop_loss"] = df["close"] * 0.95

    # MACD Crossover
    if "macd" in df.columns:
        macd_cross_up = (df["macd"] > 0) & (df["macd"].shift(1) <= 0)
        df.loc[macd_cross_up, "Signal"] = "Buy (MACD Bullish Crossover)"
        df.loc[macd_cross_up, "signal_strength"] += 1.0
        macd_cross_down = (df["macd"] < 0) & (df["macd"].shift(1) >= 0)
        df.loc[macd_cross_down, "Signal"] = "Sell (MACD Bearish Crossover)"
        df.loc[macd_cross_down, "signal_strength"] -= 1.0

    # RSI extremes
    if "rsi" in df.columns:
        df.loc[df["rsi"] < 30, "Signal"] = "Buy (RSI Oversold)"
        df.loc[df["rsi"] < 30, "signal_strength"] += 1.5
        df.loc[df["rsi"] > 70, "Signal"] = "Sell (RSI Overbought)"
        df.loc[df["rsi"] > 70, "signal_strength"] -= 1.5

    # Bollinger Band
    if "bb_low" in df.columns and "bb_high" in df.columns:
        bb_bounce = (df["close"] <= df["bb_low"]) & (df["close"].shift(1) > df["bb_low"].shift(1))
        df.loc[bb_bounce, "Signal"] = "Buy (Bollinger Band Bounce)"
        df.loc[bb_bounce, "signal_strength"] += 1.0
        bb_reject = (df["close"] >= df["bb_high"]) & (df["close"].shift(1) < df["bb_high"].shift(1))
        df.loc[bb_reject, "Signal"] = "Sell (Bollinger Band Rejection)"
        df.loc[bb_reject, "signal_strength"] -= 1.0

    # Supertrend
    if "supertrend_direction" in df.columns:
        st_buy = (df["supertrend_direction"] == 1) & (df["supertrend_direction"].shift(1) == -1)
        df.loc[st_buy, "Signal"] = "Buy (Supertrend Bullish Flip)"
        df.loc[st_buy, "signal_strength"] += 1.5
        st_sell = (df["supertrend_direction"] == -1) & (df["supertrend_direction"].shift(1) == 1)
        df.loc[st_sell, "Signal"] = "Sell (Supertrend Bearish Flip)"
        df.loc[st_sell, "signal_strength"] -= 1.5

    # Volume Breakout
    vol_avg = df["volume"].rolling(window=20).mean()
    vol_breakout = df["volume"] > 2 * vol_avg
    bullish_vol = vol_breakout & (df["close"] > df["close"].shift(1))
    bearish_vol = vol_breakout & (df["close"] < df["close"].shift(1))
    df.loc[bullish_vol, "signal_strength"] += 0.5
    df.loc[bearish_vol, "signal_strength"] -= 0.5

    # EMA Golden/Death Cross
    if "ema_50" in df.columns and "ema_200" in df.columns:
        golden = (df["ema_50"] > df["ema_200"]) & (df["ema_50"].shift(1) <= df["ema_200"].shift(1))
        death = (df["ema_50"] < df["ema_200"]) & (df["ema_50"].shift(1) >= df["ema_200"].shift(1))
        df.loc[golden, "Signal"] = "Buy (Golden Cross EMA50/200)"
        df.loc[golden, "signal_strength"] += 2.0
        df.loc[death, "Signal"] = "Sell (Death Cross EMA50/200)"
        df.loc[death, "signal_strength"] -= 2.0

    # ADX filter
    if "adx" in df.columns:
        weak_trend = df["adx"] < 20
        df.loc[weak_trend, "signal_strength"] *= 0.5

    # Greedy cut
    if "momentum_5" in df.columns and "rsi" in df.columns:
        df["momentum_change"] = df["momentum_5"] - df["momentum_5"].shift(1)
        greedy_sell = (df["momentum_5"] > 0) & (df["momentum_change"] < 0) & (df["rsi"] > 65)
        df.loc[greedy_sell, "Signal"] = "Sell (Greedy Cut on Sharp Momentum)"
        df.loc[greedy_sell, "signal_strength"] -= 0.8

    # Support/Resistance proximity
    if "support" in df.columns and "resistance" in df.columns:
        near_support = (df["close"] - df["support"]) / df["close"] < 0.02
        near_resistance = (df["resistance"] - df["close"]) / df["close"] < 0.02
        df.loc[near_support, "signal_strength"] += 0.3
        df.loc[near_resistance, "signal_strength"] -= 0.3

    return df
