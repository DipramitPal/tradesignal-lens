"""
Divergence detection engine for RSI, MACD histogram, and OBV.

Detects:
  - Regular Bullish divergence (price LL, indicator HL)
  - Regular Bearish divergence (price HH, indicator LH)
  - Hidden Bullish divergence (price HL, indicator LL)
  - Hidden Bearish divergence (price LH, indicator HH)
"""

import pandas as pd
import numpy as np
from typing import Optional


def find_swing_points(series: pd.Series, order: int = 5) -> list[dict]:
    """
    Find local swing highs and lows in a series.

    Args:
        series: data series to analyze
        order: number of bars on each side to confirm a swing point

    Returns:
        List of dicts with 'index', 'value', 'type' ('high' or 'low')
    """
    swings = []
    values = series.values
    n = len(values)

    for i in range(order, n - order):
        if pd.isna(values[i]):
            continue

        # Check for swing high
        is_high = True
        for j in range(1, order + 1):
            if pd.isna(values[i - j]) or pd.isna(values[i + j]):
                is_high = False
                break
            if values[i] <= values[i - j] or values[i] <= values[i + j]:
                is_high = False
                break
        if is_high:
            swings.append({"index": i, "value": float(values[i]), "type": "high"})

        # Check for swing low
        is_low = True
        for j in range(1, order + 1):
            if pd.isna(values[i - j]) or pd.isna(values[i + j]):
                is_low = False
                break
            if values[i] >= values[i - j] or values[i] >= values[i + j]:
                is_low = False
                break
        if is_low:
            swings.append({"index": i, "value": float(values[i]), "type": "low"})

    return swings


def detect_divergence(
    price_series: pd.Series,
    indicator_series: pd.Series,
    lookback: int = 50,
    swing_order: int = 5,
) -> Optional[dict]:
    """
    Detect divergence between price and an indicator.

    Args:
        price_series: close price series
        indicator_series: indicator values (RSI, MACD hist, OBV, etc.)
        lookback: number of bars to look back for swing points
        swing_order: bars on each side to confirm swing

    Returns:
        dict with 'type', 'confidence' or None if no divergence found
    """
    # Use only the last N bars
    if len(price_series) < lookback:
        return None

    price_recent = price_series.iloc[-lookback:]
    ind_recent = indicator_series.iloc[-lookback:]

    price_swings = find_swing_points(price_recent, order=swing_order)
    ind_swings = find_swing_points(ind_recent, order=swing_order)

    if len(price_swings) < 2 or len(ind_swings) < 2:
        return None

    # Get last two swing lows
    price_lows = [s for s in price_swings if s["type"] == "low"]
    price_highs = [s for s in price_swings if s["type"] == "high"]
    ind_lows = [s for s in ind_swings if s["type"] == "low"]
    ind_highs = [s for s in ind_swings if s["type"] == "high"]

    # --- Regular Bullish: Price Lower Low, Indicator Higher Low ---
    if len(price_lows) >= 2 and len(ind_lows) >= 2:
        p1, p2 = price_lows[-2], price_lows[-1]
        i1, i2 = ind_lows[-2], ind_lows[-1]
        if p2["value"] < p1["value"] and i2["value"] > i1["value"]:
            return {"type": "BULLISH_DIVERGENCE", "confidence": 0.85,
                    "detail": "Price made lower low, indicator made higher low"}

    # --- Regular Bearish: Price Higher High, Indicator Lower High ---
    if len(price_highs) >= 2 and len(ind_highs) >= 2:
        p1, p2 = price_highs[-2], price_highs[-1]
        i1, i2 = ind_highs[-2], ind_highs[-1]
        if p2["value"] > p1["value"] and i2["value"] < i1["value"]:
            return {"type": "BEARISH_DIVERGENCE", "confidence": 0.85,
                    "detail": "Price made higher high, indicator made lower high"}

    # --- Hidden Bullish: Price Higher Low, Indicator Lower Low ---
    if len(price_lows) >= 2 and len(ind_lows) >= 2:
        p1, p2 = price_lows[-2], price_lows[-1]
        i1, i2 = ind_lows[-2], ind_lows[-1]
        if p2["value"] > p1["value"] and i2["value"] < i1["value"]:
            return {"type": "HIDDEN_BULLISH", "confidence": 0.70,
                    "detail": "Price higher low, indicator lower low (trend continuation)"}

    # --- Hidden Bearish: Price Lower High, Indicator Higher High ---
    if len(price_highs) >= 2 and len(ind_highs) >= 2:
        p1, p2 = price_highs[-2], price_highs[-1]
        i1, i2 = ind_highs[-2], ind_highs[-1]
        if p2["value"] < p1["value"] and i2["value"] > i1["value"]:
            return {"type": "HIDDEN_BEARISH", "confidence": 0.70,
                    "detail": "Price lower high, indicator higher high (trend continuation)"}

    return None


def detect_all_divergences(df: pd.DataFrame, lookback: int = 50) -> list[dict]:
    """
    Run divergence detection on RSI, MACD histogram, and OBV.

    Returns:
        List of divergence results with indicator name and type.
    """
    divergences = []
    price = df["close"]

    # RSI divergence
    if "rsi" in df.columns:
        div = detect_divergence(price, df["rsi"], lookback=lookback)
        if div:
            div["indicator"] = "RSI"
            divergences.append(div)

    # MACD histogram divergence
    if "macd_hist" in df.columns:
        div = detect_divergence(price, df["macd_hist"], lookback=lookback)
        if div:
            div["indicator"] = "MACD_HIST"
            divergences.append(div)

    # OBV divergence
    if "obv" in df.columns:
        div = detect_divergence(price, df["obv"], lookback=lookback)
        if div:
            div["indicator"] = "OBV"
            divergences.append(div)

    return divergences


def summarize_divergences(divergences: list[dict]) -> dict:
    """
    Summarize divergence results into a combined signal.

    Returns:
        dict with 'direction' (BULLISH/BEARISH/NONE), 'count', 'confidence',
        'details' list.
    """
    if not divergences:
        return {"direction": "NONE", "count": 0, "confidence": 0.0, "details": []}

    bullish = [d for d in divergences if "BULLISH" in d["type"]]
    bearish = [d for d in divergences if "BEARISH" in d["type"]]

    if len(bullish) > len(bearish):
        avg_conf = sum(d["confidence"] for d in bullish) / len(bullish)
        # Multi-indicator confirmation boosts confidence
        if len(bullish) >= 2:
            avg_conf = min(avg_conf * 1.15, 0.95)
        return {
            "direction": "BULLISH",
            "count": len(bullish),
            "confidence": round(avg_conf, 2),
            "details": [f"{d['indicator']}: {d['detail']}" for d in bullish],
        }
    elif len(bearish) > len(bullish):
        avg_conf = sum(d["confidence"] for d in bearish) / len(bearish)
        if len(bearish) >= 2:
            avg_conf = min(avg_conf * 1.15, 0.95)
        return {
            "direction": "BEARISH",
            "count": len(bearish),
            "confidence": round(avg_conf, 2),
            "details": [f"{d['indicator']}: {d['detail']}" for d in bearish],
        }
    else:
        return {"direction": "MIXED", "count": len(divergences),
                "confidence": 0.5, "details": []}
