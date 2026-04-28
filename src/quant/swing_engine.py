"""
Swing/position trading setup classification and structure-aware stops.

This module keeps the higher-timeframe trading thesis separate from the
faster signal-scoring code. It is intentionally small: identify the setup,
then produce an initial stop that matches the setup's invalidation level.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


NO_SETUP = "NO_SETUP"
BREAKOUT = "BREAKOUT"
PULLBACK = "PULLBACK"
CONTINUATION = "CONTINUATION"
REVERSAL = "REVERSAL"


@dataclass(frozen=True)
class SwingSetup:
    setup_type: str
    quality_score: int
    structure_level: float
    stop_loss: float
    reasons: list[str]

    @property
    def actionable(self) -> bool:
        return self.setup_type != NO_SETUP and self.quality_score >= 50

    def as_dict(self) -> dict:
        return {
            "setup_type": self.setup_type,
            "quality_score": self.quality_score,
            "structure_level": self.structure_level,
            "stop_loss": self.stop_loss,
            "reasons": self.reasons,
            "actionable": self.actionable,
        }


def classify_swing_setup(
    df_daily: pd.DataFrame,
    current_price: float | None = None,
    rvol: float = 1.0,
) -> SwingSetup:
    """
    Classify a stock into a swing setup using daily candles.

    The goal is not to predict. The goal is to say what kind of trade thesis
    exists so SL and exits can be matched to that thesis.
    """
    if df_daily is None or df_daily.empty or len(df_daily) < 60:
        return _empty_setup("Need at least 60 daily candles")

    df = _normalize_columns(df_daily.copy())
    latest = df.iloc[-1]
    price = float(current_price if current_price is not None else latest["close"])
    atr = _safe_float(latest.get("atr"), price * 0.02)
    rsi = _safe_float(latest.get("rsi"), 50.0)
    adx = _safe_float(latest.get("adx"), 0.0)
    ema21 = _safe_float(latest.get("ema_21"), price)
    ema50 = _safe_float(latest.get("ema_50"), price)
    ema200 = _safe_float(latest.get("ema_200"), price)
    cmf = _safe_float(latest.get("cmf"), 0.0)
    squeeze_fire = int(_safe_float(latest.get("squeeze_fire"), 0.0))

    high20 = float(df["high"].iloc[-21:-1].max())
    high52 = float(df["high"].iloc[-253:-1].max()) if len(df) >= 253 else high20
    swing_low = _recent_swing_low(df, lookback=20)

    trend_ok = price > ema50 > ema200
    strong_trend = trend_ok and adx >= 20
    volume_ok = rvol >= 1.3
    constructive_money_flow = cmf >= 0
    reasons: list[str] = []

    if price > high20 and volume_ok and trend_ok:
        quality = 55
        reasons.append(f"Price cleared prior 20-day high {high20:.2f}")
        reasons.append(f"Relative volume confirms demand ({rvol:.1f}x)")
        if price >= high52:
            quality += 10
            reasons.append("Price is also near/above the 52-week high")
        if adx >= 25:
            quality += 10
            reasons.append(f"ADX confirms trend strength ({adx:.1f})")
        if constructive_money_flow:
            quality += 5
            reasons.append("CMF is non-negative")
        stop = _bounded_stop(price, max(high20 - 0.5 * atr, swing_low - 0.25 * atr), atr)
        return SwingSetup(BREAKOUT, min(100, quality), round(high20, 2), stop, reasons)

    near_ema21 = _pct_distance(price, ema21) <= 3.0
    near_ema50 = _pct_distance(price, ema50) <= 3.5
    healthy_rsi = 38 <= rsi <= 62
    if trend_ok and healthy_rsi and (near_ema21 or near_ema50):
        quality = 50
        support = ema21 if near_ema21 else ema50
        reasons.append("Established uptrend with controlled pullback")
        reasons.append(f"Price is near {'21' if near_ema21 else '50'} EMA support")
        if constructive_money_flow:
            quality += 8
            reasons.append("CMF suggests accumulation has not broken")
        if rvol <= 1.4:
            quality += 7
            reasons.append("Pullback is not showing abnormal distribution volume")
        stop = _bounded_stop(price, min(swing_low, support) - 0.5 * atr, atr)
        return SwingSetup(PULLBACK, min(100, quality), round(support, 2), stop, reasons)

    if strong_trend and price > ema21 and (squeeze_fire or (rvol >= 1.1 and latest.get("momentum_5", 0) > 0)):
        quality = 48
        reasons.append("Strong trend remains intact")
        if squeeze_fire:
            quality += 15
            reasons.append("Volatility compression fired")
        if rvol >= 1.1:
            quality += 7
            reasons.append(f"Volume is supportive ({rvol:.1f}x)")
        stop = _bounded_stop(price, max(ema21 - 0.75 * atr, swing_low - 0.25 * atr), atr)
        return SwingSetup(CONTINUATION, min(100, quality), round(ema21, 2), stop, reasons)

    reclaimed_ema50 = price > ema50 and float(df["close"].iloc[-2]) <= float(df["ema_50"].iloc[-2])
    if price > ema200 and reclaimed_ema50 and rsi >= 45 and volume_ok:
        quality = 50
        reasons.append("Price reclaimed 50 EMA while above 200 EMA")
        reasons.append(f"Relative volume confirms reclaim ({rvol:.1f}x)")
        stop = _bounded_stop(price, min(swing_low, ema50) - 0.5 * atr, atr)
        return SwingSetup(REVERSAL, min(100, quality), round(ema50, 2), stop, reasons)

    return _empty_setup("No clean swing setup: wait for breakout, pullback, or continuation")


def _empty_setup(reason: str) -> SwingSetup:
    return SwingSetup(NO_SETUP, 0, 0.0, 0.0, [reason])


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).lower() for c in df.columns]
    return df


def _safe_float(value, default: float) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _pct_distance(price: float, level: float) -> float:
    if price <= 0 or level <= 0:
        return 999.0
    return abs(price - level) / price * 100


def _recent_swing_low(df: pd.DataFrame, lookback: int = 20) -> float:
    if df.empty:
        return 0.0
    lows = df["low"].iloc[-lookback:]
    return float(lows.min()) if not lows.empty else 0.0


def _bounded_stop(price: float, candidate_stop: float, atr: float) -> float:
    fallback = price - 1.5 * atr
    stop = candidate_stop if 0 < candidate_stop < price else fallback
    return round(max(0.01, stop), 2)
