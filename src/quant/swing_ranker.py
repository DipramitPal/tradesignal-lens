"""
Swing stock ranking model.

This converts a candidate into a single priority score for position trading.
Unlike the raw MTF score, this emphasizes relative strength, medium-term
momentum, trend quality, liquidity/volume, setup quality, and risk distance.

Components and weights:
  momentum (20%) — 3-month and 6-month price return
  trend    (16%) — EMA ladder + ADX
  setup    (16%) — swing setup type × quality
  signal   (12%) — MTF confluence score
  rs       (11%) — relative strength vs NIFTY 50/500 benchmark
  entry     (8%) — entry quality gate
  volume    (7%) — relative volume
  sector    (5%) — sector rotation phase
  risk      (5%) — stop-loss distance quality
"""

from __future__ import annotations

import pandas as pd


def compute_swing_rank(
    df_daily: pd.DataFrame,
    *,
    price: float,
    swing_setup: dict,
    mtf_score: float,
    entry_quality: int,
    rvol: float,
    sector_multiplier: float = 1.0,
    rs_ratio: float = 1.0,
) -> dict:
    """
    Return a 0-100 ranking score and component breakdown.

    This is designed for cross-sectional sorting: "which candidate deserves
    capital first?" It should be used after the setup and risk gates.

    Args:
        rs_ratio: Relative strength ratio vs benchmark (NIFTY 50/500).
                  >1.0 = outperforming, <1.0 = underperforming.
                  Defaults to 1.0 (neutral) when benchmark data is unavailable.
    """
    if df_daily is None or df_daily.empty or len(df_daily) < 65 or price <= 0:
        return _empty_rank("Need at least 65 daily candles")

    df = df_daily.copy()
    df.columns = [str(c).lower() for c in df.columns]
    latest = df.iloc[-1]

    momentum_3m = _return_pct(df, 63)
    momentum_6m = _return_pct(df, 126)
    trend_score = _trend_score(price, latest)
    volume_score = _volume_score(rvol)
    setup_score = _setup_score(swing_setup)
    signal_score = _scale(mtf_score, 0.20, 0.70)
    entry_score = max(0, min(100, entry_quality))
    risk_score = _risk_score(price, float(swing_setup.get("stop_loss") or 0))
    rs_score = _rs_score(rs_ratio)

    momentum_score = 0.65 * _scale(momentum_3m, 5, 30) + 0.35 * _scale(momentum_6m, 8, 55)
    sector_score = max(0, min(100, 50 + (sector_multiplier - 1.0) * 100))

    raw = (
        momentum_score * 0.20
        + trend_score * 0.16
        + setup_score * 0.16
        + signal_score * 0.12
        + rs_score * 0.11
        + entry_score * 0.08
        + volume_score * 0.07
        + sector_score * 0.05
        + risk_score * 0.05
    )

    score = round(max(0, min(100, raw)), 1)
    bucket = _bucket(score)

    return {
        "score": score,
        "bucket": bucket,
        "components": {
            "momentum": round(momentum_score, 1),
            "trend": round(trend_score, 1),
            "setup": round(setup_score, 1),
            "signal": round(signal_score, 1),
            "rs": round(rs_score, 1),
            "entry": round(entry_score, 1),
            "volume": round(volume_score, 1),
            "sector": round(sector_score, 1),
            "risk": round(risk_score, 1),
        },
        "metrics": {
            "momentum_3m_pct": round(momentum_3m, 2),
            "momentum_6m_pct": round(momentum_6m, 2),
            "risk_pct": round(_risk_pct(price, float(swing_setup.get("stop_loss") or 0)), 2),
            "rs_ratio": round(rs_ratio, 3),
        },
        "reason": "",
    }


def _empty_rank(reason: str) -> dict:
    return {
        "score": 0.0,
        "bucket": "AVOID",
        "components": {},
        "metrics": {},
        "reason": reason,
    }


def _return_pct(df: pd.DataFrame, lookback: int) -> float:
    if len(df) <= lookback:
        return 0.0
    start = float(df["close"].iloc[-lookback])
    end = float(df["close"].iloc[-1])
    if start <= 0:
        return 0.0
    return (end - start) / start * 100


def _trend_score(price: float, latest: pd.Series) -> float:
    ema21 = _safe_float(latest.get("ema_21"), price)
    ema50 = _safe_float(latest.get("ema_50"), price)
    ema200 = _safe_float(latest.get("ema_200"), price)
    adx = _safe_float(latest.get("adx"), 0)

    score = 0.0
    if price > ema21:
        score += 20
    if price > ema50:
        score += 20
    if price > ema200:
        score += 20
    if ema50 > ema200:
        score += 20
    score += max(0, min(20, (adx - 15) * 2))
    return score


def _volume_score(rvol: float) -> float:
    if rvol >= 2.0:
        return 100.0
    if rvol >= 1.5:
        return 80.0
    if rvol >= 1.1:
        return 60.0
    if rvol >= 0.8:
        return 40.0
    return 20.0


def _setup_score(swing_setup: dict) -> float:
    setup_type = swing_setup.get("setup_type", "NO_SETUP")
    quality = float(swing_setup.get("quality_score") or 0)
    multiplier = {
        "BREAKOUT": 1.10,
        "PULLBACK": 1.00,
        "CONTINUATION": 0.95,
        "REVERSAL": 0.75,
        "NO_SETUP": 0.0,
    }.get(setup_type, 0.0)
    return max(0, min(100, quality * multiplier))


def _risk_score(price: float, stop_loss: float) -> float:
    risk_pct = _risk_pct(price, stop_loss)
    if risk_pct <= 0:
        return 0.0
    if 4 <= risk_pct <= 10:
        return 100.0
    if risk_pct < 4:
        return 70.0
    if risk_pct <= 14:
        return 65.0
    if risk_pct <= 18:
        return 35.0
    return 10.0


def _risk_pct(price: float, stop_loss: float) -> float:
    if price <= 0 or stop_loss <= 0 or stop_loss >= price:
        return 0.0
    return (price - stop_loss) / price * 100


def _rs_score(rs_ratio: float) -> float:
    """
    Convert a relative-strength ratio into a 0-100 score.

    RS ratio > 1.0 means the stock outperforms the benchmark.
    The score ramps from 0 (RS ≤ 0.70) to 100 (RS ≥ 1.30).
    Neutral (RS = 1.0) → 50.
    """
    return _scale(rs_ratio, 0.70, 1.30)


def _scale(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return max(0, min(100, (value - low) / (high - low) * 100))


def _safe_float(value, default: float) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _bucket(score: float) -> str:
    if score >= 80:
        return "A+"
    if score >= 68:
        return "A"
    if score >= 55:
        return "B"
    if score >= 40:
        return "C"
    return "AVOID"
