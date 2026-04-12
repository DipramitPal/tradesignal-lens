"""
Adaptive stop-loss, take-profit, position sizing, and entry quality engine.

Implements:
  - 4-phase SL (initial → breakeven → trailing with SAR → exit triggers)
  - Weighted exit scoring (requires consensus ≥ 0.60 from multiple indicators)
  - Risk-based position sizing (regime-adaptive: 1%–2.5% per trade)
  - R:R minimum gate enforcement
  - Entry quality gate (score ≥ 50 to recommend BUY)
  - Portfolio-level risk controls
"""

import math
from typing import Optional

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import (
    RISK_PER_TRADE_PCT, MIN_RR_RATIO, MAX_OPEN_POSITIONS,
    MAX_SECTOR_EXPOSURE, DAILY_LOSS_LIMIT, DEFAULT_ACCOUNT_VALUE,
    EXIT_SCORE_THRESHOLD, REGIME_RISK_MAP,
)


# ------------------------------------------------------------------
# Stop-Loss
# ------------------------------------------------------------------

def compute_initial_sl(entry_price: float, atr_15m: float,
                       multiplier: float = 1.5) -> float:
    """Initial stop-loss = entry − 1.5 × ATR(15m)."""
    return round(entry_price - multiplier * atr_15m, 2)


def compute_phase_sl(
    entry_price: float,
    current_price: float,
    highest_since_entry: float,
    atr_15m: float,
    parabolic_sar: float,
    current_sl: float,
) -> tuple[float, str]:
    """
    4-phase adaptive stop-loss.

    Returns:
        (new_sl, phase_name)
    """
    r = entry_price - compute_initial_sl(entry_price, atr_15m)  # 1R distance
    if r <= 0:
        r = entry_price * 0.02  # fallback

    pnl = current_price - entry_price
    pnl_r = pnl / r if r > 0 else 0

    # Phase 4 checks are done via exit triggers (separate function)

    # Phase 3: Trailing (P&L ≥ 2R)
    if pnl_r >= 2.0:
        trailing = highest_since_entry - 1.0 * atr_15m
        # Use the better of trailing and SAR
        if parabolic_sar > 0:
            sar_based = parabolic_sar
            new_sl = max(trailing, sar_based)
        else:
            new_sl = trailing
        # Never lower the SL
        new_sl = max(new_sl, current_sl)
        return round(new_sl, 2), "TRAILING"

    # Phase 2: Breakeven (P&L ≥ 1R)
    if pnl_r >= 1.0:
        new_sl = max(entry_price, current_sl)
        return round(new_sl, 2), "BREAKEVEN"

    # Phase 1: Initial
    return current_sl, "INITIAL"


# ------------------------------------------------------------------
# Exit Triggers
# ------------------------------------------------------------------

def compute_exit_score(
    rsi_15m: float,
    supertrend_dir_15m: float,
    cmf: float,
    parabolic_sar: float,
    current_price: float,
    pivot_r3: float = 0,
    divergence_direction: str = "NONE",
    threshold: float = EXIT_SCORE_THRESHOLD,
) -> tuple[bool, float, list[str]]:
    """
    Weighted exit scoring — requires consensus from multiple indicators.

    Instead of exiting on a single trigger, each exit condition contributes
    a weighted score. Exit is recommended only when the total score ≥ threshold.

    Returns:
        (should_exit, exit_score, list_of_reasons)
    """
    score = 0.0
    reasons = []

    # RSI overbought: weight 0.30
    if rsi_15m > 80:
        score += 0.30
        reasons.append(f"RSI(15m) strongly overbought at {rsi_15m:.0f} (+0.30)")
    elif rsi_15m > 75:
        score += 0.20
        reasons.append(f"RSI(15m) overbought at {rsi_15m:.0f} (+0.20)")

    # Supertrend bearish flip: weight 0.40
    if supertrend_dir_15m == -1:
        score += 0.40
        reasons.append("Supertrend(15m) flipped bearish (+0.40)")

    # CMF institutional selling: weight 0.20
    if cmf < -0.15:
        score += 0.20
        reasons.append(f"CMF strongly negative ({cmf:.3f}) — heavy selling (+0.20)")
    elif cmf < -0.10:
        score += 0.12
        reasons.append(f"CMF negative ({cmf:.3f}) — institutional selling (+0.12)")

    # Parabolic SAR crossed above: weight 0.25
    if parabolic_sar > 0 and parabolic_sar > current_price:
        score += 0.25
        reasons.append(f"Parabolic SAR above price (+0.25)")

    # Bearish divergence: weight 0.35
    if "BEARISH" in divergence_direction:
        score += 0.35
        reasons.append("Bearish divergence detected (+0.35)")

    # Pivot R3 resistance: weight 0.15
    if pivot_r3 > 0 and current_price >= pivot_r3:
        score += 0.15
        reasons.append(f"Price at/above Camarilla R3 ({pivot_r3:.2f}) (+0.15)")

    should_exit = score >= threshold
    return should_exit, round(score, 2), reasons


# Backward-compatible alias
def check_exit_triggers(
    rsi_15m: float,
    supertrend_dir_15m: float,
    cmf: float,
    parabolic_sar: float,
    current_price: float,
    pivot_r3: float = 0,
    divergence_direction: str = "NONE",
) -> tuple[bool, list[str]]:
    """
    Backward-compatible wrapper for compute_exit_score.

    Returns:
        (should_exit, list_of_reasons)
    """
    should_exit, _score, reasons = compute_exit_score(
        rsi_15m, supertrend_dir_15m, cmf, parabolic_sar,
        current_price, pivot_r3, divergence_direction,
    )
    return should_exit, reasons


# ------------------------------------------------------------------
# Position Sizing
# ------------------------------------------------------------------

def compute_position_size(
    account_value: float,
    entry_price: float,
    stop_loss: float,
    risk_pct: float = RISK_PER_TRADE_PCT,
) -> int:
    """
    Risk-based position sizing.

    Returns:
        Number of shares to buy (integer).
    """
    risk_amount = account_value * risk_pct
    stop_distance = abs(entry_price - stop_loss)
    if stop_distance <= 0:
        return 0

    shares = math.floor(risk_amount / stop_distance)

    # Cap at 15% of account in a single position
    max_position_value = account_value * 0.15
    max_shares = math.floor(max_position_value / entry_price) if entry_price > 0 else 0
    shares = min(shares, max_shares)

    return max(shares, 0)


def compute_rr_ratio(entry: float, sl: float, target: float) -> float:
    """Compute risk-reward ratio."""
    risk = abs(entry - sl)
    reward = abs(target - entry)
    if risk <= 0:
        return 0.0
    return round(reward / risk, 2)


def check_rr_gate(
    entry: float,
    sl: float,
    pivot_r3: float = 0,
    min_rr: float = MIN_RR_RATIO,
) -> tuple[bool, float, str]:
    """
    Check if a trade meets the minimum risk-reward requirement.

    Uses pivot R3 as the target. If no pivot, estimates target as
    entry + 3×ATR-equivalent distance.

    Args:
        entry: Entry price
        sl: Stop-loss price
        pivot_r3: Camarilla R3 resistance or nearest target
        min_rr: Minimum acceptable R:R ratio

    Returns:
        (passes_gate, rr_ratio, reason)
    """
    risk = abs(entry - sl)
    if risk <= 0:
        return False, 0.0, "Zero risk distance — cannot compute R:R"

    # Use pivot R3 if available, otherwise estimate target as entry + 3R
    if pivot_r3 > entry:
        target = pivot_r3
    else:
        target = entry + 3 * risk  # Default to 3R target

    rr = compute_rr_ratio(entry, sl, target)

    if rr < min_rr:
        return (
            False, rr,
            f"R:R {rr:.1f} < {min_rr:.1f} min — insufficient risk-reward"
        )

    return True, rr, ""


def get_regime_risk_pct(regime: str) -> float:
    """
    Get the risk-per-trade percentage based on the current market regime.

    Defensive in downtrends/volatile markets, aggressive in uptrends.

    Returns:
        Risk percentage (e.g., 0.025 for 2.5%)
    """
    return REGIME_RISK_MAP.get(regime, RISK_PER_TRADE_PCT)


# ------------------------------------------------------------------
# Entry Quality Gate
# ------------------------------------------------------------------

def compute_entry_quality(
    current_price: float,
    rsi_15m: float,
    squeeze_fire: int,
    rvol: float,
    cmf: float,
    near_support: bool = False,
    near_fib_618: bool = False,
    news_sentiment: float = 0.0,
    pct_from_breakout: float = 0.0,
    earnings_within_5d: bool = False,
) -> int:
    """
    Compute entry quality score (0–100). BUY only recommended if ≥ 50.

    Args:
        current_price: latest close
        rsi_15m: current RSI on 15m
        squeeze_fire: 1 if squeeze just fired, 0 otherwise
        rvol: relative volume
        cmf: Chaikin Money Flow
        near_support: True if price within 1.5% of pivot S3 or support
        near_fib_618: True if price near Fibonacci 0.618 level
        news_sentiment: news sentiment score (-1 to +1). Negative = penalty
        pct_from_breakout: how far price has moved from breakout (%). >5% = late
        earnings_within_5d: True if earnings announcement within 5 trading days

    Returns:
        Entry quality score (0–100)
    """
    score = 0

    # Support / Fibonacci proximity
    if near_support or near_fib_618:
        score += 30

    # RSI sweet spot
    if rsi_15m < 45:
        score += 20
    elif rsi_15m < 55:
        score += 10

    # Squeeze fire
    if squeeze_fire:
        score += 25

    # Volume confirmation
    if rvol > 1.5:
        score += 15
    elif rvol > 1.0:
        score += 5

    # Institutional buying
    if cmf > 0:
        score += 10

    # --- NEW: News sentiment factor ---
    if news_sentiment < -0.3:
        score -= 15  # Strong negative news = penalty
    elif news_sentiment < -0.1:
        score -= 8
    elif news_sentiment > 0.3:
        score += 5   # Minor boost for positive news

    # --- NEW: Time-since-breakout penalty ---
    if pct_from_breakout > 8.0:
        score -= 20  # Very late entry
    elif pct_from_breakout > 5.0:
        score -= 12  # Late entry
    elif pct_from_breakout > 3.0:
        score -= 5   # Slightly late

    # --- NEW: Earnings proximity warning ---
    # Doesn't block the trade but reduces quality (event risk)
    if earnings_within_5d:
        score -= 10

    return max(0, min(score, 100))


# ------------------------------------------------------------------
# Portfolio-Level Limits
# ------------------------------------------------------------------

def check_portfolio_limits(
    open_positions: int,
    sector_counts: dict[str, int],
    total_positions: int = MAX_OPEN_POSITIONS,
    max_sector: float = MAX_SECTOR_EXPOSURE,
    current_sector: str = "",
) -> tuple[bool, str]:
    """
    Check if a new trade is allowed based on portfolio limits.

    Returns:
        (allowed, reason_if_blocked)
    """
    if open_positions >= total_positions:
        return False, f"Max {total_positions} open positions reached"

    if current_sector and sector_counts:
        sector_count = sector_counts.get(current_sector, 0)
        sector_pct = sector_count / max(open_positions, 1)
        if sector_pct >= max_sector and sector_count > 0:
            return False, f"Sector '{current_sector}' at {sector_pct:.0%} — exceeds {max_sector:.0%} limit"

    return True, ""
