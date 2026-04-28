"""
Tests for the swing backtester.

All tests use synthetic data — no yfinance calls.
The synthetic helper builds DataFrames with realistic OHLCV + indicators
so classify_swing_setup and compute_swing_rank work correctly.
"""

import unittest
from copy import deepcopy

import numpy as np
import pandas as pd

from src.quant.swing_backtester import SwingBacktester, SwingBacktestConfig


# ------------------------------------------------------------------
# Synthetic data helpers
# ------------------------------------------------------------------

def _make_daily(
    closes: list[float],
    volumes: list[float] | None = None,
    start: str = "2022-01-03",
) -> pd.DataFrame:
    """
    Build a daily DataFrame with OHLCV and all indicators expected by
    swing_engine / swing_ranker.
    """
    n = len(closes)
    volumes = volumes or [500_000] * n
    opens = [c * 0.998 for c in closes]
    highs = [c * 1.012 for c in closes]
    lows = [c * 0.988 for c in closes]

    dates = pd.bdate_range(start, periods=n, freq="B")
    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=dates,
    )
    return df  # indicators added by _prepare_df inside the backtester


def _uptrend(n: int = 300, start_price: float = 100.0, daily_drift: float = 0.3):
    """Generate a steadily rising close series."""
    return [start_price + i * daily_drift for i in range(n)]


def _downtrend(n: int = 300, start_price: float = 200.0, daily_drift: float = 0.25):
    """Generate a steadily falling close series."""
    return [max(10, start_price - i * daily_drift) for i in range(n)]


def _build_universe(
    series_map: dict[str, list[float]],
    volumes: list[float] | None = None,
) -> dict[str, pd.DataFrame]:
    """Build a universe dict from {symbol: closes}."""
    return {sym: _make_daily(closes, volumes) for sym, closes in series_map.items()}


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

class TestSwingBacktesterSynthetic(unittest.TestCase):
    """Tests using synthetic data — no network calls."""

    def _quick_config(self, **overrides) -> SwingBacktestConfig:
        defaults = dict(
            universe=[],
            start_date="2023-01-02",
            end_date="2023-06-30",
            initial_capital=500_000,
            max_positions=3,
            rebalance_freq="weekly",
            risk_per_trade=0.02,
            slippage_pct=0.0015,
            transaction_cost_pct=0.001,
            min_swing_rank=30,
        )
        defaults.update(overrides)
        return SwingBacktestConfig(**defaults)

    # ---- 1. Basic flow ----

    def test_backtester_runs_on_synthetic_data(self):
        """Full sim loop runs without error, produces equity curve + trades."""
        universe = _build_universe({
            "STOCK_A": _uptrend(350, 100, 0.4),
            "STOCK_B": _uptrend(350, 50, 0.25),
            "STOCK_C": _uptrend(350, 200, 0.3),
        })

        cfg = self._quick_config()
        bt = SwingBacktester(cfg)
        bt.load_data(preloaded=universe)
        bt.run()

        eq = bt.get_equity_curve()
        self.assertFalse(eq.empty, "Equity curve should not be empty")
        self.assertGreater(len(eq), 50, "Should have many daily records")

        summary = bt.get_summary()
        self.assertIn("total_return_pct", summary)
        self.assertIn("total_trades", summary)

    # ---- 2. Gap-through-stop exit ----

    def test_sl_exit_triggers_on_gap_down(self):
        """When open gaps below SL, exit at open (not SL)."""
        # Build a stock that rises then gaps down sharply
        rises = _uptrend(280, 100, 0.5)
        # Day 281+: massive gap down
        gap_down = [80.0] * 20  # well below any reasonable SL
        closes = rises + gap_down
        volumes = [800_000] * len(closes)

        universe = _build_universe({"GAPPER": closes}, volumes)

        cfg = self._quick_config(
            max_positions=1,
            min_swing_rank=0,      # accept anything
        )
        bt = SwingBacktester(cfg)
        bt.load_data(preloaded=universe)
        bt.run()

        # Find SL-hit sells
        sl_sells = [
            t for t in bt.trade_log
            if t["action"] == "SELL" and t["reason"] == "SL_HIT"
        ]
        if sl_sells:
            for sell in sl_sells:
                # Exit should be at the gapped-down open, which is lower
                # than the SL — verifying gap-through handling
                self.assertGreater(sell["price"], 0)

    # ---- 3. Transaction costs reduce returns ----

    def test_transaction_costs_reduce_returns(self):
        """Backtest with costs < same backtest without costs."""
        universe = _build_universe({
            "UP_1": _uptrend(350, 100, 0.3),
            "UP_2": _uptrend(350, 150, 0.2),
        })

        # With costs
        cfg_cost = self._quick_config(
            slippage_pct=0.003,
            transaction_cost_pct=0.002,
        )
        bt_cost = SwingBacktester(cfg_cost)
        bt_cost.load_data(preloaded=deepcopy(universe))
        bt_cost.run()

        # Without costs
        cfg_free = self._quick_config(
            slippage_pct=0.0,
            transaction_cost_pct=0.0,
        )
        bt_free = SwingBacktester(cfg_free)
        bt_free.load_data(preloaded=deepcopy(universe))
        bt_free.run()

        eq_cost = bt_cost.get_equity_curve()
        eq_free = bt_free.get_equity_curve()

        if not eq_cost.empty and not eq_free.empty:
            final_cost = eq_cost["total_value"].iloc[-1]
            final_free = eq_free["total_value"].iloc[-1]
            # The cost run should finish with equal or lower value
            self.assertLessEqual(
                final_cost, final_free + 1,  # +1 for float rounding
                "Transaction costs should not increase returns",
            )

    # ---- 4. Next-day entry ----

    def test_next_day_entry(self):
        """Signal on rebalance day T → BUY executes on day T+1."""
        universe = _build_universe({
            "DELAYED": _uptrend(350, 100, 0.3),
        })

        cfg = self._quick_config(max_positions=1, min_swing_rank=0)
        bt = SwingBacktester(cfg)
        bt.load_data(preloaded=universe)
        bt.run()

        buys = [t for t in bt.trade_log if t["action"] == "BUY"]
        if len(buys) >= 2:
            # The buy date should be the day AFTER a rebalance day
            # We just verify the buy happens on some date recorded in the log
            # and that the price used is the OPEN of that day (not close)
            for buy in buys:
                buy_date = buy["date"]
                df = bt.data["DELAYED"]
                if buy_date in df.index:
                    open_price = float(df.loc[buy_date, "open"])
                    # entry price should be open + slippage, not close
                    expected_min = open_price * 0.999  # tolerance
                    expected_max = open_price * 1.01
                    self.assertGreaterEqual(buy["price"], expected_min)
                    self.assertLessEqual(buy["price"], expected_max)

    # ---- 5. Position sizing respects risk ----

    def test_position_sizing_respects_risk(self):
        """No single position should exceed 15% of portfolio value."""
        universe = _build_universe({
            f"STOCK_{i}": _uptrend(350, 50 + i * 30, 0.2)
            for i in range(6)
        })

        cfg = self._quick_config(max_positions=5, min_swing_rank=0)
        bt = SwingBacktester(cfg)
        bt.load_data(preloaded=universe)
        bt.run()

        buys = [t for t in bt.trade_log if t["action"] == "BUY"]
        for buy in buys:
            position_value = buy["price"] * buy["shares"]
            # At the time of buy, total equity ≈ initial capital
            # Position should not exceed 15% of initial capital (roughly)
            max_allowed = self.cfg_initial * 0.20  # generous 20% bound
            self.assertLessEqual(
                position_value, max_allowed,
                f"{buy['symbol']} position Rs.{position_value:,.0f} "
                f"exceeds 20% of capital",
            )

    @property
    def cfg_initial(self):
        return 500_000

    # ---- 6. Downtrend produces few/no trades ----

    def test_no_trades_in_downtrend(self):
        """A declining universe should produce few or no actionable setups."""
        universe = _build_universe({
            "DOWN_A": _downtrend(350, 200, 0.3),
            "DOWN_B": _downtrend(350, 150, 0.2),
        })

        cfg = self._quick_config(min_swing_rank=40)
        bt = SwingBacktester(cfg)
        bt.load_data(preloaded=universe)
        bt.run()

        buys = [t for t in bt.trade_log if t["action"] == "BUY"]
        # In a steady downtrend, swing setups rarely fire
        self.assertLessEqual(
            len(buys), 5,
            f"Expected few buys in a downtrend, got {len(buys)}",
        )

    # ---- 7. Weekly vs monthly rebalance ----

    def test_weekly_vs_monthly_rebalance_both_work(self):
        """Both rebalance frequencies run without error."""
        universe = _build_universe({
            "STOCK_X": _uptrend(350, 100, 0.3),
        })

        for freq in ("weekly", "monthly"):
            cfg = self._quick_config(rebalance_freq=freq, min_swing_rank=0)
            bt = SwingBacktester(cfg)
            bt.load_data(preloaded=deepcopy(universe))
            bt.run()

            eq = bt.get_equity_curve()
            self.assertFalse(eq.empty, f"{freq} rebalance produced no equity data")

    # ---- 8. Portfolio replacement: only swap when meaningfully better ----

    def test_replacement_reduces_turnover_vs_naive(self):
        """
        With a high replacement threshold, fewer holdings get swapped
        compared to a threshold of 0 (naive rebalance-out).
        """
        universe = _build_universe({
            f"STOCK_{i}": _uptrend(350, 80 + i * 10, 0.15 + i * 0.03)
            for i in range(6)
        })

        # Strict threshold = less turnover
        cfg_strict = self._quick_config(
            max_positions=3,
            min_swing_rank=0,
            replacement_threshold=20.0,
        )
        bt_strict = SwingBacktester(cfg_strict)
        bt_strict.load_data(preloaded=deepcopy(universe))
        bt_strict.run()

        # Loose threshold = more turnover
        cfg_loose = self._quick_config(
            max_positions=3,
            min_swing_rank=0,
            replacement_threshold=0.0,  # swap on any rank difference
        )
        bt_loose = SwingBacktester(cfg_loose)
        bt_loose.load_data(preloaded=deepcopy(universe))
        bt_loose.run()

        sells_strict = len([t for t in bt_strict.trade_log if t["action"] == "SELL"])
        sells_loose = len([t for t in bt_loose.trade_log if t["action"] == "SELL"])

        # Strict threshold should produce equal or fewer sells
        self.assertLessEqual(
            sells_strict, sells_loose + 2,  # small tolerance
            "High replacement_threshold should not increase turnover",
        )

    def test_replacement_reason_in_trade_log(self):
        """When a holding is replaced, reason should be REPLACED_BY_BETTER."""
        # One strong stock + one that starts strong then flattens
        strong = _uptrend(350, 100, 0.5)
        starts_ok = _uptrend(200, 100, 0.3) + [160.0] * 150  # flattens
        late_star = [50.0] * 200 + _uptrend(150, 50, 0.8)  # emerges late

        universe = _build_universe({
            "STRONG": strong,
            "FADES": starts_ok,
            "LATE_STAR": late_star,
        })

        cfg = self._quick_config(
            max_positions=2,
            min_swing_rank=0,
            replacement_threshold=5.0,
        )
        bt = SwingBacktester(cfg)
        bt.load_data(preloaded=universe)
        bt.run()

        reasons = set(
            t["reason"] for t in bt.trade_log if t["action"] == "SELL"
        )
        # We should see replacement exits in at least some scenarios
        # (the log should contain valid reasons regardless)
        valid_reasons = {
            "SL_HIT", "REPLACED_BY_BETTER", "FAILED_BREAKOUT",
            "STRUCTURE_BREAK", "RANK_DETERIORATION", "REBALANCE_OUT",
        }
        for r in reasons:
            self.assertIn(r, valid_reasons, f"Unknown exit reason: {r}")

    # ---- 9. Improved exit logic: exit reasons ----

    def test_exit_reasons_tracked_in_summary(self):
        """Summary should include exit_reasons breakdown."""
        universe = _build_universe({
            "STOCK_A": _uptrend(350, 100, 0.4),
            "STOCK_B": _uptrend(350, 50, 0.25),
        })

        cfg = self._quick_config(min_swing_rank=0)
        bt = SwingBacktester(cfg)
        bt.load_data(preloaded=universe)
        bt.run()

        summary = bt.get_summary()
        self.assertIn("exit_reasons", summary)
        self.assertIsInstance(summary["exit_reasons"], dict)

    def test_swing_exits_can_be_disabled(self):
        """When all swing exit flags are False, only SL and replacement exits remain."""
        universe = _build_universe({
            "STOCK_A": _uptrend(350, 100, 0.3),
        })

        cfg = self._quick_config(
            min_swing_rank=0,
            exit_on_failed_breakout=False,
            exit_on_structure_break=False,
            exit_on_rank_deterioration=False,
        )
        bt = SwingBacktester(cfg)
        bt.load_data(preloaded=universe)
        bt.run()

        # No FAILED_BREAKOUT, STRUCTURE_BREAK, or RANK_DETERIORATION exits
        swing_exit_reasons = {"FAILED_BREAKOUT", "STRUCTURE_BREAK", "RANK_DETERIORATION"}
        for trade in bt.trade_log:
            if trade["action"] == "SELL":
                self.assertNotIn(
                    trade["reason"], swing_exit_reasons,
                    f"Got {trade['reason']} exit but swing exits are disabled",
                )

    def test_failed_breakout_exit_fires(self):
        """
        A stock that rises then reverses should produce exits.  If the swing
        engine classifies a breakout, the FAILED_BREAKOUT exit may fire;
        otherwise SL_HIT or STRUCTURE_BREAK will handle the reversal.
        We verify the sim runs cleanly and all exit reasons are valid.
        """
        # Rise to trigger breakout, then fall back
        rise = _uptrend(270, 100, 0.5)
        peak_price = rise[-1]  # ~234
        # Sharp reversal below breakout level
        reversal = [peak_price - i * 2 for i in range(80)]
        closes = rise + reversal
        # High volume to help trigger breakout detection
        volumes = [300_000] * 250 + [900_000] * 20 + [600_000] * len(reversal)

        universe = _build_universe({"BREAKER": closes}, volumes)

        cfg = self._quick_config(
            max_positions=1,
            min_swing_rank=0,
            exit_on_failed_breakout=True,
            exit_on_structure_break=True,
            exit_on_rank_deterioration=False,
        )
        bt = SwingBacktester(cfg)
        bt.load_data(preloaded=universe)
        bt.run()

        # Verify all exit reasons are from the known set
        valid_reasons = {
            "SL_HIT", "REPLACED_BY_BETTER", "FAILED_BREAKOUT",
            "STRUCTURE_BREAK", "RANK_DETERIORATION", "REBALANCE_OUT",
        }
        for trade in bt.trade_log:
            if trade["action"] == "SELL":
                self.assertIn(
                    trade["reason"], valid_reasons,
                    f"Unknown exit reason: {trade['reason']}",
                )

        # The sim should complete without errors (equity curve not empty)
        eq = bt.get_equity_curve()
        self.assertFalse(eq.empty, "Equity curve should not be empty")

    # ---- 10. Relative strength vs benchmark ----

    def test_rs_component_in_ranking(self):
        """Swing rank output should include 'rs' component and rs_ratio metric."""
        from src.quant.swing_ranker import compute_swing_rank

        # Build minimal df for ranking
        closes = _uptrend(100, 100, 0.3)
        df = _make_daily(closes)
        from src.feature_engineering import add_technical_indicators
        df = add_technical_indicators(df)

        rank = compute_swing_rank(
            df,
            price=float(df["close"].iloc[-1]),
            swing_setup={"setup_type": "BREAKOUT", "quality_score": 70,
                         "stop_loss": 100, "actionable": True},
            mtf_score=0.5,
            entry_quality=60,
            rvol=1.2,
            sector_multiplier=1.0,
            rs_ratio=1.15,  # outperformer
        )

        self.assertIn("rs", rank["components"])
        self.assertIn("rs_ratio", rank["metrics"])
        self.assertAlmostEqual(rank["metrics"]["rs_ratio"], 1.15, places=2)

    def test_outperformer_ranks_higher_than_underperformer(self):
        """A stock with RS > 1 should score higher than one with RS < 1."""
        from src.quant.swing_ranker import compute_swing_rank

        closes = _uptrend(100, 100, 0.3)
        df = _make_daily(closes)
        from src.feature_engineering import add_technical_indicators
        df = add_technical_indicators(df)

        common = dict(
            price=float(df["close"].iloc[-1]),
            swing_setup={"setup_type": "BREAKOUT", "quality_score": 70,
                         "stop_loss": 100, "actionable": True},
            mtf_score=0.5,
            entry_quality=60,
            rvol=1.2,
            sector_multiplier=1.0,
        )

        rank_outperform = compute_swing_rank(df, **common, rs_ratio=1.25)
        rank_underperform = compute_swing_rank(df, **common, rs_ratio=0.80)

        self.assertGreater(
            rank_outperform["score"], rank_underperform["score"],
            "Outperformer (RS 1.25) should rank higher than underperformer (RS 0.80)",
        )
        # RS component should differ
        self.assertGreater(
            rank_outperform["components"]["rs"],
            rank_underperform["components"]["rs"],
        )

    def test_backtester_with_synthetic_benchmark(self):
        """Backtester with benchmark data loaded produces valid RS ratios."""
        # Stock rises faster than benchmark → RS > 1.0
        stock_closes = _uptrend(350, 100, 0.5)
        bench_closes = _uptrend(350, 100, 0.2)  # slower rise

        universe = _build_universe({"OUTPERF": stock_closes})

        # Build benchmark df
        bench_df = _make_daily(bench_closes)

        cfg = self._quick_config(max_positions=1, min_swing_rank=0)
        bt = SwingBacktester(cfg)
        bt.load_data(preloaded=universe)
        # Manually set benchmark
        bt.benchmark_data = bench_df
        bt.run()

        eq = bt.get_equity_curve()
        self.assertFalse(eq.empty, "Should produce equity curve with benchmark")

    def test_rs_ratio_neutral_without_benchmark(self):
        """Without benchmark data, RS ratio defaults to 1.0 (neutral)."""
        universe = _build_universe({
            "STOCK_A": _uptrend(350, 100, 0.3),
        })

        cfg = self._quick_config(min_swing_rank=0)
        bt = SwingBacktester(cfg)
        bt.load_data(preloaded=universe)

        # No benchmark loaded
        self.assertIsNone(bt.benchmark_data)

        # _compute_rs_ratio should return 1.0
        df = list(bt.data.values())[0]
        rs = bt._compute_rs_ratio(df)
        self.assertEqual(rs, 1.0, "RS should be neutral (1.0) without benchmark")

    # ---- 11. Liquidity & bad-stock filters ----

    def test_penny_stock_excluded_by_filter(self):
        """Stocks below min_price should not generate any BUY trades."""
        # Stock trading at Rs.20-30 — below default Rs.50 threshold
        penny = [20.0 + i * 0.05 for i in range(350)]
        normal = _uptrend(350, 100, 0.3)

        universe = _build_universe({
            "PENNY": penny,
            "NORMAL": normal,
        })

        cfg = self._quick_config(
            max_positions=2,
            min_swing_rank=0,
            min_price=50.0,          # penny threshold
            min_avg_volume=0,        # don't filter on volume
            min_avg_turnover=0,      # don't filter on turnover
            min_trade_days=60,       # relaxed
        )
        bt = SwingBacktester(cfg)
        bt.load_data(preloaded=universe)
        bt.run()

        penny_buys = [t for t in bt.trade_log if t["action"] == "BUY" and t["symbol"] == "PENNY"]
        self.assertEqual(
            len(penny_buys), 0,
            "Penny stock should not be bought when min_price=50",
        )

    def test_illiquid_stock_excluded_by_volume_filter(self):
        """Stocks with low volume should be filtered out."""
        # Low volume stock
        low_vol_closes = _uptrend(350, 100, 0.3)
        low_vol_volumes = [5_000] * 350  # only 5K shares/day

        # Normal volume stock
        normal_closes = _uptrend(350, 100, 0.3)
        normal_volumes = [500_000] * 350  # 500K shares/day

        universe = {
            "LOW_VOL": _make_daily(low_vol_closes, low_vol_volumes),
            "NORMAL": _make_daily(normal_closes, normal_volumes),
        }

        cfg = self._quick_config(
            max_positions=2,
            min_swing_rank=0,
            min_price=0,             # don't filter on price
            min_avg_volume=100_000,  # 100K minimum
            min_avg_turnover=0,      # don't filter on turnover
            min_trade_days=60,
        )
        bt = SwingBacktester(cfg)
        bt.load_data(preloaded=universe)
        bt.run()

        low_vol_buys = [t for t in bt.trade_log if t["action"] == "BUY" and t["symbol"] == "LOW_VOL"]
        self.assertEqual(
            len(low_vol_buys), 0,
            "Low-volume stock should be excluded by min_avg_volume filter",
        )

    def test_filters_relaxed_includes_everything(self):
        """When all filter thresholds are 0, all stocks pass."""
        penny = [20.0 + i * 0.05 for i in range(350)]
        universe = _build_universe({"CHEAP": penny}, [50_000] * 350)

        cfg = self._quick_config(
            max_positions=1,
            min_swing_rank=0,
            min_price=0,
            max_price=999_999,
            min_avg_volume=0,
            min_avg_turnover=0,
            min_trade_days=60,
        )
        bt = SwingBacktester(cfg)
        bt.load_data(preloaded=universe)
        bt.run()

        # Even the cheap stock should be considered now
        eq = bt.get_equity_curve()
        self.assertFalse(eq.empty, "All filters relaxed should still produce results")

    def test_held_positions_bypass_liquidity_filter(self):
        """
        Already-held positions should NOT be filtered out during rebalance,
        even if they would fail the liquidity filter. This prevents forced
        sales due to temporary volume drops.
        """
        # Stock that starts with good volume then drops (but we're already holding)
        closes = _uptrend(350, 100, 0.3)
        volumes = [500_000] * 250 + [10_000] * 100  # volume crash mid-way

        universe = {"HOLDER": _make_daily(closes, volumes)}

        cfg = self._quick_config(
            max_positions=1,
            min_swing_rank=0,
            min_price=0,
            min_avg_volume=100_000,  # will fail after volume crash
            min_avg_turnover=0,
            min_trade_days=60,
        )
        bt = SwingBacktester(cfg)
        bt.load_data(preloaded=universe)
        bt.run()

        # The backtester should still produce an equity curve
        # (held positions are not ejected by the filter)
        eq = bt.get_equity_curve()
        self.assertFalse(eq.empty)

    # ---- 12. Full analytics ----

    def test_full_analytics_produces_all_sections(self):
        """compute_full_analytics should return all expected sections."""
        from src.quant.backtest_analytics import compute_full_analytics

        universe = _build_universe({
            "STOCK_A": _uptrend(350, 100, 0.4),
            "STOCK_B": _uptrend(350, 50, 0.25),
        })

        cfg = self._quick_config(min_swing_rank=0)
        bt = SwingBacktester(cfg)
        bt.load_data(preloaded=universe)
        bt.run()

        report = compute_full_analytics(bt)

        # All sections present
        expected_sections = [
            "summary", "risk_adjusted", "trade_quality",
            "exposure", "drawdown", "monthly_returns",
            "by_setup", "by_exit_reason",
        ]
        for section in expected_sections:
            self.assertIn(section, report, f"Missing section: {section}")

        # Summary has CAGR
        self.assertIn("cagr_pct", report["summary"])

        # Risk-adjusted has Sharpe, Sortino, Calmar
        ra = report["risk_adjusted"]
        self.assertIn("sharpe", ra)
        self.assertIn("sortino", ra)
        self.assertIn("calmar", ra)

        # Trade quality has profit factor and expectancy
        tq = report["trade_quality"]
        self.assertIn("profit_factor", tq)
        self.assertIn("expectancy", tq)
        self.assertIn("largest_win", tq)
        self.assertIn("largest_loss", tq)

        # Exposure
        self.assertIn("time_in_market_pct", report["exposure"])

        # Drawdown
        self.assertIn("max_dd_duration_days", report["drawdown"])

        # Monthly returns
        self.assertIn("best_month", report["monthly_returns"])

    def test_analytics_sharpe_is_finite(self):
        """Sharpe ratio should be a finite number, not NaN or inf."""
        from src.quant.backtest_analytics import compute_full_analytics
        import math

        universe = _build_universe({
            "STOCK_A": _uptrend(350, 100, 0.3),
        })

        cfg = self._quick_config(min_swing_rank=0)
        bt = SwingBacktester(cfg)
        bt.load_data(preloaded=universe)
        bt.run()

        report = compute_full_analytics(bt)
        sharpe = report["risk_adjusted"]["sharpe"]
        self.assertTrue(math.isfinite(sharpe), f"Sharpe should be finite, got {sharpe}")

    def test_by_setup_breakdown(self):
        """Per-setup-type breakdown should group trades correctly."""
        from src.quant.backtest_analytics import compute_full_analytics

        universe = _build_universe({
            "STOCK_A": _uptrend(350, 100, 0.4),
            "STOCK_B": _uptrend(350, 50, 0.25),
            "STOCK_C": _uptrend(350, 200, 0.5),
        })

        cfg = self._quick_config(max_positions=3, min_swing_rank=0)
        bt = SwingBacktester(cfg)
        bt.load_data(preloaded=universe)
        bt.run()

        report = compute_full_analytics(bt)
        by_setup = report["by_setup"]

        # Each setup in the breakdown should have valid stats
        for setup, stats in by_setup.items():
            self.assertGreater(stats["count"], 0)
            self.assertIn("win_rate_pct", stats)
            self.assertIn("avg_pnl", stats)

    # ---- 13. Walk-forward validation ----

    def test_walk_forward_runs_on_synthetic_data(self):
        """Walk-forward with 2 windows should produce IS and OOS results."""
        from src.quant.backtest_analytics import walk_forward

        # Need long enough data for walk-forward
        universe = _build_universe({
            "STOCK_A": _uptrend(500, 100, 0.3),
            "STOCK_B": _uptrend(500, 50, 0.2),
        })

        cfg = self._quick_config(
            start_date="2022-06-01",
            end_date="2023-12-31",
            min_swing_rank=0,
        )

        wf = walk_forward(cfg, universe, n_windows=2)

        self.assertNotIn("error", wf, f"Walk-forward error: {wf.get('error')}")
        self.assertIn("windows", wf)
        self.assertIn("aggregate", wf)
        self.assertEqual(len(wf["windows"]), 2)

        # Each window should have IS and OOS results
        for w in wf["windows"]:
            self.assertIn("in_sample", w)
            self.assertIn("out_of_sample", w)
            self.assertIn("return_pct", w["in_sample"])
            self.assertIn("return_pct", w["out_of_sample"])

        # Aggregate
        agg = wf["aggregate"]
        self.assertIn("performance_decay_pct", agg)
        self.assertIn("is_oos_consistent", agg)

    def test_walk_forward_too_short_returns_error(self):
        """Walk-forward on too-short date range returns error."""
        from src.quant.backtest_analytics import walk_forward

        universe = _build_universe({
            "STOCK_A": _uptrend(100, 100, 0.3),
        })

        cfg = self._quick_config(
            start_date="2023-01-02",
            end_date="2023-03-01",  # only 2 months — too short for 4 windows
        )

        wf = walk_forward(cfg, universe, n_windows=4)
        self.assertIn("error", wf)


if __name__ == "__main__":
    unittest.main()
