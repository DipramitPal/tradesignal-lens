"""
Verification script for all 13 trading logic improvements.
Tests imports, function signatures, and basic behavior.
Output is written to verify_results.txt for viewing.
"""
import sys
import os

# Fix encoding for Windows
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in dir() else os.getcwd()
sys.path.insert(0, os.path.join(SCRIPT_DIR, "src"))
os.chdir(SCRIPT_DIR)

# Redirect output to file for reliable reading on Windows
import io
_output_lines = []
_orig_print = print
def print(*args, **kwargs):
    buf = io.StringIO()
    _orig_print(*args, file=buf, **kwargs)
    line = buf.getvalue()
    _output_lines.append(line)
    try:
        _orig_print(line, end='')
    except Exception:
        pass

passed = 0
failed = 0
errors = []

def check(name, condition, detail=""):
    global passed, failed, errors
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        errors.append(f"{name}: {detail}")
        print(f"  [FAIL] {name} -- {detail}")


print("=" * 60)
print("TRADING LOGIC IMPROVEMENTS — VERIFICATION")
print("=" * 60)

# =====================================================
# 1. Settings imports
# =====================================================
print("\n--- 1. Settings ---")
try:
    from settings import (
        TRADE_JOURNAL_FILE, CORRELATION_LOOKBACK, MAX_CORRELATION,
        MAX_DRAWDOWN_PCT, MAX_DAILY_VAR_PCT, EXIT_SCORE_THRESHOLD,
        REGIME_RISK_MAP, SCALING_LOTS, GAP_THRESHOLD_PCT,
        MARKET_OPEN_BUFFER_MINUTES, MARKET_CLOSE_BUFFER_MINUTES,
    )
    check("New settings imported", True)
    check("REGIME_RISK_MAP has 4 regimes", len(REGIME_RISK_MAP) == 4)
    check("SCALING_LOTS default is 3", SCALING_LOTS == 3)
    check("EXIT_SCORE_THRESHOLD is 0.60", EXIT_SCORE_THRESHOLD == 0.60)
    check("GAP_THRESHOLD_PCT is 3.0", GAP_THRESHOLD_PCT == 3.0)
except Exception as e:
    check("Settings import", False, str(e))

# =====================================================
# 2. Trade Journal
# =====================================================
print("\n--- 2. Trade Journal ---")
try:
    from quant.trade_journal import TradeJournal
    import tempfile, json

    # Use temp file for testing
    tmp = os.path.join(tempfile.gettempdir(), "test_journal.json")
    try:
        os.remove(tmp)
    except FileNotFoundError:
        pass

    journal = TradeJournal(journal_path=tmp)
    check("TradeJournal created", True)

    # Log entry
    journal.log_entry(
        symbol="TEST.NS", entry_price=100.0, shares=30,
        stop_loss=97.0, regime="TRENDING_UP", signal_score=0.65,
        entry_quality=75, sector="IT", lots=3,
    )
    check("log_entry works", "TEST.NS" in journal.open_trades)

    # Log partial exit
    journal.log_partial_exit(
        symbol="TEST.NS", exit_price=103.0, shares_sold=10, reason="1R partial"
    )
    check("log_partial_exit works",
          len(journal.open_trades["TEST.NS"]["partial_exits"]) == 1)

    # Log full exit
    journal.log_exit(symbol="TEST.NS", exit_price=106.0, reason="Take profit")
    check("log_exit works", len(journal.trades) == 1)
    check("Trade has R-multiple", journal.trades[0].get("r_multiple") is not None)
    check("Trade has is_winner", journal.trades[0].get("is_winner") == True)

    # Metrics
    metrics = journal.get_performance_metrics(lookback_days=30)
    check("get_performance_metrics works", metrics["total_trades"] == 1)
    check("Win rate computed", metrics["win_rate"] == 1.0)

    # Adaptive risk
    risk = journal.get_adaptive_risk_pct()
    check("get_adaptive_risk_pct returns float", isinstance(risk, float))

    # Summary text
    summary = journal.get_summary_text()
    check("get_summary_text works", len(summary) > 10)

    # Cleanup
    os.remove(tmp)
except Exception as e:
    check("Trade Journal", False, str(e))

# =====================================================
# 3. Correlation Engine
# =====================================================
print("\n--- 3. Correlation Engine ---")
try:
    import pandas as pd
    import numpy as np
    from quant.correlation_engine import CorrelationEngine

    engine = CorrelationEngine(account_value=1000000)
    check("CorrelationEngine created", True)

    # Create mock daily data
    dates = pd.date_range("2024-01-01", periods=40, freq="D")
    np.random.seed(42)
    mock_data = {
        "SYM_A": pd.DataFrame({
            "close": 100 + np.cumsum(np.random.randn(40))
        }, index=dates),
        "SYM_B": pd.DataFrame({
            "close": 100 + np.cumsum(np.random.randn(40))
        }, index=dates),
        "SYM_C": pd.DataFrame({
            "close": 100 + np.cumsum(np.random.randn(40) * 0.1)
        }, index=dates),
    }
    # Make SYM_C highly correlated with SYM_A
    mock_data["SYM_C"]["close"] = mock_data["SYM_A"]["close"] * 1.05 + np.random.randn(40) * 0.1

    # Correlation matrix
    corr = engine.compute_correlation_matrix(mock_data, ["SYM_A", "SYM_B", "SYM_C"])
    check("Correlation matrix computed", not corr.empty)
    check("Matrix is 3x3", corr.shape == (3, 3))

    # Correlation conflict
    has_conflict, max_corr, conflicting = engine.check_correlation_conflict(
        "SYM_C", ["SYM_A"], mock_data
    )
    check("High correlation detected", has_conflict or max_corr > 0.5,
          f"corr={max_corr}")

    # Position size adjustment
    adj_shares, reason = engine.get_position_size_adjustment(
        "SYM_C", ["SYM_A"], mock_data, 100
    )
    check("Position adjustment works", isinstance(adj_shares, int))

    # VaR
    position_values = {"SYM_A": 200000, "SYM_B": 150000}
    var = engine.compute_portfolio_var(mock_data, position_values)
    check("VaR computed", var >= 0)

    # Drawdown
    engine.update_portfolio_value(950000)
    dd = engine.get_current_drawdown()
    check("Drawdown tracked", dd > 0)

    active, dd_val = engine.check_drawdown_circuit_breaker()
    check("Circuit breaker check works", isinstance(active, bool))

except Exception as e:
    check("Correlation Engine", False, str(e))

# =====================================================
# 4. Risk Manager — Weighted Exit Scoring
# =====================================================
print("\n--- 4. Weighted Exit Scoring ---")
try:
    from quant.risk_manager import compute_exit_score, check_exit_triggers

    # Single trigger should NOT exit (score < 0.60)
    should_exit, score, reasons = compute_exit_score(
        rsi_15m=76, supertrend_dir_15m=1, cmf=0.05,
        parabolic_sar=0, current_price=100, pivot_r3=0,
    )
    check("Single RSI trigger doesn't force exit", not should_exit,
          f"score={score}, should_exit={should_exit}")

    # Multiple triggers SHOULD exit
    should_exit, score, reasons = compute_exit_score(
        rsi_15m=82, supertrend_dir_15m=-1, cmf=-0.20,
        parabolic_sar=105, current_price=100,
        divergence_direction="BEARISH",
    )
    check("Multiple triggers → exit", should_exit, f"score={score}")
    check("Exit score has weighted reasons", all("+" in r for r in reasons))

    # Backward compat
    should_exit_bc, reasons_bc = check_exit_triggers(
        rsi_15m=82, supertrend_dir_15m=-1, cmf=-0.20,
        parabolic_sar=105, current_price=100,
    )
    check("Backward-compat check_exit_triggers works", should_exit_bc)

except Exception as e:
    check("Weighted Exit Scoring", False, str(e))

# =====================================================
# 5. Risk Manager — R:R Gate
# =====================================================
print("\n--- 5. R:R Minimum Gate ---")
try:
    from quant.risk_manager import check_rr_gate

    # Good R:R
    passes, rr, reason = check_rr_gate(entry=100, sl=97, pivot_r3=112)
    check("Good R:R passes gate", passes, f"rr={rr}")
    check("R:R ratio correct", rr == 4.0 or rr > 2.0, f"rr={rr}")

    # Bad R:R
    passes, rr, reason = check_rr_gate(entry=100, sl=97, pivot_r3=101)
    check("Bad R:R blocked", not passes, f"rr={rr}")
    check("Reason explains insufficient R:R", "insufficient" in reason.lower())

except Exception as e:
    check("R:R Gate", False, str(e))

# =====================================================
# 6. Regime-Adaptive Risk
# =====================================================
print("\n--- 6. Regime-Adaptive Risk ---")
try:
    from quant.risk_manager import get_regime_risk_pct

    up_risk = get_regime_risk_pct("TRENDING_UP")
    down_risk = get_regime_risk_pct("TRENDING_DOWN")
    check("Uptrend risk is 2.5%", up_risk == 0.025)
    check("Downtrend risk is 1.0%", down_risk == 0.010)
    check("Uptrend risk > downtrend risk", up_risk > down_risk)

except Exception as e:
    check("Regime-Adaptive Risk", False, str(e))

# =====================================================
# 7. Enhanced Entry Quality
# =====================================================
print("\n--- 7. Enhanced Entry Quality ---")
try:
    from quant.risk_manager import compute_entry_quality

    # With negative news
    score_with_bad_news = compute_entry_quality(
        100, rsi_15m=40, squeeze_fire=1, rvol=2.0, cmf=0.1,
        near_support=True, news_sentiment=-0.5,
    )
    score_without_news = compute_entry_quality(
        100, rsi_15m=40, squeeze_fire=1, rvol=2.0, cmf=0.1,
        near_support=True, news_sentiment=0.0,
    )
    check("Negative news reduces quality", score_with_bad_news < score_without_news)

    # Late entry penalty
    score_late = compute_entry_quality(
        100, rsi_15m=40, squeeze_fire=1, rvol=2.0, cmf=0.1,
        pct_from_breakout=7.0,
    )
    score_early = compute_entry_quality(
        100, rsi_15m=40, squeeze_fire=1, rvol=2.0, cmf=0.1,
        pct_from_breakout=0.0,
    )
    check("Late entry reduces quality", score_late < score_early)

    # Earnings warning
    score_earnings = compute_entry_quality(
        100, rsi_15m=40, squeeze_fire=1, rvol=2.0, cmf=0.1,
        earnings_within_5d=True,
    )
    score_no_earnings = compute_entry_quality(
        100, rsi_15m=40, squeeze_fire=1, rvol=2.0, cmf=0.1,
        earnings_within_5d=False,
    )
    check("Earnings proximity reduces quality", score_earnings < score_no_earnings)

    # Score stays in bounds
    score_min = compute_entry_quality(
        100, rsi_15m=80, squeeze_fire=0, rvol=0.5, cmf=-0.5,
        news_sentiment=-0.8, pct_from_breakout=10.0, earnings_within_5d=True,
    )
    check("Entry quality min bound is 0", score_min >= 0)

except Exception as e:
    check("Enhanced Entry Quality", False, str(e))

# =====================================================
# 8. Regime Transition Smoothing
# =====================================================
print("\n--- 8. Regime Transition Smoothing ---")
try:
    from quant.regime_classifier import (
        classify_regime, get_weight_table, is_in_transition,
        get_transition_info, reset_transition_state, get_blended_weight_table,
        WEIGHT_TABLES,
    )

    reset_transition_state()

    # Create mock daily DataFrame with indicators
    dates = pd.date_range("2024-01-01", periods=60, freq="D")
    df_mock = pd.DataFrame({
        "close": [100] * 60,
        "adx": [30] * 60,
        "ema_50": [102] * 60,
        "ema_200": [98] * 60,
        "supertrend_direction": [1] * 60,
        "bb_width": [2.0] * 60,
        "atr": [1.5] * 60,
    }, index=dates)

    # First call should start transition but NOT switch (1/3 candles)
    regime1 = classify_regime(df_mock, "RANGE_BOUND")
    check("First call doesn't switch immediately", regime1 == "RANGE_BOUND")
    check("In transition after first call", is_in_transition())

    # Second call (2/3)
    regime2 = classify_regime(df_mock, "RANGE_BOUND")
    check("Second call still transitioning", regime2 == "RANGE_BOUND")

    # Third call (3/3) — NOW it switches
    regime3 = classify_regime(df_mock, "RANGE_BOUND")
    check("Third call confirms new regime", regime3 == "TRENDING_UP")
    check("No longer in transition", not is_in_transition())

    # Weight table blending
    blended = get_blended_weight_table("RANGE_BOUND", "TRENDING_UP", 0.5)
    check("Blended weight table has all keys",
          len(blended) == len(WEIGHT_TABLES["RANGE_BOUND"]))

    reset_transition_state()

except Exception as e:
    check("Regime Transition Smoothing", False, str(e))

# =====================================================
# 9. Live Monitor Imports
# =====================================================
print("\n--- 9. Live Monitor v3 ---")
try:
    from quant.live_monitor import LiveMonitor, Position

    # Position with scaling
    pos = Position("TEST.NS", 100.0, "2024-01-01", total_shares=30, lots=3)
    check("Position has lots_remaining", pos.lots_remaining == 3)
    check("Position has shares_per_lot", pos.shares_per_lot == 10)

    # R-multiple
    pos.stop_loss = 97.0
    r = pos.r_multiple(103.0)
    check("R-multiple computed", r == 1.0, f"r={r}")

    # Partial exit
    shares = pos.shares_for_partial()
    check("Shares for partial = 10", shares == 10)
    pos.record_partial_exit(10)
    check("After partial: lots_remaining = 2", pos.lots_remaining == 2)
    check("After partial: total_shares = 20", pos.total_shares == 20)

    # LiveMonitor creation
    monitor = LiveMonitor(symbols=["TEST.NS"], account_value=500000)
    check("LiveMonitor v3 created", True)
    check("Has trade_journal", hasattr(monitor, 'trade_journal'))
    check("Has correlation_engine", hasattr(monitor, 'correlation_engine'))
    check("Has _defense_mode", hasattr(monitor, '_defense_mode'))
    check("Has _daily_pnl", hasattr(monitor, '_daily_pnl'))

    # Gap detection
    gap = monitor._detect_gap(4.5)
    check("Gap-up detected", gap == "GAP_UP")
    gap = monitor._detect_gap(-4.0)
    check("Gap-down detected", gap == "GAP_DOWN")
    gap = monitor._detect_gap(1.5)
    check("Normal detected", gap == "NORMAL")

    # Daily loss limit
    monitor._update_daily_pnl(-5.0)
    check("Defense mode activated after 5% loss",
          monitor._defense_mode == True)
    check("Buy suppressed in defense mode",
          monitor._is_buy_suppressed() == True)

except Exception as e:
    check("Live Monitor v3", False, str(e))


# =====================================================
# FINAL REPORT
# =====================================================
print(f"\n{'='*60}")
print(f"  RESULTS: {passed} passed, {failed} failed")
print(f"{'='*60}")

if errors:
    print("\n  FAILURES:")
    for e in errors:
        print(f"    [FAIL] {e}")

with open(os.path.join(SCRIPT_DIR, "verify_results.txt"), "w", encoding="utf-8") as f:
    f.write("".join(_output_lines))

sys.exit(0 if failed == 0 else 1)
