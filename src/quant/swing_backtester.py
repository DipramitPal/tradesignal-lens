"""
Swing/position trading backtester.

Uses the exact live swing setup classification, swing ranking, and
structure-aware stop-loss logic to simulate a daily equity curve over
historical data.

Realistic assumptions:
  - Next-day entry (signal on day T, buy at T+1 open + slippage)
  - Transaction costs (brokerage + STT + GST + stamp duty)
  - Slippage on entry
  - Gap-through-stop handling on exits
  - Risk-based position sizing via compute_position_size
  - Cash tracking, open positions, detailed trade log

Portfolio management:
  - Smart replacement: only swap a holding when the new candidate's rank
    exceeds the holding's current rank by a configurable threshold
  - Improved swing exits: failed breakout, close below structure level,
    rank deterioration below minimum
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from feature_engineering import add_technical_indicators
from quant.swing_engine import classify_swing_setup, SwingSetup
from quant.swing_ranker import compute_swing_rank
from quant.risk_manager import compute_position_size


# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------

@dataclass
class SwingBacktestConfig:
    """All tuneable parameters for the swing backtest."""

    universe: list[str] = field(default_factory=list)
    start_date: str = "2023-01-01"
    end_date: str = "2024-12-31"
    initial_capital: float = 500_000.0
    max_positions: int = 5
    rebalance_freq: str = "weekly"       # "weekly" or "monthly"
    risk_per_trade: float = 0.02         # 2% risk per trade
    slippage_pct: float = 0.0015         # 0.15% adverse slippage on entry
    transaction_cost_pct: float = 0.001  # 0.10% round-trip per side
    min_swing_rank: float = 40.0         # minimum rank score to consider
    warmup_days: int = 252               # ~1 year look-back for indicators

    # Portfolio replacement: only swap when new rank exceeds old by this much
    replacement_threshold: float = 10.0

    # Swing exit triggers (checked daily, not just on rebalance)
    exit_on_failed_breakout: bool = True    # price falls back below breakout level
    exit_on_structure_break: bool = True    # close below structure support level
    exit_on_rank_deterioration: bool = True # rank drops below min_swing_rank

    # Relative strength benchmark
    benchmark_symbol: str = "^NSEI"        # NIFTY 50; use "" to disable RS

    # Liquidity & bad-stock filters (applied before ranking)
    min_price: float = 50.0               # exclude penny stocks below Rs.50
    max_price: float = 50_000.0           # exclude ultra-expensive stocks
    min_avg_volume: int = 100_000         # minimum 20-day avg volume (shares)
    min_avg_turnover: float = 1_00_00_000 # minimum 20-day avg turnover (Rs.1 Cr)
    min_trade_days: int = 200             # minimum bars of history required


# ------------------------------------------------------------------
# Position tracking
# ------------------------------------------------------------------

@dataclass
class _Position:
    symbol: str
    shares: int
    entry_price: float
    stop_loss: float
    entry_date: object  # pd.Timestamp
    setup_type: str
    swing_rank: float
    current_rank: float = 0.0       # updated on each rebalance
    structure_level: float = 0.0    # key support from setup classification


# ------------------------------------------------------------------
# Backtester
# ------------------------------------------------------------------

class SwingBacktester:
    """
    Daily swing/position backtest engine.

    Workflow per trading day:
      1. Check SL exits (gap-through-stop aware)
      2. Mark-to-market equity curve
      3. On rebalance days: rank universe → sell weak, buy strong
         (entries execute next trading day)
    """

    def __init__(self, config: SwingBacktestConfig):
        self.cfg = config
        self.data: dict[str, pd.DataFrame] = {}

        # Portfolio state
        self.cash: float = config.initial_capital
        self.positions: dict[str, _Position] = {}
        self._pending_buys: list[dict] = []   # filled next trading day

        # Benchmark data for RS computation
        self.benchmark_data: pd.DataFrame | None = None

        # Output
        self.portfolio_history: list[dict] = []
        self.trade_log: list[dict] = []

    # ----------------------------------------------------------
    # Data loading
    # ----------------------------------------------------------

    def load_data(self, preloaded: dict[str, pd.DataFrame] | None = None):
        """
        Load and prepare daily data for the universe.

        Pass *preloaded* to skip yfinance calls (useful for tests).
        """
        if preloaded is not None:
            self.data = {}
            for symbol, df in preloaded.items():
                prepared = self._prepare_df(df)
                if prepared is not None:
                    self.data[symbol] = prepared
            return

        import yfinance as yf

        start = pd.to_datetime(self.cfg.start_date) - pd.DateOffset(
            days=self.cfg.warmup_days + 30
        )
        end = pd.to_datetime(self.cfg.end_date) + pd.DateOffset(days=5)

        print(f"Fetching daily data for {len(self.cfg.universe)} stocks ...")
        for symbol in self.cfg.universe:
            try:
                yf_sym = (
                    symbol
                    if symbol.endswith(".NS") or symbol.endswith(".BO")
                    else f"{symbol}.NS"
                )
                df = yf.Ticker(yf_sym).history(
                    start=start, end=end, auto_adjust=True
                )
                if df.empty or len(df) < 60:
                    continue
                df.columns = [c.lower() for c in df.columns]
                df.index = df.index.tz_localize(None)
                prepared = self._prepare_df(df)
                if prepared is not None:
                    self.data[symbol] = prepared
            except Exception as e:
                print(f"  skip {symbol}: {e}")

        # Load benchmark for RS ratio computation
        if self.cfg.benchmark_symbol:
            try:
                bench_df = yf.Ticker(self.cfg.benchmark_symbol).history(
                    start=start, end=end, auto_adjust=True
                )
                if not bench_df.empty and len(bench_df) >= 60:
                    bench_df.columns = [c.lower() for c in bench_df.columns]
                    bench_df.index = bench_df.index.tz_localize(None)
                    self.benchmark_data = bench_df
                    print(f"Loaded benchmark {self.cfg.benchmark_symbol} ({len(bench_df)} bars)")
            except Exception as e:
                print(f"  skip benchmark: {e}")

        print(f"Loaded {len(self.data)} stocks with indicators.")

    def _prepare_df(self, df: pd.DataFrame) -> pd.DataFrame | None:
        """Add indicators; return None if data is insufficient."""
        df = df.copy()
        df.columns = [str(c).lower() for c in df.columns]
        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(df.columns):
            return None
        if len(df) < 60:
            return None
        try:
            df = add_technical_indicators(df)
        except Exception:
            return None

        # RVOL (20-day average volume ratio)
        vol_avg = df["volume"].rolling(20).mean()
        df["rvol"] = df["volume"] / (vol_avg + 1e-10)
        return df

    # ----------------------------------------------------------
    # Main simulation
    # ----------------------------------------------------------

    def run(self):
        """Execute the full backtest simulation."""
        if not self.data:
            self.load_data()

        sim_start = pd.to_datetime(self.cfg.start_date)
        sim_end = pd.to_datetime(self.cfg.end_date)

        # Build a unified calendar of all trading days
        all_dates = pd.DatetimeIndex([])
        for df in self.data.values():
            all_dates = all_dates.union(df.index)
        all_dates = all_dates[(all_dates >= sim_start) & (all_dates <= sim_end)]
        all_dates = all_dates.sort_values()

        if all_dates.empty:
            print("No trading days in date range.")
            return

        for i, today in enumerate(all_dates):
            # 1. Execute pending buys from previous rebalance
            self._execute_pending_buys(today)

            # 2. Check SL exits
            self._process_sl_exits(today)

            # 3. Check swing exit triggers (daily)
            self._process_swing_exits(today)

            # 4. Mark-to-market
            self._record_equity(today)

            # 5. Rebalance check
            if self._is_rebalance_day(today, all_dates, i):
                self._rebalance(today)

    # ----------------------------------------------------------
    # Rebalance logic
    # ----------------------------------------------------------

    def _is_rebalance_day(
        self, today: pd.Timestamp, all_dates: pd.DatetimeIndex, idx: int
    ) -> bool:
        """Determine if today is a rebalance day."""
        if self.cfg.rebalance_freq == "weekly":
            # Last trading day of the week (Friday, or Thursday if Friday is holiday)
            if idx < len(all_dates) - 1:
                next_day = all_dates[idx + 1]
                return next_day.isocalendar()[1] != today.isocalendar()[1]
            return True  # last day in dataset
        elif self.cfg.rebalance_freq == "monthly":
            if idx < len(all_dates) - 1:
                return all_dates[idx + 1].month != today.month
            return True
        return False

    def _rebalance(self, today: pd.Timestamp):
        """
        On rebalance day:
          1. Rank the entire universe (including current holdings)
          2. Re-rank current holdings and update their current_rank
          3. Compare weakest holdings against best unowned candidates
          4. Replace only when the new candidate is meaningfully better
          5. Queue buys for new candidates (execute next day)
        """
        # ---- rank universe (with liquidity filter) ----
        ranked: list[dict] = []
        filtered_count = 0
        for symbol, df in self.data.items():
            if today not in df.index:
                continue
            loc = df.index.get_loc(today)
            if loc < 65:
                continue
            df_slice = df.iloc[: loc + 1]

            # Apply liquidity filter for non-held stocks only
            if symbol not in self.positions:
                if not self._passes_liquidity_filter(df_slice):
                    filtered_count += 1
                    continue

            rank_info = self._rank_stock(symbol, df_slice)
            if rank_info is not None:
                ranked.append(rank_info)

        ranked.sort(key=lambda x: x["rank_score"], reverse=True)
        rank_by_sym = {r["symbol"]: r for r in ranked}

        # ---- update current holdings' ranks ----
        for symbol in list(self.positions):
            pos = self.positions[symbol]
            info = rank_by_sym.get(symbol)
            if info is not None:
                pos.current_rank = info["rank_score"]
                pos.structure_level = info["setup"].structure_level
            else:
                pos.current_rank = 0.0  # can't rank → weakest

        # ---- identify replacements ----
        # Sort current holdings by rank (weakest first → candidates for replacement)
        held_sorted = sorted(
            self.positions.values(), key=lambda p: p.current_rank
        )
        # Unowned actionable candidates sorted by rank (best first)
        unowned = [
            r for r in ranked
            if r["symbol"] not in self.positions
            and r["rank_score"] >= self.cfg.min_swing_rank
            and r["setup"].actionable
        ]

        self._pending_buys.clear()

        # --- replace weak holdings when a meaningfully better candidate exists ---
        threshold = self.cfg.replacement_threshold
        unowned_idx = 0
        for pos in held_sorted:
            if unowned_idx >= len(unowned):
                break
            candidate = unowned[unowned_idx]
            # Replace if: (a) holding fell below minimum, OR
            #             (b) candidate rank exceeds holding rank by threshold
            holding_weak = pos.current_rank < self.cfg.min_swing_rank
            candidate_better = (
                candidate["rank_score"] - pos.current_rank >= threshold
            )
            if holding_weak or candidate_better:
                self._exit_position(
                    pos.symbol, today, reason="REPLACED_BY_BETTER"
                )
                self._pending_buys.append(candidate)
                unowned_idx += 1

        # --- fill empty slots with best unowned candidates ---
        open_slots = self.cfg.max_positions - (
            len(self.positions) + len(self._pending_buys)
        )
        while open_slots > 0 and unowned_idx < len(unowned):
            self._pending_buys.append(unowned[unowned_idx])
            unowned_idx += 1
            open_slots -= 1

    def _rank_stock(self, symbol: str, df_slice: pd.DataFrame) -> dict | None:
        """Run swing engine + ranker on a stock as of the last row."""
        latest = df_slice.iloc[-1]
        price = float(latest["close"])
        rvol = float(latest.get("rvol", 1.0))

        setup: SwingSetup = classify_swing_setup(
            df_slice, current_price=price, rvol=rvol
        )

        # Proxy entry quality from daily indicators
        rsi = float(latest.get("rsi", 50))
        cmf = float(latest.get("cmf", 0))
        squeeze = int(float(latest.get("squeeze_fire", 0)))
        entry_quality = self._proxy_entry_quality(rsi, cmf, rvol, squeeze)

        # Proxy MTF score from daily trend alignment
        ema50 = float(latest.get("ema_50", price))
        macd = float(latest.get("macd", 0))
        macd_signal = float(latest.get("macd_signal", 0))
        st_dir = float(latest.get("supertrend_direction", 0))
        mtf_proxy = (
            (0.3 if price > ema50 else 0)
            + (0.3 if macd > macd_signal else 0)
            + (0.4 if st_dir == 1 else 0)
        )

        rank = compute_swing_rank(
            df_slice,
            price=price,
            swing_setup=setup.as_dict(),
            mtf_score=mtf_proxy,
            entry_quality=entry_quality,
            rvol=rvol,
            sector_multiplier=1.0,
            rs_ratio=self._compute_rs_ratio(df_slice),
        )

        return {
            "symbol": symbol,
            "price": price,
            "setup": setup,
            "rank_score": rank["score"],
            "rank_bucket": rank["bucket"],
            "entry_quality": entry_quality,
            "rvol": rvol,
        }

    def _compute_rs_ratio(self, stock_df: pd.DataFrame, lookback: int = 63) -> float:
        """
        Compute relative strength ratio: stock return / benchmark return
        over *lookback* trading days.

        Returns 1.0 (neutral) if benchmark data is unavailable.
        """
        if self.benchmark_data is None or len(stock_df) < lookback + 1:
            return 1.0

        last_date = stock_df.index[-1]
        bench = self.benchmark_data

        # Find matching dates in benchmark
        bench_mask = bench.index <= last_date
        bench_slice = bench.loc[bench_mask]
        if len(bench_slice) < lookback + 1:
            return 1.0

        # Stock return over lookback
        stock_end = float(stock_df["close"].iloc[-1])
        stock_start = float(stock_df["close"].iloc[-lookback])
        if stock_start <= 0:
            return 1.0
        stock_ret = stock_end / stock_start

        # Benchmark return over lookback
        bench_end = float(bench_slice["close"].iloc[-1])
        bench_start = float(bench_slice["close"].iloc[-lookback])
        if bench_start <= 0:
            return 1.0
        bench_ret = bench_end / bench_start

        if bench_ret <= 0:
            return 1.0

        return stock_ret / bench_ret

    @staticmethod
    def _proxy_entry_quality(
        rsi: float, cmf: float, rvol: float, squeeze_fire: int
    ) -> int:
        """Approximate entry quality from daily indicators."""
        score = 30  # base
        if 35 <= rsi <= 55:
            score += 20
        if cmf > 0:
            score += 20
        if rvol > 1.2:
            score += 15
        if squeeze_fire:
            score += 15
        return min(100, score)

    # ----------------------------------------------------------
    # Liquidity & bad-stock filter
    # ----------------------------------------------------------

    def _passes_liquidity_filter(self, df_slice: pd.DataFrame) -> bool:
        """
        Pre-ranking gate to exclude illiquid, penny, or insufficient-data
        stocks before they are even ranked.

        Checks:
          1. Minimum number of trading days (min_trade_days)
          2. Price range (min_price to max_price)
          3. 20-day average volume (min_avg_volume)
          4. 20-day average turnover in Rs. (min_avg_turnover)
        """
        cfg = self.cfg

        # 1. Minimum history
        if len(df_slice) < cfg.min_trade_days:
            return False

        latest = df_slice.iloc[-1]
        price = float(latest["close"])

        # 2. Price range
        if price < cfg.min_price or price > cfg.max_price:
            return False

        # 3. Average daily volume (20-day)
        tail = df_slice.tail(20)
        avg_vol = float(tail["volume"].mean())
        if avg_vol < cfg.min_avg_volume:
            return False

        # 4. Average daily turnover (price × volume)
        avg_turnover = float((tail["close"] * tail["volume"]).mean())
        if avg_turnover < cfg.min_avg_turnover:
            return False

        return True

    # ----------------------------------------------------------
    # Entry execution (next-day)
    # ----------------------------------------------------------

    def _execute_pending_buys(self, today: pd.Timestamp):
        """Execute queued buys at today's open + slippage."""
        if not self._pending_buys:
            return

        buys_to_process = list(self._pending_buys)
        self._pending_buys.clear()

        for candidate in buys_to_process:
            symbol = candidate["symbol"]
            if symbol in self.positions:
                continue
            if len(self.positions) >= self.cfg.max_positions:
                break

            df = self.data.get(symbol)
            if df is None or today not in df.index:
                continue

            row = df.loc[today]
            open_price = float(row["open"])

            # Apply slippage (buy higher)
            entry_price = open_price * (1 + self.cfg.slippage_pct)

            # Transaction cost
            cost_per_share = entry_price * self.cfg.transaction_cost_pct

            # Structure-aware stop from the setup
            stop_loss = float(candidate["setup"].stop_loss)
            if stop_loss <= 0 or stop_loss >= entry_price:
                # Fallback: 1.5× ATR below entry
                atr = float(row.get("atr", entry_price * 0.02))
                stop_loss = entry_price - 1.5 * atr

            # Risk-based position sizing
            shares = compute_position_size(
                account_value=self._total_equity(today),
                entry_price=entry_price,
                stop_loss=stop_loss,
                risk_pct=self.cfg.risk_per_trade,
            )
            if shares <= 0:
                continue

            total_cost = shares * (entry_price + cost_per_share)
            if total_cost > self.cash:
                shares = int(self.cash // (entry_price + cost_per_share))
            if shares <= 0:
                continue

            total_cost = shares * (entry_price + cost_per_share)
            self.cash -= total_cost

            self.positions[symbol] = _Position(
                symbol=symbol,
                shares=shares,
                entry_price=round(entry_price, 2),
                stop_loss=round(stop_loss, 2),
                entry_date=today,
                setup_type=candidate["setup"].setup_type,
                swing_rank=candidate["rank_score"],
                current_rank=candidate["rank_score"],
                structure_level=float(candidate["setup"].structure_level),
            )

            self.trade_log.append(
                {
                    "date": today,
                    "symbol": symbol,
                    "action": "BUY",
                    "price": round(entry_price, 2),
                    "shares": shares,
                    "stop_loss": round(stop_loss, 2),
                    "setup_type": candidate["setup"].setup_type,
                    "swing_rank": candidate["rank_score"],
                    "cost": round(total_cost, 2),
                    "reason": "SWING_ENTRY",
                }
            )

    # ----------------------------------------------------------
    # Stop-loss exits
    # ----------------------------------------------------------

    def _process_sl_exits(self, today: pd.Timestamp):
        """Check every open position for SL hit, handle gap-through."""
        for symbol in list(self.positions):
            pos = self.positions[symbol]
            df = self.data.get(symbol)
            if df is None or today not in df.index:
                continue

            row = df.loc[today]
            low = float(row["low"])
            open_price = float(row["open"])

            if low <= pos.stop_loss:
                # Gap-through: if open is already below SL, exit at open
                exit_price = min(open_price, pos.stop_loss)
                self._exit_position(
                    symbol, today, reason="SL_HIT", exit_price=exit_price
                )

    # ----------------------------------------------------------
    # Swing exit triggers (daily, beyond SL)
    # ----------------------------------------------------------

    def _process_swing_exits(self, today: pd.Timestamp):
        """
        Daily exit checks beyond stop-loss:
          - Failed breakout: BREAKOUT setup but price fell back below the
            breakout level (structure_level)
          - Close below structure: price closes below the key support
            level from the setup classification
          - Rank deterioration: re-rank the stock today; if it drops
            below min_swing_rank, exit
        """
        for symbol in list(self.positions):
            if symbol not in self.positions:
                continue  # may have been removed by an earlier exit
            pos = self.positions[symbol]
            df = self.data.get(symbol)
            if df is None or today not in df.index:
                continue

            row = df.loc[today]
            close = float(row["close"])

            # --- Failed breakout ---
            if (
                self.cfg.exit_on_failed_breakout
                and pos.setup_type == "BREAKOUT"
                and pos.structure_level > 0
                and close < pos.structure_level
            ):
                self._exit_position(
                    symbol, today, reason="FAILED_BREAKOUT"
                )
                continue

            # --- Close below trailing structure ---
            if (
                self.cfg.exit_on_structure_break
                and pos.structure_level > 0
                and close < pos.structure_level * 0.98  # 2% buffer
            ):
                self._exit_position(
                    symbol, today, reason="STRUCTURE_BREAK"
                )
                continue

            # --- Rank deterioration (lightweight daily re-rank) ---
            if self.cfg.exit_on_rank_deterioration:
                loc = df.index.get_loc(today)
                if loc >= 65:
                    df_slice = df.iloc[: loc + 1]
                    info = self._rank_stock(symbol, df_slice)
                    if info is not None:
                        pos.current_rank = info["rank_score"]
                        pos.structure_level = info["setup"].structure_level
                        if info["rank_score"] < self.cfg.min_swing_rank:
                            self._exit_position(
                                symbol, today, reason="RANK_DETERIORATION"
                            )
                            continue

    # ----------------------------------------------------------
    # Exit helper
    # ----------------------------------------------------------

    def _exit_position(
        self,
        symbol: str,
        today: pd.Timestamp,
        reason: str,
        exit_price: float | None = None,
    ):
        """Close a position and record the trade."""
        pos = self.positions.get(symbol)
        if pos is None:
            return

        if exit_price is None:
            df = self.data.get(symbol)
            if df is not None and today in df.index:
                exit_price = float(df.loc[today, "close"])
            else:
                exit_price = pos.entry_price  # fallback

        # Transaction cost on exit
        cost = pos.shares * exit_price * self.cfg.transaction_cost_pct
        proceeds = pos.shares * exit_price - cost
        self.cash += proceeds

        pnl = proceeds - pos.shares * pos.entry_price
        risk_per_share = pos.entry_price - pos.stop_loss
        r_multiple = (
            round(pnl / (pos.shares * risk_per_share), 2)
            if risk_per_share > 0 and pos.shares > 0
            else 0.0
        )
        holding_days = (today - pos.entry_date).days if pos.entry_date else 0

        self.trade_log.append(
            {
                "date": today,
                "symbol": symbol,
                "action": "SELL",
                "price": round(exit_price, 2),
                "shares": pos.shares,
                "entry_price": pos.entry_price,
                "pnl": round(pnl, 2),
                "r_multiple": r_multiple,
                "holding_days": holding_days,
                "reason": reason,
                "setup_type": pos.setup_type,
            }
        )

        del self.positions[symbol]

    # ----------------------------------------------------------
    # Equity tracking
    # ----------------------------------------------------------

    def _total_equity(self, today: pd.Timestamp) -> float:
        """Cash + mark-to-market value of open positions."""
        stock_value = 0.0
        for sym, pos in self.positions.items():
            df = self.data.get(sym)
            if df is not None and today in df.index:
                stock_value += float(df.loc[today, "close"]) * pos.shares
            else:
                stock_value += pos.entry_price * pos.shares
        return self.cash + stock_value

    def _record_equity(self, today: pd.Timestamp):
        """Append today's equity snapshot."""
        stock_value = 0.0
        for sym, pos in self.positions.items():
            df = self.data.get(sym)
            if df is not None and today in df.index:
                stock_value += float(df.loc[today, "close"]) * pos.shares
            else:
                stock_value += pos.entry_price * pos.shares
        total = self.cash + stock_value
        self.portfolio_history.append(
            {
                "date": today,
                "cash": round(self.cash, 2),
                "stock_value": round(stock_value, 2),
                "total_value": round(total, 2),
                "open_positions": len(self.positions),
            }
        )

    # ----------------------------------------------------------
    # Results
    # ----------------------------------------------------------

    def get_equity_curve(self) -> pd.DataFrame:
        """Return the daily equity curve as a DataFrame."""
        return pd.DataFrame(self.portfolio_history)

    def get_trade_log(self) -> pd.DataFrame:
        """Return all trades as a DataFrame."""
        return pd.DataFrame(self.trade_log)

    def get_summary(self) -> dict:
        """Compute summary statistics for the backtest."""
        if not self.portfolio_history:
            return {"error": "No simulation data — call run() first"}

        equity = pd.DataFrame(self.portfolio_history)
        initial = self.cfg.initial_capital
        final = equity["total_value"].iloc[-1]
        total_return_pct = (final - initial) / initial * 100

        sells = [t for t in self.trade_log if t["action"] == "SELL"]
        n_trades = len(sells)
        wins = [t for t in sells if t.get("pnl", 0) > 0]
        win_rate = len(wins) / n_trades * 100 if n_trades else 0
        avg_pnl = np.mean([t["pnl"] for t in sells]) if sells else 0
        avg_r = np.mean([t["r_multiple"] for t in sells]) if sells else 0
        avg_hold = np.mean([t["holding_days"] for t in sells]) if sells else 0

        # Max drawdown
        running_max = equity["total_value"].cummax()
        drawdown = (equity["total_value"] - running_max) / running_max
        max_dd_pct = drawdown.min() * 100

        # Exit reason breakdown
        reason_counts = {}
        for t in sells:
            r = t.get("reason", "UNKNOWN")
            reason_counts[r] = reason_counts.get(r, 0) + 1

        return {
            "initial_capital": initial,
            "final_value": round(final, 2),
            "total_return_pct": round(total_return_pct, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "total_trades": n_trades,
            "win_rate_pct": round(win_rate, 1),
            "avg_pnl": round(avg_pnl, 2),
            "avg_r_multiple": round(avg_r, 2),
            "avg_holding_days": round(avg_hold, 1),
            "rebalance_freq": self.cfg.rebalance_freq,
            "start_date": self.cfg.start_date,
            "end_date": self.cfg.end_date,
            "exit_reasons": reason_counts,
        }

    def print_summary(self):
        """Pretty-print backtest results."""
        s = self.get_summary()
        if "error" in s:
            print(f"  {s['error']}")
            return

        print(f"\n{'='*60}")
        print(f"  SWING BACKTEST RESULTS")
        print(f"{'='*60}")
        print(f"  Period:         {s['start_date']} → {s['end_date']}")
        print(f"  Rebalance:      {s['rebalance_freq']}")
        print(f"  Initial:        Rs.{s['initial_capital']:,.0f}")
        print(f"  Final:          Rs.{s['final_value']:,.0f}")
        pct = s['total_return_pct']
        sign = "+" if pct >= 0 else ""
        print(f"  Total Return:   {sign}{pct:.2f}%")
        print(f"  Max Drawdown:   {s['max_drawdown_pct']:.2f}%")
        print(f"  Trades:         {s['total_trades']}")
        print(f"  Win Rate:       {s['win_rate_pct']:.1f}%")
        print(f"  Avg PnL/trade:  Rs.{s['avg_pnl']:,.2f}")
        print(f"  Avg R-multiple: {s['avg_r_multiple']:.2f}R")
        print(f"  Avg Holding:    {s['avg_holding_days']:.0f} days")
        reasons = s.get("exit_reasons", {})
        if reasons:
            print(f"\n  Exit Reasons:")
            for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
                print(f"    {reason:<25} {count}")
        print(f"{'='*60}\n")


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    from settings import SCAN_UNIVERSE
    from quant.backtest_analytics import compute_full_analytics, print_analytics

    # Small subset for quick test
    small_universe = SCAN_UNIVERSE[:10]
    cfg = SwingBacktestConfig(
        universe=small_universe,
        start_date="2023-06-01",
        end_date="2024-12-31",
        initial_capital=500_000,
        max_positions=5,
        rebalance_freq="weekly",
    )
    bt = SwingBacktester(cfg)
    bt.load_data()
    bt.run()

    # Print full analytics report
    report = compute_full_analytics(bt)
    print_analytics(report)

    trades = bt.get_trade_log()
    if not trades.empty:
        print("Last 10 trades:")
        print(trades.tail(10).to_string(index=False))
