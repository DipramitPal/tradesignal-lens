"""
Adaptive stop-loss, take-profit, position sizing, and entry quality engine.

Implements:
  - 4-phase SL (initial → breakeven → trailing with SAR → exit triggers)
  - Risk-based position sizing (2% per trade)
  - Entry quality gate (score ≥ 50 to recommend BUY)
  - Portfolio-level risk controls
  - Exit trigger checking
"""

import math
from typing import Optional

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import (
    RISK_PER_TRADE_PCT, MIN_RR_RATIO, MAX_OPEN_POSITIONS,
    MAX_SECTOR_EXPOSURE, DAILY_LOSS_LIMIT, DEFAULT_ACCOUNT_VALUE,
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
    Check multiple exit conditions.

    Returns:
        (should_exit, list_of_reasons)
    """
    reasons = []

    if rsi_15m > 75:
        reasons.append(f"RSI(15m) overbought at {rsi_15m:.0f}")

    if supertrend_dir_15m == -1:
        reasons.append("Supertrend(15m) flipped bearish")

    if cmf < -0.10:
        reasons.append(f"CMF negative ({cmf:.3f}) — institutional selling")

    if parabolic_sar > 0 and parabolic_sar > current_price:
        reasons.append("Parabolic SAR crossed above price")

    if pivot_r3 > 0 and current_price >= pivot_r3:
        reasons.append(f"Price at/above Camarilla R3 ({pivot_r3:.2f})")

    if "BEARISH" in divergence_direction:
        reasons.append(f"Bearish divergence detected")

    return len(reasons) >= 1, reasons


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

    Returns:
        Entry quality score (0–100)
    """
    score = 0

    if near_support or near_fib_618:
        score += 30
    if rsi_15m < 45:
        score += 20
    elif rsi_15m < 55:
        score += 10
    if squeeze_fire:
        score += 25
    if rvol > 1.5:
        score += 15
    elif rvol > 1.0:
        score += 5
    if cmf > 0:
        score += 10

    return min(score, 100)


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
