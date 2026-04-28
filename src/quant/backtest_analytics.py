"""
Walk-forward validation and performance analytics for the swing backtester.

Computes professional-grade metrics: CAGR, Sharpe, Sortino, Calmar, profit
factor, expectancy, turnover, time-in-market, monthly returns, drawdown
analysis, and per-setup-type / per-exit-reason breakdowns.

Usage:
    from quant.backtest_analytics import compute_full_analytics, walk_forward

    bt = SwingBacktester(cfg)
    bt.run()
    report = compute_full_analytics(bt)

    wf = walk_forward(cfg, preloaded_data, n_windows=4)
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

import numpy as np
import pandas as pd


# ------------------------------------------------------------------
# Core analytics (works on equity curve + trade log DataFrames)
# ------------------------------------------------------------------

def compute_full_analytics(backtester) -> dict:
    """
    Compute comprehensive performance analytics from a completed backtest.

    Returns a dict with sections:
      - summary: basic stats (return, drawdown, trades)
      - risk_adjusted: Sharpe, Sortino, Calmar
      - trade_quality: profit factor, expectancy, avg R
      - exposure: time in market, turnover
      - drawdown: max drawdown depth + duration
      - monthly_returns: pivot table of monthly returns
      - by_setup: per-setup-type stats
      - by_exit_reason: per-exit-reason stats
    """
    equity = backtester.get_equity_curve()
    trades = backtester.get_trade_log()
    cfg = backtester.cfg

    if equity.empty:
        return {"error": "No equity data — run the backtest first"}

    initial = cfg.initial_capital
    final = float(equity["total_value"].iloc[-1])

    result = {}

    # 1. Summary
    result["summary"] = _summary_stats(equity, initial, final, cfg)

    # 2. Risk-adjusted returns
    result["risk_adjusted"] = _risk_adjusted_metrics(equity, initial, cfg)

    # 3. Trade quality
    result["trade_quality"] = _trade_quality(trades)

    # 4. Exposure
    result["exposure"] = _exposure_metrics(equity, trades, cfg)

    # 5. Drawdown analysis
    result["drawdown"] = _drawdown_analysis(equity)

    # 6. Monthly returns
    result["monthly_returns"] = _monthly_returns(equity)

    # 7. Per-setup-type breakdown
    result["by_setup"] = _by_group(trades, "setup_type")

    # 8. Per-exit-reason breakdown
    result["by_exit_reason"] = _by_group(trades, "reason")

    return result


# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------

def _summary_stats(equity: pd.DataFrame, initial: float, final: float, cfg) -> dict:
    total_return_pct = (final - initial) / initial * 100

    n_days = len(equity)
    years = n_days / 252 if n_days > 0 else 1

    cagr = ((final / initial) ** (1 / years) - 1) * 100 if years > 0 and initial > 0 else 0

    running_max = equity["total_value"].cummax()
    drawdown = (equity["total_value"] - running_max) / running_max
    max_dd_pct = drawdown.min() * 100

    return {
        "initial_capital": initial,
        "final_value": round(final, 2),
        "total_return_pct": round(total_return_pct, 2),
        "cagr_pct": round(cagr, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "trading_days": n_days,
        "years": round(years, 2),
        "rebalance_freq": cfg.rebalance_freq,
        "start_date": cfg.start_date,
        "end_date": cfg.end_date,
    }


# ------------------------------------------------------------------
# Risk-adjusted metrics
# ------------------------------------------------------------------

def _risk_adjusted_metrics(equity: pd.DataFrame, initial: float, cfg) -> dict:
    """Sharpe, Sortino, Calmar ratios."""
    daily_values = equity["total_value"].values.astype(float)
    if len(daily_values) < 2:
        return {"sharpe": 0.0, "sortino": 0.0, "calmar": 0.0}

    daily_returns = np.diff(daily_values) / daily_values[:-1]

    # Annualised
    annual_rf = 0.06  # 6% risk-free (Indian T-Bill proxy)
    daily_rf = annual_rf / 252

    excess = daily_returns - daily_rf
    mean_excess = np.mean(excess)
    std_excess = np.std(excess, ddof=1)

    # Sharpe
    sharpe = (mean_excess / std_excess * np.sqrt(252)) if std_excess > 0 else 0.0

    # Sortino (downside deviation only)
    downside = excess[excess < 0]
    downside_std = np.std(downside, ddof=1) if len(downside) > 1 else 1e-10
    sortino = (mean_excess / downside_std * np.sqrt(252)) if downside_std > 0 else 0.0

    # Calmar (CAGR / max drawdown)
    final = daily_values[-1]
    n_days = len(daily_values)
    years = n_days / 252
    cagr = ((final / initial) ** (1 / years) - 1) if years > 0 and initial > 0 else 0

    running_max = np.maximum.accumulate(daily_values)
    max_dd = np.min((daily_values - running_max) / running_max)
    calmar = abs(cagr / max_dd) if max_dd < 0 else 0.0

    return {
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "calmar": round(calmar, 3),
        "annual_risk_free_rate": annual_rf,
        "annualized_volatility_pct": round(np.std(daily_returns, ddof=1) * np.sqrt(252) * 100, 2),
    }


# ------------------------------------------------------------------
# Trade quality
# ------------------------------------------------------------------

def _trade_quality(trades: pd.DataFrame) -> dict:
    """Profit factor, expectancy, win/loss breakdown."""
    if trades.empty:
        return _empty_trade_quality()

    sells = trades[trades["action"] == "SELL"].copy()
    if sells.empty:
        return _empty_trade_quality()

    n = len(sells)
    pnls = sells["pnl"].values.astype(float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]

    n_wins = len(wins)
    n_losses = len(losses)
    win_rate = n_wins / n * 100 if n > 0 else 0

    gross_profit = float(np.sum(wins)) if n_wins > 0 else 0
    gross_loss = float(np.abs(np.sum(losses))) if n_losses > 0 else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    avg_win = float(np.mean(wins)) if n_wins > 0 else 0
    avg_loss = float(np.mean(losses)) if n_losses > 0 else 0

    # Expectancy: avg_win × win_rate - avg_loss × loss_rate
    expectancy = (avg_win * (n_wins / n) + avg_loss * (n_losses / n)) if n > 0 else 0

    # R-multiples
    r_multiples = sells["r_multiple"].values.astype(float) if "r_multiple" in sells.columns else np.array([])
    avg_r = float(np.mean(r_multiples)) if len(r_multiples) > 0 else 0
    median_r = float(np.median(r_multiples)) if len(r_multiples) > 0 else 0

    # Holding periods
    holding = sells["holding_days"].values.astype(float) if "holding_days" in sells.columns else np.array([])
    avg_hold = float(np.mean(holding)) if len(holding) > 0 else 0
    max_hold = float(np.max(holding)) if len(holding) > 0 else 0

    # Largest win/loss
    largest_win = float(np.max(wins)) if n_wins > 0 else 0
    largest_loss = float(np.min(losses)) if n_losses > 0 else 0

    return {
        "total_trades": n,
        "wins": n_wins,
        "losses": n_losses,
        "win_rate_pct": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2),
        "expectancy": round(expectancy, 2),
        "avg_pnl": round(float(np.mean(pnls)), 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "largest_win": round(largest_win, 2),
        "largest_loss": round(largest_loss, 2),
        "avg_r_multiple": round(avg_r, 2),
        "median_r_multiple": round(median_r, 2),
        "avg_holding_days": round(avg_hold, 1),
        "max_holding_days": round(max_hold, 0),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
    }


def _empty_trade_quality() -> dict:
    return {
        "total_trades": 0, "wins": 0, "losses": 0, "win_rate_pct": 0,
        "profit_factor": 0, "expectancy": 0, "avg_pnl": 0, "avg_win": 0,
        "avg_loss": 0, "largest_win": 0, "largest_loss": 0,
        "avg_r_multiple": 0, "median_r_multiple": 0,
        "avg_holding_days": 0, "max_holding_days": 0,
        "gross_profit": 0, "gross_loss": 0,
    }


# ------------------------------------------------------------------
# Exposure metrics
# ------------------------------------------------------------------

def _exposure_metrics(equity: pd.DataFrame, trades: pd.DataFrame, cfg) -> dict:
    """Time in market, turnover rate."""
    n_days = len(equity)
    if n_days == 0:
        return {"time_in_market_pct": 0, "turnover_rate": 0}

    # Time in market: % of days with at least one position
    days_with_positions = int((equity["open_positions"] > 0).sum())
    time_in_market = days_with_positions / n_days * 100

    # Turnover: number of sells / average positions held
    if not trades.empty:
        n_sells = len(trades[trades["action"] == "SELL"])
        avg_positions = float(equity["open_positions"].mean())
        if avg_positions > 0:
            turnover = n_sells / avg_positions
        else:
            turnover = 0
    else:
        n_sells = 0
        turnover = 0

    return {
        "time_in_market_pct": round(time_in_market, 1),
        "days_with_positions": days_with_positions,
        "total_trading_days": n_days,
        "avg_positions_held": round(float(equity["open_positions"].mean()), 2),
        "total_sells": n_sells,
        "turnover_rate": round(turnover, 2),
    }


# ------------------------------------------------------------------
# Drawdown analysis
# ------------------------------------------------------------------

def _drawdown_analysis(equity: pd.DataFrame) -> dict:
    """Max drawdown depth and duration."""
    values = equity["total_value"].values.astype(float)
    dates = equity["date"].values

    if len(values) < 2:
        return {"max_dd_pct": 0, "max_dd_duration_days": 0, "drawdown_periods": []}

    running_max = np.maximum.accumulate(values)
    drawdown_pct = (values - running_max) / running_max * 100

    max_dd_pct = float(np.min(drawdown_pct))

    # Find drawdown periods (peak-to-trough-to-recovery)
    in_dd = False
    peak_idx = 0
    trough_idx = 0
    dd_periods = []

    for i in range(len(values)):
        if values[i] >= running_max[i]:
            if in_dd:
                # Recovery point
                dd_periods.append({
                    "peak_date": str(dates[peak_idx])[:10],
                    "trough_date": str(dates[trough_idx])[:10],
                    "recovery_date": str(dates[i])[:10],
                    "depth_pct": round(float(drawdown_pct[trough_idx]), 2),
                    "duration_days": int((pd.Timestamp(dates[i]) - pd.Timestamp(dates[peak_idx])).days),
                })
                in_dd = False
            peak_idx = i
        else:
            if not in_dd:
                in_dd = True
            if drawdown_pct[i] < drawdown_pct[trough_idx] or not in_dd:
                trough_idx = i

    # If still in drawdown at end of series
    if in_dd:
        dd_periods.append({
            "peak_date": str(dates[peak_idx])[:10],
            "trough_date": str(dates[trough_idx])[:10],
            "recovery_date": "ongoing",
            "depth_pct": round(float(drawdown_pct[trough_idx]), 2),
            "duration_days": int((pd.Timestamp(dates[-1]) - pd.Timestamp(dates[peak_idx])).days),
        })

    # Longest drawdown
    max_dd_duration = max((p["duration_days"] for p in dd_periods), default=0)

    return {
        "max_dd_pct": round(max_dd_pct, 2),
        "max_dd_duration_days": max_dd_duration,
        "drawdown_periods": sorted(dd_periods, key=lambda x: x["depth_pct"])[:5],
    }


# ------------------------------------------------------------------
# Monthly returns
# ------------------------------------------------------------------

def _monthly_returns(equity: pd.DataFrame) -> dict:
    """Month-by-month return grid for heatmap display."""
    if equity.empty or "date" not in equity.columns:
        return {"table": [], "by_month": {}}

    eq = equity.copy()
    eq["date"] = pd.to_datetime(eq["date"])
    eq = eq.set_index("date")

    # Resample to month-end values
    monthly = eq["total_value"].resample("ME").last().dropna()
    if len(monthly) < 2:
        return {"table": [], "by_month": {}}

    monthly_returns = monthly.pct_change().dropna() * 100

    table = []
    by_month = {}
    for dt, ret in monthly_returns.items():
        year = dt.year
        month = dt.month
        table.append({
            "year": year,
            "month": month,
            "return_pct": round(ret, 2),
        })
        month_name = dt.strftime("%b")
        by_month.setdefault(month_name, []).append(round(ret, 2))

    # Average by month
    month_avg = {m: round(np.mean(vals), 2) for m, vals in by_month.items()}

    return {
        "table": table,
        "month_averages": month_avg,
        "best_month": round(float(monthly_returns.max()), 2) if len(monthly_returns) > 0 else 0,
        "worst_month": round(float(monthly_returns.min()), 2) if len(monthly_returns) > 0 else 0,
        "positive_months": int((monthly_returns > 0).sum()),
        "negative_months": int((monthly_returns <= 0).sum()),
    }


# ------------------------------------------------------------------
# Per-group breakdown (setup type or exit reason)
# ------------------------------------------------------------------

def _by_group(trades: pd.DataFrame, group_col: str) -> dict:
    """Break down trade stats by a categorical column."""
    if trades.empty:
        return {}

    sells = trades[trades["action"] == "SELL"].copy()
    if sells.empty or group_col not in sells.columns:
        return {}

    result = {}
    for group, grp_df in sells.groupby(group_col):
        pnls = grp_df["pnl"].values.astype(float)
        n = len(pnls)
        wins = pnls[pnls > 0]
        result[str(group)] = {
            "count": n,
            "win_rate_pct": round(len(wins) / n * 100, 1) if n > 0 else 0,
            "avg_pnl": round(float(np.mean(pnls)), 2),
            "total_pnl": round(float(np.sum(pnls)), 2),
            "avg_r": round(float(np.mean(grp_df["r_multiple"].values)), 2) if "r_multiple" in grp_df.columns else 0,
            "avg_hold": round(float(np.mean(grp_df["holding_days"].values)), 1) if "holding_days" in grp_df.columns else 0,
        }

    return result


# ------------------------------------------------------------------
# Walk-forward validation
# ------------------------------------------------------------------

def walk_forward(
    config,
    preloaded_data: dict[str, pd.DataFrame],
    n_windows: int = 4,
    in_sample_pct: float = 0.60,
) -> dict:
    """
    Rolling walk-forward validation.

    Splits the date range into overlapping windows, each with an
    in-sample training period and out-of-sample (OOS) test period.

    Returns per-window results + aggregate OOS metrics for detecting
    overfitting (IS >> OOS implies overfitting).

    Args:
        config: SwingBacktestConfig (will be cloned per window)
        preloaded_data: {symbol: DataFrame} — raw OHLCV data
        n_windows: number of rolling windows
        in_sample_pct: fraction of each window used as in-sample
    """
    from quant.swing_backtester import SwingBacktester, SwingBacktestConfig

    start = pd.to_datetime(config.start_date)
    end = pd.to_datetime(config.end_date)
    total_days = (end - start).days

    if total_days < 90 * n_windows:
        return {"error": "Date range too short for walk-forward validation"}

    window_days = total_days // n_windows
    step_days = int(window_days * (1 - in_sample_pct))

    windows = []
    for i in range(n_windows):
        w_start = start + pd.DateOffset(days=i * step_days)
        w_end = w_start + pd.DateOffset(days=window_days)
        if w_end > end:
            w_end = end

        is_end = w_start + pd.DateOffset(days=int(window_days * in_sample_pct))

        windows.append({
            "window": i + 1,
            "is_start": w_start.strftime("%Y-%m-%d"),
            "is_end": is_end.strftime("%Y-%m-%d"),
            "oos_start": is_end.strftime("%Y-%m-%d"),
            "oos_end": w_end.strftime("%Y-%m-%d"),
        })

    results = []
    for w in windows:
        # In-sample
        is_cfg = deepcopy(config)
        is_cfg.start_date = w["is_start"]
        is_cfg.end_date = w["is_end"]

        is_bt = SwingBacktester(is_cfg)
        is_bt.load_data(preloaded=deepcopy(preloaded_data))
        is_bt.run()
        is_report = compute_full_analytics(is_bt)

        # Out-of-sample
        oos_cfg = deepcopy(config)
        oos_cfg.start_date = w["oos_start"]
        oos_cfg.end_date = w["oos_end"]

        oos_bt = SwingBacktester(oos_cfg)
        oos_bt.load_data(preloaded=deepcopy(preloaded_data))
        oos_bt.run()
        oos_report = compute_full_analytics(oos_bt)

        results.append({
            "window": w["window"],
            "dates": w,
            "in_sample": {
                "return_pct": is_report.get("summary", {}).get("total_return_pct", 0),
                "sharpe": is_report.get("risk_adjusted", {}).get("sharpe", 0),
                "max_dd_pct": is_report.get("summary", {}).get("max_drawdown_pct", 0),
                "trades": is_report.get("trade_quality", {}).get("total_trades", 0),
                "win_rate": is_report.get("trade_quality", {}).get("win_rate_pct", 0),
            },
            "out_of_sample": {
                "return_pct": oos_report.get("summary", {}).get("total_return_pct", 0),
                "sharpe": oos_report.get("risk_adjusted", {}).get("sharpe", 0),
                "max_dd_pct": oos_report.get("summary", {}).get("max_drawdown_pct", 0),
                "trades": oos_report.get("trade_quality", {}).get("total_trades", 0),
                "win_rate": oos_report.get("trade_quality", {}).get("win_rate_pct", 0),
            },
        })

    # Aggregate OOS stats
    oos_returns = [r["out_of_sample"]["return_pct"] for r in results]
    oos_sharpes = [r["out_of_sample"]["sharpe"] for r in results]
    is_returns = [r["in_sample"]["return_pct"] for r in results]

    is_avg = float(np.mean(is_returns)) if is_returns else 0
    oos_avg = float(np.mean(oos_returns)) if oos_returns else 0
    decay = ((is_avg - oos_avg) / abs(is_avg) * 100) if is_avg != 0 else 0

    return {
        "windows": results,
        "aggregate": {
            "is_avg_return_pct": round(is_avg, 2),
            "oos_avg_return_pct": round(oos_avg, 2),
            "oos_avg_sharpe": round(float(np.mean(oos_sharpes)), 3) if oos_sharpes else 0,
            "performance_decay_pct": round(decay, 1),
            "is_oos_consistent": abs(decay) < 50,  # heuristic
            "n_windows": n_windows,
        },
    }


# ------------------------------------------------------------------
# Pretty printer
# ------------------------------------------------------------------

def print_analytics(report: dict):
    """Pretty-print the full analytics report to console."""
    if "error" in report:
        print(f"  {report['error']}")
        return

    s = report.get("summary", {})
    ra = report.get("risk_adjusted", {})
    tq = report.get("trade_quality", {})
    ex = report.get("exposure", {})
    dd = report.get("drawdown", {})
    mr = report.get("monthly_returns", {})

    print(f"\n{'='*65}")
    print(f"  SWING BACKTEST — FULL ANALYTICS REPORT")
    print(f"{'='*65}")

    # Summary
    print(f"\n  ── Performance ──")
    print(f"  Period:          {s.get('start_date','')} → {s.get('end_date','')}")
    print(f"  Rebalance:       {s.get('rebalance_freq','')}")
    print(f"  Initial:         Rs.{s.get('initial_capital',0):,.0f}")
    print(f"  Final:           Rs.{s.get('final_value',0):,.0f}")
    pct = s.get('total_return_pct', 0)
    sign = "+" if pct >= 0 else ""
    print(f"  Total Return:    {sign}{pct:.2f}%")
    print(f"  CAGR:            {s.get('cagr_pct',0):.2f}%")
    print(f"  Max Drawdown:    {s.get('max_drawdown_pct',0):.2f}%")

    # Risk-adjusted
    print(f"\n  ── Risk-Adjusted ──")
    print(f"  Sharpe:          {ra.get('sharpe',0):.3f}")
    print(f"  Sortino:         {ra.get('sortino',0):.3f}")
    print(f"  Calmar:          {ra.get('calmar',0):.3f}")
    print(f"  Ann. Volatility: {ra.get('annualized_volatility_pct',0):.2f}%")

    # Trade quality
    print(f"\n  ── Trade Quality ──")
    print(f"  Trades:          {tq.get('total_trades',0)}")
    print(f"  Win Rate:        {tq.get('win_rate_pct',0):.1f}%")
    print(f"  Profit Factor:   {tq.get('profit_factor',0):.2f}")
    print(f"  Expectancy:      Rs.{tq.get('expectancy',0):,.2f}")
    print(f"  Avg PnL/trade:   Rs.{tq.get('avg_pnl',0):,.2f}")
    print(f"  Avg Win:         Rs.{tq.get('avg_win',0):,.2f}")
    print(f"  Avg Loss:        Rs.{tq.get('avg_loss',0):,.2f}")
    print(f"  Largest Win:     Rs.{tq.get('largest_win',0):,.2f}")
    print(f"  Largest Loss:    Rs.{tq.get('largest_loss',0):,.2f}")
    print(f"  Avg R-multiple:  {tq.get('avg_r_multiple',0):.2f}R")
    print(f"  Med R-multiple:  {tq.get('median_r_multiple',0):.2f}R")
    print(f"  Avg Hold:        {tq.get('avg_holding_days',0):.0f} days")

    # Exposure
    print(f"\n  ── Exposure ──")
    print(f"  Time in Market:  {ex.get('time_in_market_pct',0):.1f}%")
    print(f"  Avg Positions:   {ex.get('avg_positions_held',0):.2f}")
    print(f"  Turnover Rate:   {ex.get('turnover_rate',0):.2f}x")

    # Drawdown
    print(f"\n  ── Drawdown ──")
    print(f"  Max Drawdown:    {dd.get('max_dd_pct',0):.2f}%")
    print(f"  Longest DD:      {dd.get('max_dd_duration_days',0)} days")
    top_dd = dd.get('drawdown_periods', [])
    if top_dd:
        print(f"  Top drawdowns:")
        for d in top_dd[:3]:
            rec = d.get('recovery_date', 'ongoing')
            print(f"    {d['depth_pct']:+.2f}%  {d['peak_date']} → {d['trough_date']} (recovery: {rec})")

    # Monthly
    print(f"\n  ── Monthly Returns ──")
    print(f"  Best Month:      {mr.get('best_month',0):+.2f}%")
    print(f"  Worst Month:     {mr.get('worst_month',0):+.2f}%")
    print(f"  +ve Months:      {mr.get('positive_months',0)}")
    print(f"  -ve Months:      {mr.get('negative_months',0)}")

    # By setup
    by_setup = report.get("by_setup", {})
    if by_setup:
        print(f"\n  ── By Setup Type ──")
        print(f"  {'Setup':<18} {'Count':>5} {'Win%':>7} {'Avg PnL':>10} {'Avg R':>7}")
        for setup, stats in sorted(by_setup.items(), key=lambda x: -x[1]["total_pnl"]):
            print(f"  {setup:<18} {stats['count']:>5} {stats['win_rate_pct']:>6.1f}% "
                  f"Rs.{stats['avg_pnl']:>8,.0f} {stats['avg_r']:>6.2f}R")

    # By exit reason
    by_exit = report.get("by_exit_reason", {})
    if by_exit:
        print(f"\n  ── By Exit Reason ──")
        print(f"  {'Reason':<25} {'Count':>5} {'Win%':>7} {'Avg PnL':>10}")
        for reason, stats in sorted(by_exit.items(), key=lambda x: -x[1]["count"]):
            print(f"  {reason:<25} {stats['count']:>5} {stats['win_rate_pct']:>6.1f}% "
                  f"Rs.{stats['avg_pnl']:>8,.0f}")

    print(f"\n{'='*65}\n")


def print_walk_forward(wf: dict):
    """Pretty-print walk-forward validation results."""
    if "error" in wf:
        print(f"  {wf['error']}")
        return

    agg = wf.get("aggregate", {})
    windows = wf.get("windows", [])

    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD VALIDATION ({agg.get('n_windows',0)} windows)")
    print(f"{'='*70}")

    print(f"\n  {'Window':<8} {'IS Return':>10} {'OOS Return':>11} {'OOS Sharpe':>11} {'OOS DD':>8} {'Trades':>7}")
    for w in windows:
        i = w["in_sample"]
        o = w["out_of_sample"]
        print(f"  {w['window']:<8} {i['return_pct']:>+9.2f}% {o['return_pct']:>+10.2f}% "
              f"{o['sharpe']:>10.3f} {o['max_dd_pct']:>7.2f}% {o['trades']:>6}")

    print(f"\n  ── Aggregate ──")
    print(f"  IS Avg Return:   {agg.get('is_avg_return_pct',0):+.2f}%")
    print(f"  OOS Avg Return:  {agg.get('oos_avg_return_pct',0):+.2f}%")
    print(f"  OOS Avg Sharpe:  {agg.get('oos_avg_sharpe',0):.3f}")
    print(f"  Perf. Decay:     {agg.get('performance_decay_pct',0):.1f}%")
    consistent = "✅ YES" if agg.get("is_oos_consistent") else "⚠️  NO (possible overfitting)"
    print(f"  IS/OOS Consistent: {consistent}")
    print(f"{'='*70}\n")
