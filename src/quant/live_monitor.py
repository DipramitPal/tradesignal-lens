"""
Live stock monitoring engine v3 — Hedge-fund-grade quant scanning.

15-minute intraday candle based with multi-timeframe confluence,
divergence detection, regime classification, adaptive SL/TP,
dynamic universe scanning, and sector rotation analysis.

v3 enhancements:
  - Partial exit / scaling out (sell in thirds at 1R, 2R, trail remainder)
  - Daily loss limit enforcement (defense mode)
  - Market-hours signal filtering (suppress BUY in open/close buffers)
  - Gap-up / gap-down detection
  - Multi-stock ranking with capital allocation priority
  - Dynamic universe rescanning
  - Correlation-aware position sizing
  - Trade journal integration
"""

import os
import sys
import time
import signal as os_signal
from datetime import datetime, time as dt_time
from typing import Optional

import pandas as pd
import numpy as np
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import (
    MONITOR_INTERVAL_MINUTES, MONITOR_SYMBOLS, SCAN_INTERVAL_MINUTES,
    DEFAULT_ACCOUNT_VALUE, RISK_PER_TRADE_PCT, SYMBOL_SECTOR,
    DAILY_LOSS_LIMIT, GAP_THRESHOLD_PCT, SCALING_LOTS,
    MARKET_OPEN_BUFFER_MINUTES, MARKET_CLOSE_BUFFER_MINUTES,
    UNIVERSE_RESCAN_INTERVAL, EXIT_SCORE_THRESHOLD,
)
from feature_engineering import add_technical_indicators, compute_pivot_points
from signal_generator import (
    score_signals, compute_mtf_confluence, apply_divergence_boost,
    apply_rvol_multiplier, apply_sector_adjustment, normalize_score,
    score_to_recommendation, score_to_confidence,
    generate_signals, compute_stop_loss, compute_trailing_stop,
)
from market_data.data_cache import DataCache
from market_data.market_utils import now_ist, MARKET_OPEN, MARKET_CLOSE
from quant.regime_classifier import classify_regime, get_weight_table, is_in_transition
from quant.divergence_detector import detect_all_divergences, summarize_divergences
from quant.risk_manager import (
    compute_initial_sl, compute_phase_sl, check_exit_triggers,
    compute_exit_score, compute_position_size, compute_entry_quality,
    check_rr_gate, get_regime_risk_pct,
)
from quant.sector_analyzer import SectorAnalyzer
from quant.trade_journal import TradeJournal
from quant.correlation_engine import CorrelationEngine
from portfolio.portfolio_manager import PortfolioManager
from quant.universe_scanner import UniverseScanner
from quant.breakout_manager import BreakoutManager


class Position:
    """Tracks a single stock position with scaling-out support."""

    def __init__(self, symbol: str, entry_price: float, entry_date: str,
                 total_shares: int = 0, lots: int = SCALING_LOTS):
        self.symbol = symbol
        self.entry_price = entry_price
        self.entry_date = entry_date
        self.highest_since_entry = entry_price
        self.stop_loss = 0.0
        self.trailing_stop = 0.0
        self.phase = "INITIAL"

        # Scaling out
        self.total_shares = total_shares
        self.lots_remaining = lots  # starts at SCALING_LOTS (default 3)
        self.lots_initial = lots
        self.shares_per_lot = max(1, total_shares // lots) if total_shares > 0 else 0

    def update(self, current_price: float, atr: float,
               parabolic_sar: float = 0):
        """Update position tracking with latest price."""
        self.highest_since_entry = max(self.highest_since_entry, current_price)

        new_sl, phase = compute_phase_sl(
            entry_price=self.entry_price,
            current_price=current_price,
            highest_since_entry=self.highest_since_entry,
            atr_15m=atr,
            parabolic_sar=parabolic_sar,
            current_sl=self.stop_loss,
        )
        self.stop_loss = new_sl
        self.trailing_stop = new_sl
        self.phase = phase

    @property
    def pnl_pct(self):
        return 0.0

    def pnl_at(self, current_price: float) -> float:
        return round(((current_price - self.entry_price) / self.entry_price) * 100, 2)

    def r_multiple(self, current_price: float) -> float:
        """Current R-multiple (profit in units of initial risk)."""
        initial_risk = abs(self.entry_price - self.stop_loss) if self.stop_loss > 0 else (self.entry_price * 0.015)
        if initial_risk <= 0:
            initial_risk = self.entry_price * 0.015
        return round((current_price - self.entry_price) / initial_risk, 2)

    def shares_for_partial(self) -> int:
        """Number of shares to sell in one partial exit (1 lot)."""
        if self.lots_remaining <= 1:
            # Last lot — sell everything remaining
            return self.total_shares
        return self.shares_per_lot

    def record_partial_exit(self, shares_sold: int):
        """Update lot tracking after a partial exit."""
        self.lots_remaining = max(0, self.lots_remaining - 1)
        self.total_shares = max(0, self.total_shares - shares_sold)


class LiveMonitor:
    """
    Monitors stocks at 15-minute intervals using an intraday + daily
    multi-timeframe pipeline with regime-adaptive signal scoring.

    v3: Includes partial exits, daily loss limit, market hours filtering,
    gap detection, multi-stock ranking, dynamic universe rescanning,
    correlation engine, and trade journal integration.
    """

    def __init__(
        self,
        symbols: list[str] | None = None,
        interval_minutes: int | None = None,
        account_value: float = DEFAULT_ACCOUNT_VALUE,
    ):
        self.symbols = symbols or MONITOR_SYMBOLS
        self.interval = (interval_minutes or SCAN_INTERVAL_MINUTES) * 60
        self.positions: dict[str, Position] = {}
        self.running = False
        self._cycle_count = 0
        self.account_value = account_value

        # Quant components
        self.cache = DataCache()
        self.sector_analyzer = SectorAnalyzer()
        self._regime = "RANGE_BOUND"

        # v3: New components
        self.trade_journal = TradeJournal()
        self.correlation_engine = CorrelationEngine(account_value=account_value)
        self._universe_scanner = UniverseScanner(universe=self.symbols)

        # v4: Portfolio integration
        self.portfolio = PortfolioManager()
        self._portfolio_loaded = False

        # v3: Daily loss tracking
        self._daily_pnl = 0.0  # cumulative PnL today (percentage)
        self._defense_mode = False
        self._last_trading_day = None

        # v3: Universe rescan tracking
        self._last_universe_scan = 0  # timestamp of last scan
        self._universe_scan_interval = UNIVERSE_RESCAN_INTERVAL * 60

        # v4: Breakout tracking
        self.breakout_mgr = BreakoutManager()

    def _load_portfolio_positions(self):
        """Auto-load positions from the persistent portfolio."""
        if self._portfolio_loaded:
            return

        self.portfolio._load()  # Refresh from disk

        if self.portfolio.is_empty():
            self._portfolio_loaded = True
            return

        # Update account value from portfolio
        self.account_value = self.portfolio.account_value

        loaded = []
        for symbol, holding in self.portfolio.holdings.items():
            if symbol not in self.positions:
                self.add_position(
                    symbol,
                    entry_price=holding["avg_price"],
                    shares=holding["qty"],
                    stop_loss=holding.get("stop_loss", 0),
                )
                loaded.append(symbol)

            # Ensure owned symbols are always monitored
            if symbol not in self.symbols:
                self.symbols.append(symbol)

        if loaded:
            print(f"  [Portfolio] Loaded {len(loaded)} positions: {', '.join(loaded)}")
            print(f"  [Portfolio] Account: Rs.{self.account_value:,.0f} | "
                  f"Invested: Rs.{self.portfolio.get_total_invested():,.0f} | "
                  f"Available: Rs.{self.portfolio.get_available_capital():,.0f}")

        self._portfolio_loaded = True

    def add_position(self, symbol: str, entry_price: float, entry_date: str = "",
                     shares: int = 0, stop_loss: float = 0):
        """Mark a stock as already bought at a given price."""
        if not entry_date:
            entry_date = datetime.now().strftime("%Y-%m-%d")
        pos = Position(symbol, entry_price, entry_date, total_shares=shares)
        # Set initial SL
        if stop_loss > 0:
            pos.stop_loss = stop_loss
        else:
            pos.stop_loss = compute_initial_sl(entry_price, entry_price * 0.015)
        self.positions[symbol] = pos
        print(f"  Position added: {symbol} @ {entry_price} ({shares} shares) on {entry_date}")

    def remove_position(self, symbol: str):
        """Remove a position (after selling)."""
        if symbol in self.positions:
            del self.positions[symbol]

    def start(self):
        """Start the monitoring loop with warm cache."""
        self.running = True

        def shutdown(signum, frame):
            print("\n\nStopping monitor...")
            self.running = False

        os_signal.signal(os_signal.SIGINT, shutdown)
        os_signal.signal(os_signal.SIGTERM, shutdown)

        print(f"\n{'='*70}")
        print(f"  LIVE STOCK MONITOR v3 — QUANT ENGINE")

        # Auto-load portfolio positions
        self._load_portfolio_positions()

        owned_count = len(self.positions)
        print(f"  Watching: {', '.join(self.symbols[:10])}"
              f"{'...' if len(self.symbols) > 10 else ''}")
        if owned_count > 0:
            print(f"  Portfolio: {owned_count} owned positions loaded")
        print(f"  Refresh interval: {self.interval // 60} minutes")
        print(f"  Account value: Rs.{self.account_value:,.0f}")
        print(f"  Defense mode: {'ON' if self._defense_mode else 'OFF'}")
        print(f"  Press Ctrl+C to stop")
        print(f"{'='*70}")

        # Warm cache on startup
        print(f"\n  Warming data cache...")
        self.cache.warm_cache(self.symbols)

        # Initial scan
        self._run_cycle()

        while self.running:
            next_run = datetime.now().timestamp() + self.interval
            while self.running and datetime.now().timestamp() < next_run:
                time.sleep(1)
            if self.running:
                self._run_cycle()

    def run_once(self) -> list[dict]:
        """Run a single monitoring cycle (warm cache + scan)."""
        # Auto-load portfolio positions
        self._load_portfolio_positions()

        if not self.cache.get_cached_symbols():
            print(f"\n  Warming data cache for {len(self.symbols)} symbols...")
            self.cache.warm_cache(self.symbols)
        else:
            self.cache.refresh_intraday(self.symbols)
        return self._run_cycle()

    def _run_cycle(self) -> list[dict]:
        """Execute one full monitoring cycle."""
        self._cycle_count += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        print(f"\n{'─'*70}")
        print(f"  Scan #{self._cycle_count} at {now}")
        print(f"{'─'*70}")

        # --- v3: Reset daily PnL at start of new trading day ---
        self._check_daily_reset()

        # --- v3: Defense mode status ---
        if self._defense_mode:
            print(f"  ⚠️  DEFENSE MODE ACTIVE — daily loss limit hit ({self._daily_pnl:.1f}%)")
            print(f"      No new BUY signals will be generated.")

        # Refresh intraday data
        self.cache.refresh_intraday(self.symbols)
        self.cache.refresh_daily_if_needed(self.symbols)

        # --- v3: Dynamic universe rescanning ---
        self._maybe_rescan_universe()

        # Classify regime from daily data (use first symbol with data)
        for sym in self.symbols:
            df_daily = self.cache.get_daily(sym)
            if not df_daily.empty and len(df_daily) >= 50:
                try:
                    df_daily_ind = add_technical_indicators(df_daily.copy())
                    self._regime = classify_regime(df_daily_ind, self._regime)
                except Exception:
                    pass
                break

        weight_table = get_weight_table(self._regime)
        regime_status = f"  Market Regime: {self._regime}"
        if is_in_transition():
            regime_status += " (transitioning)"
        print(regime_status)

        # --- v3: Market hours check ---
        market_hours_status = self._get_market_hours_status()
        if market_hours_status:
            print(f"  {market_hours_status}")

        results = []
        for symbol in self.symbols:
            try:
                result = self._analyze_symbol(symbol, weight_table)
                results.append(result)
                self._print_recommendation(result)
            except Exception as e:
                print(f"\n  [{symbol}] Error: {e}")
                results.append({"symbol": symbol, "error": str(e)})

        # --- v3: Multi-stock ranking ---
        self._print_ranked_summary(results)

        # --- v3: Trade journal summary ---
        journal_summary = self.trade_journal.get_summary_text()
        if journal_summary:
            print(f"\n{journal_summary}")

        return results

    # ------------------------------------------------------------------
    # v3: Daily Loss Limit / Defense Mode
    # ------------------------------------------------------------------

    def _check_daily_reset(self):
        """Reset daily PnL tracking at start of a new trading day."""
        today = datetime.now().date()
        if self._last_trading_day != today:
            self._daily_pnl = 0.0
            self._defense_mode = False
            self._last_trading_day = today

    def _update_daily_pnl(self, pnl_pct: float):
        """Add a realized P&L to daily tracking and check defense trigger."""
        self._daily_pnl += pnl_pct
        if self._daily_pnl <= -(DAILY_LOSS_LIMIT * 100):
            if not self._defense_mode:
                print(f"\n  🛑 DEFENSE MODE ACTIVATED — Daily loss: {self._daily_pnl:.1f}%")
                print(f"     All new BUY signals suppressed. Trailing stops tightened.")
            self._defense_mode = True

    # ------------------------------------------------------------------
    # v3: Market Hours Filtering
    # ------------------------------------------------------------------

    def _get_market_hours_status(self) -> str:
        """Check if current time is in a restricted trading window."""
        try:
            now = now_ist()
            current_time = now.time()
        except Exception:
            return ""

        open_buffer_end = dt_time(
            MARKET_OPEN.hour,
            MARKET_OPEN.minute + MARKET_OPEN_BUFFER_MINUTES,
        )
        close_buffer_start = dt_time(
            MARKET_CLOSE.hour,
            MARKET_CLOSE.minute - MARKET_CLOSE_BUFFER_MINUTES,
        )

        if current_time < open_buffer_end:
            return "🕐 Opening buffer — BUY signals suppressed (volatility)"
        if current_time >= close_buffer_start:
            return "🕐 Closing buffer — only exit/SL signals allowed"
        return ""

    def _is_buy_suppressed(self) -> bool:
        """Check if BUY signals should be suppressed due to time or defense mode."""
        if self._defense_mode:
            return True

        try:
            now = now_ist()
            current_time = now.time()
        except Exception:
            return False

        # Opening buffer
        open_buffer_end = dt_time(
            MARKET_OPEN.hour,
            MARKET_OPEN.minute + MARKET_OPEN_BUFFER_MINUTES,
        )
        if current_time < open_buffer_end:
            return True

        # Closing buffer
        close_buffer_start = dt_time(
            MARKET_CLOSE.hour,
            MARKET_CLOSE.minute - MARKET_CLOSE_BUFFER_MINUTES,
        )
        if current_time >= close_buffer_start:
            return True

        return False

    # ------------------------------------------------------------------
    # v3: Dynamic Universe Rescanning
    # ------------------------------------------------------------------

    def _maybe_rescan_universe(self):
        """Periodically rescan the universe for new opportunities."""
        now = datetime.now().timestamp()
        if now - self._last_universe_scan < self._universe_scan_interval:
            return

        self._last_universe_scan = now
        try:
            # Use cached daily data for lightweight scan
            daily_cache = {
                sym: self.cache.get_daily(sym) for sym in self._universe_scanner.universe
            }
            new_symbols = self._universe_scanner.scan_lightweight(daily_cache)

            # Add newly discovered symbols to monitoring list
            added = []
            for sym in new_symbols:
                if sym not in self.symbols:
                    self.symbols.append(sym)
                    added.append(sym)
                    # Warm cache for new symbol
                    self.cache.warm_cache([sym])

            if added:
                print(f"  [Universe] Added {len(added)} new symbols: {', '.join(added[:5])}")
        except Exception as e:
            print(f"  [Universe] Rescan error: {e}")

    # ------------------------------------------------------------------
    # Core Analysis
    # ------------------------------------------------------------------

    def _analyze_symbol(self, symbol: str, weight_table: dict) -> dict:
        """Analyze a single stock using the full MTF quant pipeline."""

        # --- 1. Get data ---
        df_daily = self.cache.get_daily(symbol)
        df_intraday = self.cache.get_intraday(symbol)

        # Fallback to daily-only if no intraday
        if df_intraday.empty:
            df_intraday = df_daily.copy()

        if df_daily.empty and df_intraday.empty:
            return {"symbol": symbol, "error": "No data available"}

        # --- 2. Add indicators to both timeframes ---
        try:
            df_daily_ind = add_technical_indicators(df_daily.copy()) if not df_daily.empty else pd.DataFrame()
        except Exception:
            df_daily_ind = pd.DataFrame()

        try:
            df_15m_ind = add_technical_indicators(df_intraday.copy()) if not df_intraday.empty else pd.DataFrame()
        except Exception:
            df_15m_ind = pd.DataFrame()

        # Use whichever has data
        df_primary = df_15m_ind if not df_15m_ind.empty else df_daily_ind
        if df_primary.empty:
            return {"symbol": symbol, "error": "Insufficient data for analysis"}

        latest = df_primary.iloc[-1]
        prev = df_primary.iloc[-2] if len(df_primary) > 1 else latest

        current_price = float(latest["close"])
        atr = float(latest.get("atr", current_price * 0.02))
        rsi = float(latest.get("rsi", 50))

        # --- 3. Pivot Points ---
        prev_ohlc = self.cache.get_previous_day_ohlc(symbol)
        pivots = compute_pivot_points(prev_ohlc) if prev_ohlc else {}

        # --- 4. Score signals ---
        score_15m = score_signals(df_primary, weight_table, pivots=pivots)
        score_daily = score_signals(df_daily_ind, weight_table) if not df_daily_ind.empty else 0.0
        mtf_score = compute_mtf_confluence(score_15m, score_daily)

        # --- 5. Divergence detection ---
        divergences = detect_all_divergences(df_primary, lookback=50)
        div_summary = summarize_divergences(divergences)
        mtf_score = apply_divergence_boost(mtf_score, div_summary["direction"])

        # --- 6. RVOL multiplier ---
        vol = float(latest.get("volume", 0))
        vol_avg = df_primary["volume"].rolling(20).mean().iloc[-1] if len(df_primary) >= 20 else vol
        rvol = vol / (vol_avg + 1e-10)
        mtf_score = apply_rvol_multiplier(mtf_score, rvol)

        # --- 7. Sector adjustment ---
        sector_mult = self.sector_analyzer.get_sector_multiplier(symbol)
        mtf_score = apply_sector_adjustment(mtf_score, sector_mult)

        # --- 8. Normalize ---
        normalized = normalize_score(mtf_score, max_possible=0.8)

        # --- 9. Build recommendation ---
        owned = symbol in self.positions
        supertrend_dir = float(latest.get("supertrend_direction", 0))
        cmf = float(latest.get("cmf", 0))
        psar = float(latest.get("psar", 0))
        squeeze_fire = int(latest.get("squeeze_fire", 0))

        # Day change
        prev_close = float(prev["close"])
        day_change_pct = round(((current_price - prev_close) / prev_close) * 100, 2)

        # --- v3: Gap detection ---
        gap_status = self._detect_gap(day_change_pct)

        # Entry quality
        near_support = False
        near_fib_618 = False
        if pivots:
            s3 = pivots.get("s3", 0)
            near_support = abs(current_price - s3) / (current_price + 1e-10) < 0.015 if s3 > 0 else False
        fib_618 = float(latest.get("fib_618", 0))
        if fib_618 > 0:
            near_fib_618 = abs(current_price - fib_618) / (current_price + 1e-10) < 0.015

        entry_quality = compute_entry_quality(
            current_price, rsi, squeeze_fire, rvol, cmf,
            near_support=near_support, near_fib_618=near_fib_618,
        )

        recommendation = self._build_recommendation(
            symbol=symbol, price=current_price, normalized_score=normalized,
            entry_quality=entry_quality, rsi=rsi, cmf=cmf,
            supertrend_dir=supertrend_dir, psar=psar, atr=atr,
            pivots=pivots, div_summary=div_summary, owned=owned,
            gap_status=gap_status, rvol=rvol,
        )

        # Update position if owned
        if owned:
            self.positions[symbol].update(current_price, atr, psar)

        result = {
            "symbol": symbol,
            "price": current_price,
            "day_change_pct": day_change_pct,
            "rsi": round(rsi, 1),
            "cmf": round(cmf, 3),
            "adx": round(float(latest.get("adx", 0)), 1),
            "supertrend": "Bullish" if supertrend_dir == 1 else "Bearish",
            "regime": self._regime,
            "mtf_score": round(normalized, 3),
            "rvol": round(rvol, 2),
            "entry_quality": entry_quality,
            "divergence": div_summary["direction"],
            "sector": SYMBOL_SECTOR.get(symbol, "MISC"),
            "squeeze_fire": bool(squeeze_fire),
            "owned": owned,
            "recommendation": recommendation,
            "gap_status": gap_status,
        }

        if pivots:
            result["pivot_s3"] = pivots.get("s3", 0)
            result["pivot_r3"] = pivots.get("r3", 0)

        if owned:
            pos = self.positions[symbol]
            result["entry_price"] = pos.entry_price
            result["pnl_pct"] = pos.pnl_at(current_price)
            result["trailing_stop"] = pos.trailing_stop
            result["sl_phase"] = pos.phase
            result["highest_since_entry"] = pos.highest_since_entry
            result["lots_remaining"] = pos.lots_remaining
            result["r_multiple"] = pos.r_multiple(current_price)

        # --- v4: Breakout detection & dynamic SL ---
        bo = self.breakout_mgr.check(
            symbol, current_price, df_daily,
            atr=atr, rvol=rvol,
            current_sl=result.get("trailing_stop", 0),
        )
        result["breakout"] = bo["breakout"]
        result["breakout_level"] = bo["level"]
        result["pct_above_breakout"] = bo["pct_above"]
        if bo["breakout"]:
            result["breakout_sl"] = bo["adjusted_sl"]
            result["breakout_phase"] = bo["phase"]
            result["breakout_detected_at"] = bo.get("detected_at", "")
            # Override SL for owned positions if breakout SL is tighter
            if owned and bo["adjusted_sl"] > result.get("trailing_stop", 0):
                result["trailing_stop"] = bo["adjusted_sl"]
                result["sl_phase"] = "BREAKOUT_TRAIL"
                # Persist updated SL to portfolio
                self.portfolio.update_holding(
                    symbol, stop_loss=bo["adjusted_sl"],
                )

        return result

    # ------------------------------------------------------------------
    # v3: Gap Detection
    # ------------------------------------------------------------------

    def _detect_gap(self, day_change_pct: float) -> str:
        """Detect gap-up or gap-down conditions."""
        if day_change_pct > GAP_THRESHOLD_PCT:
            return "GAP_UP"
        elif day_change_pct < -GAP_THRESHOLD_PCT:
            return "GAP_DOWN"
        return "NORMAL"

    # ------------------------------------------------------------------
    # Recommendation Engine
    # ------------------------------------------------------------------

    def _build_recommendation(
        self, *, symbol, price, normalized_score, entry_quality,
        rsi, cmf, supertrend_dir, psar, atr, pivots, div_summary, owned,
        gap_status="NORMAL", rvol=1.0,
    ) -> dict:
        """Build recommendation using the normalized MTF score."""
        action = "HOLD"
        confidence = score_to_confidence(normalized_score)
        reasons = []
        risk_notes = []

        if owned:
            pos = self.positions[symbol]
            pnl = pos.pnl_at(price)
            r_mult = pos.r_multiple(price)

            # Check exit triggers using weighted scoring
            should_exit, exit_score, exit_reasons = compute_exit_score(
                rsi_15m=rsi,
                supertrend_dir_15m=supertrend_dir,
                cmf=cmf,
                parabolic_sar=psar,
                current_price=price,
                pivot_r3=pivots.get("r3", 0) if pivots else 0,
                divergence_direction=div_summary["direction"],
            )

            # --- STOP-LOSS HIT ---
            if price <= pos.trailing_stop and pos.trailing_stop > 0:
                action = "SELL NOW"
                confidence = "HIGH"
                reasons.append(f"Price hit trailing stop ({pos.trailing_stop:.2f})")
                # Log to journal
                self.trade_journal.log_exit(
                    symbol=symbol, exit_price=price, reason="Stop-loss hit"
                )
                self._update_daily_pnl(pnl)

            # --- v3: PARTIAL EXITS (scaling out) ---
            elif pos.lots_remaining > 1 and r_mult >= 2.0 and pos.lots_remaining == pos.lots_initial - 1:
                # 2R profit — sell second lot
                shares_to_sell = pos.shares_for_partial()
                action = f"SELL 1/{pos.lots_initial} (Book 2R Profit)"
                confidence = "HIGH"
                reasons.append(f"At {r_mult:.1f}R profit — scaling out 2nd lot")
                reasons.append(f"Sell {shares_to_sell} shares, keep {pos.lots_remaining - 1} lot(s)")
                risk_notes.append(f"Let remaining lot ride with trailing stop")
                pos.record_partial_exit(shares_to_sell)
                self.trade_journal.log_partial_exit(
                    symbol=symbol, exit_price=price,
                    shares_sold=shares_to_sell, reason="2R partial exit"
                )

            elif pos.lots_remaining > 1 and r_mult >= 1.0 and pos.lots_remaining == pos.lots_initial:
                # 1R profit — sell first lot
                shares_to_sell = pos.shares_for_partial()
                action = f"SELL 1/{pos.lots_initial} (Book Partial Profit)"
                confidence = "HIGH"
                reasons.append(f"At {r_mult:.1f}R profit — scaling out 1st lot")
                reasons.append(f"Sell {shares_to_sell} shares, keep {pos.lots_remaining - 1} lot(s)")
                risk_notes.append(f"Move SL to breakeven on remaining lots")
                pos.record_partial_exit(shares_to_sell)
                self.trade_journal.log_partial_exit(
                    symbol=symbol, exit_price=price,
                    shares_sold=shares_to_sell, reason="1R partial exit"
                )

            # --- EXIT TRIGGERS (weighted scoring) ---
            elif should_exit and pnl > 0:
                action = "SELL (Book Profit)"
                confidence = "HIGH"
                reasons.append(f"Exit score: {exit_score:.2f} ≥ {EXIT_SCORE_THRESHOLD}")
                reasons.extend(exit_reasons)
                reasons.append(f"P&L: +{pnl:.1f}%")
                self.trade_journal.log_exit(
                    symbol=symbol, exit_price=price, reason="Exit triggers"
                )
                self._update_daily_pnl(pnl)

            elif should_exit and pnl < -5:
                action = "SELL (Cut Loss)"
                confidence = "HIGH"
                reasons.append(f"Exit score: {exit_score:.2f}")
                reasons.extend(exit_reasons)
                reasons.append(f"P&L: {pnl:.1f}%")
                self.trade_journal.log_exit(
                    symbol=symbol, exit_price=price, reason="Cut loss"
                )
                self._update_daily_pnl(pnl)

            elif normalized_score < -0.30:
                action = "SELL"
                confidence = "MEDIUM"
                reasons.append(f"MTF score bearish ({normalized_score:.2f})")

            elif normalized_score > 0.20:
                action = "HOLD"
                confidence = "HIGH"
                reasons.append("Trend still positive — let winner run")
                reasons.append(f"Trailing SL: {pos.trailing_stop:.2f} (Phase: {pos.phase})")
                if pos.lots_remaining < pos.lots_initial:
                    reasons.append(f"Scaled out {pos.lots_initial - pos.lots_remaining}/{pos.lots_initial} lots")

            else:
                action = "HOLD"
                confidence = "LOW"
                reasons.append(f"No strong exit signal (MTF: {normalized_score:.2f})")
                reasons.append(f"Watch SL at {pos.trailing_stop:.2f}")

            risk_notes.append(f"Entry: {pos.entry_price:.2f} | P&L: {pnl:+.1f}% | R: {r_mult:+.1f}")
            risk_notes.append(f"SL Phase: {pos.phase} | SL: {pos.trailing_stop:.2f}")
            if pos.lots_remaining < pos.lots_initial:
                risk_notes.append(f"Lots: {pos.lots_remaining}/{pos.lots_initial} remaining")

        else:
            # NOT OWNED — should we buy?
            rec = score_to_recommendation(normalized_score)
            sl_price = compute_initial_sl(price, atr)

            # --- v3: R:R Gate ---
            rr_passes, rr_ratio, rr_reason = check_rr_gate(
                entry=price, sl=sl_price,
                pivot_r3=pivots.get("r3", 0) if pivots else 0,
            )

            # --- v3: BUY suppression checks ---
            buy_suppressed = self._is_buy_suppressed()
            suppress_reason = ""
            if self._defense_mode:
                suppress_reason = f"Defense mode active (daily PnL: {self._daily_pnl:.1f}%)"
            elif buy_suppressed:
                suppress_reason = "Market hours buffer — BUY suppressed"

            # --- v3: Gap detection override ---
            if gap_status == "GAP_UP" and "BUY" in rec:
                action = "WAIT"
                confidence = "MEDIUM"
                reasons.append(f"Gap-up detected (+{abs(price - float(self.cache.get_daily(symbol).iloc[-2]['close']) if not self.cache.get_daily(symbol).empty else 0):.1f}%)")
                reasons.append("Wait for gap-fill retracement before entering")
                risk_notes.append(f"Gap threshold: {GAP_THRESHOLD_PCT}%")

            elif gap_status == "GAP_DOWN" and "BUY" in rec:
                # Gap down — require extra confirmation
                if not (rsi < 30 and div_summary["direction"] == "BULLISH"):
                    action = "WAIT"
                    confidence = "LOW"
                    reasons.append("Gap-down — potential trap")
                    reasons.append("Need RSI < 30 + bullish divergence to enter")

            elif buy_suppressed and "BUY" in rec:
                action = "WATCHLIST"
                confidence = "LOW"
                reasons.append(suppress_reason)
                reasons.append(f"Signal is positive ({normalized_score:.2f}) — monitor for entry after buffer")

            elif not rr_passes and "BUY" in rec:
                action = "WATCHLIST"
                confidence = "LOW"
                reasons.append(rr_reason)
                reasons.append(f"Signal is positive ({normalized_score:.2f}) but R:R insufficient")

            elif "STRONG BUY" in rec and entry_quality >= 50:
                # --- v3: Regime-adaptive position sizing ---
                regime_risk = get_regime_risk_pct(self._regime)
                shares = compute_position_size(self.account_value, price, sl_price, risk_pct=regime_risk)

                # --- v3: Correlation check ---
                existing_syms = list(self.positions.keys())
                daily_data = {s: self.cache.get_daily(s) for s in existing_syms + [symbol]}
                shares, corr_note = self.correlation_engine.get_position_size_adjustment(
                    symbol, existing_syms, daily_data, shares
                )

                action = "BUY"
                confidence = "HIGH"
                reasons.append(f"Strong MTF score: {normalized_score:.2f}")
                reasons.append(f"Entry quality: {entry_quality}/100")
                reasons.append(f"R:R ratio: {rr_ratio:.1f}")
                if div_summary["direction"] == "BULLISH":
                    reasons.append(f"Bullish divergence confirmed ({div_summary['count']} indicators)")
                reasons.append(f"Set SL at {sl_price:.2f}")
                risk_notes.append(f"Suggested: {shares} shares ({regime_risk*100:.1f}% risk, {self._regime})")
                if corr_note:
                    risk_notes.append(corr_note)

            elif "BUY" in rec and entry_quality >= 50:
                regime_risk = get_regime_risk_pct(self._regime)
                shares = compute_position_size(self.account_value, price, sl_price, risk_pct=regime_risk)

                existing_syms = list(self.positions.keys())
                daily_data = {s: self.cache.get_daily(s) for s in existing_syms + [symbol]}
                shares, corr_note = self.correlation_engine.get_position_size_adjustment(
                    symbol, existing_syms, daily_data, shares
                )

                action = "BUY"
                confidence = "MEDIUM"
                reasons.append(f"Moderate MTF score: {normalized_score:.2f}")
                reasons.append(f"Entry quality: {entry_quality}/100")
                reasons.append(f"R:R ratio: {rr_ratio:.1f}")
                reasons.append(f"Set SL at {sl_price:.2f}")
                risk_notes.append(f"Suggested: {shares} shares ({regime_risk*100:.1f}% risk, {self._regime})")
                if corr_note:
                    risk_notes.append(corr_note)

            elif "BUY" in rec and entry_quality < 50:
                action = "WATCHLIST"
                confidence = "LOW"
                reasons.append(f"Signal is positive ({normalized_score:.2f}) but entry quality low ({entry_quality}/100)")
                reasons.append("Wait for pullback to support before entering")

            elif normalized_score < -0.30:
                action = "AVOID"
                confidence = "HIGH"
                reasons.append(f"Bearish MTF score: {normalized_score:.2f}")
                if div_summary["direction"] == "BEARISH":
                    reasons.append("Bearish divergence detected")

            else:
                action = "WAIT"
                confidence = "LOW"
                reasons.append(f"No clear signal (MTF: {normalized_score:.2f})")
                if entry_quality < 50:
                    reasons.append(f"Entry quality: {entry_quality}/100 — below threshold")

            if pivots:
                risk_notes.append(f"Pivot S3: {pivots.get('s3', 'N/A')} | R3: {pivots.get('r3', 'N/A')}")
            risk_notes.append(f"SL (if buying): {sl_price:.2f}")

        return {
            "action": action,
            "confidence": confidence,
            "reasons": reasons,
            "risk_notes": risk_notes,
        }

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def _print_recommendation(self, result: dict):
        """Print a single stock recommendation in user-friendly format."""
        if "error" in result:
            return

        sym = result["symbol"]
        price = result["price"]
        change = result["day_change_pct"]
        change_icon = "+" if change >= 0 else ""
        rec = result["recommendation"]
        action = rec["action"]
        conf = rec["confidence"]

        print(f"\n  {sym}  ({result.get('sector', '')})")
        print(f"  {'─'*55}")
        print(f"  Price: {price:.2f}  ({change_icon}{change:.2f}%)")

        # Gap status
        gap = result.get("gap_status", "NORMAL")
        gap_str = f"  |  ⚡ {gap}" if gap != "NORMAL" else ""

        print(f"  Regime: {result['regime']}  |  MTF Score: {result['mtf_score']:.3f}"
              f"  |  Quality: {result['entry_quality']}/100{gap_str}")
        print(f"  RSI: {result['rsi']}  |  ADX: {result['adx']}"
              f"  |  RVOL: {result['rvol']:.1f}x  |  CMF: {result['cmf']:.3f}")
        print(f"  Supertrend: {result['supertrend']}"
              f"  |  Divergence: {result['divergence']}"
              f"  |  Squeeze: {'🔥' if result.get('squeeze_fire') else '—'}")

        if result.get("owned"):
            print(f"  OWNED @ {result['entry_price']:.2f}  |  P&L: {result['pnl_pct']:+.1f}%"
                  f"  |  R: {result.get('r_multiple', 0):+.1f}"
                  f"  |  SL Phase: {result.get('sl_phase', 'N/A')}")
            print(f"  Trailing Stop: {result.get('trailing_stop', 0):.2f}"
                  f"  |  Lots: {result.get('lots_remaining', '?')}/{SCALING_LOTS}")

        if result.get("breakout"):
            if result.get("owned"):
                print(f"  \U0001F680 BREAKOUT ACTIVE  |  Level: {result.get('breakout_level', 0):.2f}"
                      f"  |  SL tightened to: {result.get('breakout_sl', 0):.2f}")
            else:
                print(f"  \u26A1 BREAKOUT  |  20-day High: {result.get('breakout_level', 0):.2f}"
                      f"  |  +{result.get('pct_above_breakout', 0):.1f}% above")

        print(f"\n  >> {action.upper()}  (Confidence: {conf})")
        for reason in rec["reasons"]:
            print(f"     - {reason}")
        for note in rec["risk_notes"]:
            print(f"     * {note}")

    # ------------------------------------------------------------------
    # v3: Multi-Stock Ranking
    # ------------------------------------------------------------------

    def _print_ranked_summary(self, results: list[dict]):
        """Print end-of-cycle summary with ranked BUY signals."""
        valid = [r for r in results if "error" not in r]
        buys = [r for r in valid if r["recommendation"]["action"].startswith("BUY")]
        sells = [r for r in valid if "SELL" in r["recommendation"]["action"]]
        avoids = [r for r in valid if r["recommendation"]["action"] == "AVOID"]
        watchlist = [r for r in valid if r["recommendation"]["action"] == "WATCHLIST"]

        print(f"\n  {'='*55}")
        print(f"  SUMMARY: {len(valid)} stocks  |  Regime: {self._regime}"
              f"{'  ⚠️ DEFENSE' if self._defense_mode else ''}")

        if buys:
            # --- v3: Rank BUYs by composite score ---
            ranked_buys = sorted(
                buys,
                key=lambda r: r["mtf_score"] * r["entry_quality"] / 100.0,
                reverse=True,
            )

            print(f"\n  🟢 BUY (Ranked by priority):")
            total_capital = self.account_value
            alloc_pcts = [0.40, 0.35, 0.25]  # Top 3 allocation

            for i, r in enumerate(ranked_buys[:3]):
                composite = r["mtf_score"] * r["entry_quality"] / 100.0
                alloc = alloc_pcts[i] if i < len(alloc_pcts) else 0
                alloc_amount = total_capital * alloc
                print(f"     #{i+1} {r['symbol']} "
                      f"(MTF: {r['mtf_score']:.2f}, "
                      f"Quality: {r['entry_quality']}, "
                      f"Composite: {composite:.3f}) "
                      f"→ Alloc: {alloc*100:.0f}% (₹{alloc_amount:,.0f})")

            if len(ranked_buys) > 3:
                remaining = ", ".join(r["symbol"] for r in ranked_buys[3:])
                print(f"     Also positive: {remaining}")

        if sells:
            sell_syms = ", ".join(r["symbol"] for r in sells)
            print(f"  🔴 SELL:      {sell_syms}")
        if avoids:
            avoid_syms = ", ".join(r["symbol"] for r in avoids)
            print(f"  ⚫ AVOID:     {avoid_syms}")
        if watchlist:
            watch_syms = ", ".join(r["symbol"] for r in watchlist)
            print(f"  👀 WATCHLIST: {watch_syms}")

        holds = len(valid) - len(buys) - len(sells) - len(avoids) - len(watchlist)
        if holds > 0:
            print(f"  \u23F8\uFE0F  HOLD/WAIT: {holds} stocks")

        # --- v4: Breakout summary ---
        breakouts = [r for r in valid if r.get("breakout")]
        if breakouts:
            bo_parts = []
            for r in breakouts:
                tag = r["symbol"]
                if r.get("owned"):
                    tag += f" (SL: {r.get('breakout_sl', r.get('trailing_stop', 0)):.2f})"
                else:
                    tag += f" (+{r.get('pct_above_breakout', 0):.1f}%)"
                bo_parts.append(tag)
            print(f"  \n  \U0001F680 BREAKOUTS: {', '.join(bo_parts)}")

        # Daily PnL summary
        if self._daily_pnl != 0:
            pnl_icon = "📈" if self._daily_pnl > 0 else "📉"
            print(f"\n  {pnl_icon} Daily P&L: {self._daily_pnl:+.1f}%")

        next_time = datetime.now().timestamp() + self.interval
        next_str = datetime.fromtimestamp(next_time).strftime("%H:%M:%S")
        print(f"\n  Next scan at: {next_str}")
        print(f"  {'='*55}")
