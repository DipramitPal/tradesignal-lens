"""
Volatility Contraction Pattern (VCP) Detector.

Identifies stocks forming tight consolidation bases with progressively
narrowing price swings and declining volume — the hallmark of supply
exhaustion before a breakout (Mark Minervini / William O'Neil framework).

Detection logic:
  1. Find the consolidation base (price range contraction over time)
  2. Verify consecutive tightening swings: ΔP₁ > ΔP₂ > ΔP₃
  3. Confirm volume dry-up: right-half avg volume < left-half by threshold
  4. Score the pattern quality (0-100)

Usage:
    from quant.vcp_detector import detect_vcp, detect_vcp_breakout
    result = detect_vcp(df_daily)
    if result.is_vcp:
        bo = detect_vcp_breakout(df_daily, result, current_price, rvol)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class VCPResult:
    """Result of VCP detection on a daily price series."""

    is_vcp: bool
    num_contractions: int
    tightness_ratio: float          # ratio of last swing to first swing (< 1.0 = tighter)
    volume_dryup_pct: float         # how much volume dropped (0.40 = 40% less)
    base_length_days: int
    ceiling_price: float            # resistance ceiling of the base
    floor_price: float              # lowest low of the last contraction
    quality_score: int              # 0-100
    swing_ranges: list[float] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


_EMPTY_VCP = VCPResult(
    is_vcp=False, num_contractions=0, tightness_ratio=0.0,
    volume_dryup_pct=0.0, base_length_days=0, ceiling_price=0.0,
    floor_price=0.0, quality_score=0, swing_ranges=[], reasons=[],
)


def detect_vcp(
    df_daily: pd.DataFrame,
    min_contractions: int = 2,
    vol_dryup_pct: float = 0.30,
    min_base_days: int = 15,
    max_base_days: int = 180,
    lookback: int = 120,
) -> VCPResult:
    """
    Detect a Volatility Contraction Pattern on daily candles.

    Args:
        df_daily:          DataFrame with 'high', 'low', 'close', 'volume' columns.
        min_contractions:  Minimum number of tightening swings required (default: 2).
        vol_dryup_pct:     Minimum volume reduction in right half vs left half (default: 0.30 = 30%).
        min_base_days:     Minimum consolidation base length in trading days.
        max_base_days:     Maximum base length (beyond this it's dead money, not a VCP).
        lookback:          How far back to search for the base (trading days).

    Returns:
        VCPResult with detection details and quality score.
    """
    if df_daily is None or df_daily.empty or len(df_daily) < max(60, min_base_days + 10):
        return _EMPTY_VCP

    df = _normalize(df_daily.copy())
    df = df.iloc[-lookback:]  # limit search window

    if len(df) < min_base_days:
        return _EMPTY_VCP

    # --- Step 1: Find the consolidation base ---
    # The base starts from the highest high in the lookback and ends at the latest bar.
    ceiling_idx = df["high"].idxmax()
    ceiling_pos = df.index.get_loc(ceiling_idx)
    ceiling_price = float(df["high"].loc[ceiling_idx])

    # Base must be at least min_base_days long
    base_length = len(df) - ceiling_pos
    if base_length < min_base_days or base_length > max_base_days:
        return _EMPTY_VCP

    base_df = df.iloc[ceiling_pos:]

    # --- Step 2: Identify swing highs and lows to find contractions ---
    swings = _find_swing_ranges(base_df, min_swing_bars=3)

    if len(swings) < min_contractions:
        return VCPResult(
            is_vcp=False, num_contractions=len(swings),
            tightness_ratio=0.0, volume_dryup_pct=0.0,
            base_length_days=base_length, ceiling_price=ceiling_price,
            floor_price=0.0, quality_score=0, swing_ranges=swings,
            reasons=[f"Only {len(swings)} contractions found, need ≥ {min_contractions}"],
        )

    # --- Step 3: Verify consecutive tightening ---
    is_tightening = all(swings[i] > swings[i + 1] for i in range(len(swings) - 1))
    if not is_tightening:
        return VCPResult(
            is_vcp=False, num_contractions=len(swings),
            tightness_ratio=swings[-1] / (swings[0] + 1e-10),
            volume_dryup_pct=0.0, base_length_days=base_length,
            ceiling_price=ceiling_price, floor_price=0.0,
            quality_score=0, swing_ranges=swings,
            reasons=["Swings are not consecutively tightening"],
        )

    tightness_ratio = swings[-1] / (swings[0] + 1e-10)

    # --- Step 4: Volume dry-up check ---
    vol = base_df["volume"].values
    mid = len(vol) // 2
    left_vol = float(np.nanmean(vol[:mid])) if mid > 0 else 1.0
    right_vol = float(np.nanmean(vol[mid:])) if mid < len(vol) else 1.0
    actual_dryup = 1.0 - (right_vol / (left_vol + 1e-10))

    volume_passes = actual_dryup >= vol_dryup_pct

    # --- Step 5: Score the VCP quality ---
    floor_price = float(base_df["low"].iloc[-min(10, len(base_df)):].min())
    quality, reasons = _score_vcp(
        swings, tightness_ratio, actual_dryup, vol_dryup_pct,
        volume_passes, base_length, ceiling_price, floor_price,
    )

    is_vcp = is_tightening and volume_passes and len(swings) >= min_contractions

    return VCPResult(
        is_vcp=is_vcp,
        num_contractions=len(swings),
        tightness_ratio=round(tightness_ratio, 3),
        volume_dryup_pct=round(actual_dryup, 3),
        base_length_days=base_length,
        ceiling_price=round(ceiling_price, 2),
        floor_price=round(floor_price, 2),
        quality_score=quality,
        swing_ranges=[round(s, 4) for s in swings],
        reasons=reasons,
    )


def detect_vcp_breakout(
    df_daily: pd.DataFrame,
    vcp: VCPResult,
    current_price: float,
    rvol: float = 1.0,
    min_rvol: float = 1.3,
    chase_limit_pct: float = 2.0,
) -> dict:
    """
    Check if price is breaking out of a confirmed VCP pattern.

    Args:
        df_daily:         Daily OHLCV DataFrame.
        vcp:              VCPResult from detect_vcp().
        current_price:    Live/latest price.
        rvol:             Relative volume.
        min_rvol:         Minimum RVOL for breakout confirmation.
        chase_limit_pct:  Max % above ceiling before the setup is stale.

    Returns:
        dict with breakout status, stop_loss, and flags.
    """
    if not vcp.is_vcp or vcp.ceiling_price <= 0:
        return {
            "is_breakout": False,
            "is_stale": False,
            "ceiling": 0.0,
            "stop_loss": 0.0,
            "pct_above_ceiling": 0.0,
        }

    pct_above = ((current_price - vcp.ceiling_price) / vcp.ceiling_price) * 100

    # Chase threshold — if price has run too far above the ceiling, it's stale
    is_stale = pct_above > chase_limit_pct

    # Breakout = price above ceiling + volume confirmation + not stale
    is_breakout = (
        current_price > vcp.ceiling_price
        and rvol >= min_rvol
        and not is_stale
    )

    # Stop-loss: below the floor of the last contraction
    stop_loss = vcp.floor_price

    return {
        "is_breakout": is_breakout,
        "is_stale": is_stale,
        "ceiling": vcp.ceiling_price,
        "stop_loss": round(stop_loss, 2),
        "pct_above_ceiling": round(pct_above, 2),
        "vcp_quality": vcp.quality_score,
        "num_contractions": vcp.num_contractions,
        "tightness": vcp.tightness_ratio,
        "volume_dryup": vcp.volume_dryup_pct,
    }


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase column names."""
    df.columns = [str(c).lower() for c in df.columns]
    return df


def _find_swing_ranges(
    df: pd.DataFrame,
    min_swing_bars: int = 3,
) -> list[float]:
    """
    Find swing ranges (high-low distance) within a consolidation base.

    Splits the base into chunks and measures the price range of each chunk.
    Returns the ranges as percentages of the base ceiling.

    This is a practical approximation: instead of trying to find exact
    pivot highs/lows (which is noisy), we split the base into equal
    segments and measure the range contraction across segments.
    """
    n = len(df)
    if n < min_swing_bars * 2:
        return []

    # Determine segment count based on base length
    if n >= 60:
        num_segments = 4
    elif n >= 30:
        num_segments = 3
    else:
        num_segments = 2

    segment_size = n // num_segments
    if segment_size < min_swing_bars:
        return []

    ranges = []
    ceiling = float(df["high"].max())
    if ceiling <= 0:
        return []

    for i in range(num_segments):
        start = i * segment_size
        end = start + segment_size if i < num_segments - 1 else n
        segment = df.iloc[start:end]

        seg_high = float(segment["high"].max())
        seg_low = float(segment["low"].min())
        swing_range = (seg_high - seg_low) / ceiling  # as % of ceiling
        ranges.append(swing_range)

    return ranges


def _score_vcp(
    swings: list[float],
    tightness_ratio: float,
    actual_dryup: float,
    required_dryup: float,
    volume_passes: bool,
    base_length: int,
    ceiling: float,
    floor: float,
) -> tuple[int, list[str]]:
    """Score VCP quality from 0-100 with reasons."""
    score = 0
    reasons: list[str] = []

    # Number of contractions (max +25)
    if len(swings) >= 4:
        score += 25
        reasons.append(f"{len(swings)} contractions detected (excellent)")
    elif len(swings) >= 3:
        score += 20
        reasons.append(f"{len(swings)} contractions detected (good)")
    elif len(swings) >= 2:
        score += 12
        reasons.append(f"{len(swings)} contractions detected (minimum)")

    # Tightness ratio (max +25)
    if tightness_ratio <= 0.30:
        score += 25
        reasons.append(f"Extremely tight contraction ({tightness_ratio:.1%})")
    elif tightness_ratio <= 0.50:
        score += 20
        reasons.append(f"Good contraction ({tightness_ratio:.1%})")
    elif tightness_ratio <= 0.70:
        score += 12
        reasons.append(f"Moderate contraction ({tightness_ratio:.1%})")
    else:
        score += 5
        reasons.append(f"Loose contraction ({tightness_ratio:.1%})")

    # Volume dry-up (max +25)
    if volume_passes:
        if actual_dryup >= 0.50:
            score += 25
            reasons.append(f"Strong volume dry-up ({actual_dryup:.0%})")
        elif actual_dryup >= 0.40:
            score += 20
            reasons.append(f"Good volume dry-up ({actual_dryup:.0%})")
        else:
            score += 15
            reasons.append(f"Adequate volume dry-up ({actual_dryup:.0%})")
    else:
        reasons.append(f"Volume dry-up insufficient ({actual_dryup:.0%} < {required_dryup:.0%})")

    # Base length (max +15)
    if 25 <= base_length <= 90:
        score += 15
        reasons.append(f"Optimal base length ({base_length} days)")
    elif 15 <= base_length <= 120:
        score += 10
        reasons.append(f"Acceptable base length ({base_length} days)")
    else:
        score += 3
        reasons.append(f"Non-ideal base length ({base_length} days)")

    # Price depth — how much the base has corrected from ceiling (max +10)
    if ceiling > 0 and floor > 0:
        depth_pct = (ceiling - floor) / ceiling * 100
        if depth_pct <= 15:
            score += 10
            reasons.append(f"Shallow base depth ({depth_pct:.1f}%)")
        elif depth_pct <= 25:
            score += 7
            reasons.append(f"Moderate base depth ({depth_pct:.1f}%)")
        elif depth_pct <= 35:
            score += 3
            reasons.append(f"Deep base ({depth_pct:.1f}%)")
        else:
            reasons.append(f"Very deep base ({depth_pct:.1f}%) — higher risk")

    return min(100, score), reasons
