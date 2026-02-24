"""
Rule-based signal generator with advanced quant logic.

Generates buy/sell/hold signals using:
  - MACD crossovers
  - RSI extremes
  - Bollinger Band breakouts
  - Supertrend direction changes
  - Volume breakouts
  - EMA golden cross / death cross
  - ATR-based stop-loss levels
  - ADX trend strength filtering
"""

import pandas as pd
import numpy as np
from feature_engineering import add_technical_indicators


def resample_data(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    rule_map = {
        "daily": "D",
        "weekly": "W",
        "monthly": "M",
        "quarterly": "Q",
    }
    if timeframe not in rule_map:
        raise ValueError("Timeframe must be one of: daily, weekly, monthly, quarterly")

    ohlc_dict = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    df_resampled = df.resample(rule_map[timeframe]).apply(ohlc_dict).dropna()
    return df_resampled


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate trading signals from technical indicators.

    Adds columns:
      - Signal: human-readable signal description
      - stop_loss: ATR-based stop-loss price
      - signal_strength: numeric score (positive=bullish, negative=bearish)
    """
    df["Signal"] = "Hold"
    df["signal_strength"] = 0.0

    # --- ATR-based stop-loss (2x ATR below close for longs) ---
    if "atr" in df.columns:
        df["stop_loss"] = df["close"] - 2 * df["atr"]
    else:
        df["stop_loss"] = df["close"] * 0.95  # fallback 5% below

    # --- MACD Bullish crossover ---
    if "macd" in df.columns:
        macd_cross_up = (df["macd"] > 0) & (df["macd"].shift(1) <= 0)
        df.loc[macd_cross_up, "Signal"] = "Buy (MACD Bullish Crossover)"
        df.loc[macd_cross_up, "signal_strength"] += 1.0

        macd_cross_down = (df["macd"] < 0) & (df["macd"].shift(1) >= 0)
        df.loc[macd_cross_down, "Signal"] = "Sell (MACD Bearish Crossover)"
        df.loc[macd_cross_down, "signal_strength"] -= 1.0

    # --- RSI extremes ---
    if "rsi" in df.columns:
        rsi_oversold = df["rsi"] < 30
        df.loc[rsi_oversold, "Signal"] = "Buy (RSI Oversold)"
        df.loc[rsi_oversold, "signal_strength"] += 1.5

        rsi_overbought = df["rsi"] > 70
        df.loc[rsi_overbought, "Signal"] = "Sell (RSI Overbought)"
        df.loc[rsi_overbought, "signal_strength"] -= 1.5

    # --- Bollinger Band Breakout ---
    if "bb_low" in df.columns and "bb_high" in df.columns:
        bb_bounce = (df["close"] <= df["bb_low"]) & (
            df["close"].shift(1) > df["bb_low"].shift(1)
        )
        df.loc[bb_bounce, "Signal"] = "Buy (Bollinger Band Bounce)"
        df.loc[bb_bounce, "signal_strength"] += 1.0

        bb_reject = (df["close"] >= df["bb_high"]) & (
            df["close"].shift(1) < df["bb_high"].shift(1)
        )
        df.loc[bb_reject, "Signal"] = "Sell (Bollinger Band Rejection)"
        df.loc[bb_reject, "signal_strength"] -= 1.0

    # --- Supertrend direction change ---
    if "supertrend_direction" in df.columns:
        st_buy = (df["supertrend_direction"] == 1) & (
            df["supertrend_direction"].shift(1) == -1
        )
        df.loc[st_buy, "Signal"] = "Buy (Supertrend Bullish Flip)"
        df.loc[st_buy, "signal_strength"] += 1.5

        st_sell = (df["supertrend_direction"] == -1) & (
            df["supertrend_direction"].shift(1) == 1
        )
        df.loc[st_sell, "Signal"] = "Sell (Supertrend Bearish Flip)"
        df.loc[st_sell, "signal_strength"] -= 1.5

    # --- Volume Breakout (volume > 2x 20-day avg) ---
    vol_avg = df["volume"].rolling(window=20).mean()
    vol_breakout = df["volume"] > 2 * vol_avg
    bullish_vol = vol_breakout & (df["close"] > df["close"].shift(1))
    bearish_vol = vol_breakout & (df["close"] < df["close"].shift(1))
    df.loc[bullish_vol, "signal_strength"] += 0.5
    df.loc[bearish_vol, "signal_strength"] -= 0.5

    # --- EMA Golden Cross / Death Cross ---
    if "ema_50" in df.columns and "ema_200" in df.columns:
        golden = (df["ema_50"] > df["ema_200"]) & (
            df["ema_50"].shift(1) <= df["ema_200"].shift(1)
        )
        death = (df["ema_50"] < df["ema_200"]) & (
            df["ema_50"].shift(1) >= df["ema_200"].shift(1)
        )
        df.loc[golden, "Signal"] = "Buy (Golden Cross EMA50/200)"
        df.loc[golden, "signal_strength"] += 2.0

        df.loc[death, "Signal"] = "Sell (Death Cross EMA50/200)"
        df.loc[death, "signal_strength"] -= 2.0

    # --- ADX trend strength filter ---
    if "adx" in df.columns:
        weak_trend = df["adx"] < 20
        df.loc[weak_trend, "signal_strength"] *= 0.5

    # --- Greedy Cut: Sharp upward momentum sell ---
    if "momentum_5" in df.columns and "rsi" in df.columns:
        df["momentum_change"] = df["momentum_5"] - df["momentum_5"].shift(1)
        greedy_sell = (
            (df["momentum_5"] > 0)
            & (df["momentum_change"] < 0)
            & (df["rsi"] > 65)
        )
        df.loc[greedy_sell, "Signal"] = "Sell (Greedy Cut on Sharp Momentum)"
        df.loc[greedy_sell, "signal_strength"] -= 0.8

    # --- Support/Resistance proximity ---
    if "support" in df.columns and "resistance" in df.columns:
        near_support = (df["close"] - df["support"]) / df["close"] < 0.02
        near_resistance = (df["resistance"] - df["close"]) / df["close"] < 0.02
        df.loc[near_support, "signal_strength"] += 0.3
        df.loc[near_resistance, "signal_strength"] -= 0.3

    return df


def compute_stop_loss(price: float, atr: float, multiplier: float = 2.0) -> float:
    """Compute ATR-based stop-loss for a long position."""
    return round(price - multiplier * atr, 2)


def compute_trailing_stop(
    price: float,
    highest_since_buy: float,
    atr: float,
    multiplier: float = 2.0,
) -> float:
    """
    Compute trailing stop-loss that follows price up but never down.

    Args:
        price: current price
        highest_since_buy: highest close since entry
        atr: current ATR value
        multiplier: ATR multiplier (default 2x)

    Returns:
        trailing stop-loss price
    """
    new_high = max(price, highest_since_buy)
    return round(new_high - multiplier * atr, 2)


def analyze_stock(df: pd.DataFrame, timeframe: str = "weekly") -> pd.DataFrame:
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    df = resample_data(df, timeframe)
    df = add_technical_indicators(df)
    df = generate_signals(df)
    return df
