"""
Live stock monitoring engine v2 — Hedge-fund-grade quant scanning.

15-minute intraday candle based with multi-timeframe confluence,
divergence detection, regime classification, adaptive SL/TP,
dynamic universe scanning, and sector rotation analysis.
"""

import os
import sys
import time
import signal as os_signal
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import (
    MONITOR_INTERVAL_MINUTES, MONITOR_SYMBOLS, SCAN_INTERVAL_MINUTES,
    DEFAULT_ACCOUNT_VALUE, RISK_PER_TRADE_PCT, SYMBOL_SECTOR,
)
from feature_engineering import add_technical_indicators, compute_pivot_points
from signal_generator import (
    score_signals, compute_mtf_confluence, apply_divergence_boost,
    apply_rvol_multiplier, apply_sector_adjustment, normalize_score,
    score_to_recommendation, score_to_confidence,
    generate_signals, compute_stop_loss, compute_trailing_stop,
)
from market_data.data_cache import DataCache
from quant.regime_classifier import classify_regime, get_weight_table
from quant.divergence_detector import detect_all_divergences, summarize_divergences
from quant.risk_manager import (
    compute_initial_sl, compute_phase_sl, check_exit_triggers,
    compute_position_size, compute_entry_quality,
)
from quant.sector_analyzer import SectorAnalyzer


class Position:
    """Tracks a single stock position (bought/not bought)."""

    def __init__(self, symbol: str, entry_price: float, entry_date: str):
        self.symbol = symbol
        self.entry_price = entry_price
        self.entry_date = entry_date
        self.highest_since_entry = entry_price
        self.stop_loss = 0.0
        self.trailing_stop = 0.0
        self.phase = "INITIAL"

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


class LiveMonitor:
    """
    Monitors stocks at 15-minute intervals using an intraday + daily
    multi-timeframe pipeline with regime-adaptive signal scoring.
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
        self._universe_scanner = None

    def add_position(self, symbol: str, entry_price: float, entry_date: str = ""):
        """Mark a stock as already bought at a given price."""
        if not entry_date:
            entry_date = datetime.now().strftime("%Y-%m-%d")
        pos = Position(symbol, entry_price, entry_date)
        # Set initial SL
        pos.stop_loss = compute_initial_sl(entry_price, entry_price * 0.015)
        self.positions[symbol] = pos
        print(f"  Position added: {symbol} @ {entry_price} on {entry_date}")

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
        print(f"  LIVE STOCK MONITOR v2 — QUANT ENGINE")
        print(f"  Watching: {', '.join(self.symbols[:10])}"
              f"{'...' if len(self.symbols) > 10 else ''}")
        print(f"  Refresh interval: {self.interval // 60} minutes")
        print(f"  Account value: ₹{self.account_value:,.0f}")
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

        # Refresh intraday data
        self.cache.refresh_intraday(self.symbols)
        self.cache.refresh_daily_if_needed(self.symbols)

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
        print(f"  Market Regime: {self._regime}")

        results = []
        for symbol in self.symbols:
            try:
                result = self._analyze_symbol(symbol, weight_table)
                results.append(result)
                self._print_recommendation(result)
            except Exception as e:
                print(f"\n  [{symbol}] Error: {e}")
                results.append({"symbol": symbol, "error": str(e)})

        self._print_summary(results)
        return results

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

        return result

    def _build_recommendation(
        self, *, symbol, price, normalized_score, entry_quality,
        rsi, cmf, supertrend_dir, psar, atr, pivots, div_summary, owned,
    ) -> dict:
        """Build recommendation using the normalized MTF score."""
        action = "HOLD"
        confidence = score_to_confidence(normalized_score)
        reasons = []
        risk_notes = []

        if owned:
            pos = self.positions[symbol]
            pnl = pos.pnl_at(price)

            # Check exit triggers
            should_exit, exit_reasons = check_exit_triggers(
                rsi_15m=rsi,
                supertrend_dir_15m=supertrend_dir,
                cmf=cmf,
                parabolic_sar=psar,
                current_price=price,
                pivot_r3=pivots.get("r3", 0) if pivots else 0,
                divergence_direction=div_summary["direction"],
            )

            if price <= pos.trailing_stop and pos.trailing_stop > 0:
                action = "SELL NOW"
                confidence = "HIGH"
                reasons.append(f"Price hit trailing stop ({pos.trailing_stop:.2f})")

            elif should_exit and pnl > 0:
                action = "SELL (Book Profit)"
                confidence = "HIGH"
                reasons.extend(exit_reasons)
                reasons.append(f"P&L: +{pnl:.1f}%")

            elif should_exit and pnl < -5:
                action = "SELL (Cut Loss)"
                confidence = "HIGH"
                reasons.extend(exit_reasons)
                reasons.append(f"P&L: {pnl:.1f}%")

            elif normalized_score < -0.30:
                action = "SELL"
                confidence = "MEDIUM"
                reasons.append(f"MTF score bearish ({normalized_score:.2f})")

            elif normalized_score > 0.20:
                action = "HOLD"
                confidence = "HIGH"
                reasons.append("Trend still positive — let winner run")
                reasons.append(f"Trailing SL: {pos.trailing_stop:.2f} (Phase: {pos.phase})")

            else:
                action = "HOLD"
                confidence = "LOW"
                reasons.append(f"No strong exit signal (MTF: {normalized_score:.2f})")
                reasons.append(f"Watch SL at {pos.trailing_stop:.2f}")

            risk_notes.append(f"Entry: {pos.entry_price:.2f} | P&L: {pnl:+.1f}%")
            risk_notes.append(f"SL Phase: {pos.phase} | SL: {pos.trailing_stop:.2f}")

        else:
            # NOT OWNED — should we buy?
            rec = score_to_recommendation(normalized_score)
            sl_price = compute_initial_sl(price, atr)

            if "STRONG BUY" in rec and entry_quality >= 50:
                action = "BUY"
                confidence = "HIGH"
                reasons.append(f"Strong MTF score: {normalized_score:.2f}")
                reasons.append(f"Entry quality: {entry_quality}/100")
                if div_summary["direction"] == "BULLISH":
                    reasons.append(f"Bullish divergence confirmed ({div_summary['count']} indicators)")
                reasons.append(f"Set SL at {sl_price:.2f}")
                shares = compute_position_size(self.account_value, price, sl_price)
                risk_notes.append(f"Suggested size: {shares} shares (2% risk)")

            elif "BUY" in rec and entry_quality >= 50:
                action = "BUY"
                confidence = "MEDIUM"
                reasons.append(f"Moderate MTF score: {normalized_score:.2f}")
                reasons.append(f"Entry quality: {entry_quality}/100")
                reasons.append(f"Set SL at {sl_price:.2f}")
                shares = compute_position_size(self.account_value, price, sl_price)
                risk_notes.append(f"Suggested size: {shares} shares (2% risk)")

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
        print(f"  Regime: {result['regime']}  |  MTF Score: {result['mtf_score']:.3f}"
              f"  |  Quality: {result['entry_quality']}/100")
        print(f"  RSI: {result['rsi']}  |  ADX: {result['adx']}"
              f"  |  RVOL: {result['rvol']:.1f}x  |  CMF: {result['cmf']:.3f}")
        print(f"  Supertrend: {result['supertrend']}"
              f"  |  Divergence: {result['divergence']}"
              f"  |  Squeeze: {'🔥' if result.get('squeeze_fire') else '—'}")

        if result.get("owned"):
            print(f"  OWNED @ {result['entry_price']:.2f}  |  P&L: {result['pnl_pct']:+.1f}%"
                  f"  |  SL Phase: {result.get('sl_phase', 'N/A')}")
            print(f"  Trailing Stop: {result.get('trailing_stop', 0):.2f}")

        print(f"\n  >> {action.upper()}  (Confidence: {conf})")
        for reason in rec["reasons"]:
            print(f"     - {reason}")
        for note in rec["risk_notes"]:
            print(f"     * {note}")

    def _print_summary(self, results: list[dict]):
        """Print end-of-cycle summary."""
        valid = [r for r in results if "error" not in r]
        buys = [r for r in valid if r["recommendation"]["action"].startswith("BUY")]
        sells = [r for r in valid if "SELL" in r["recommendation"]["action"]]
        avoids = [r for r in valid if r["recommendation"]["action"] == "AVOID"]
        watchlist = [r for r in valid if r["recommendation"]["action"] == "WATCHLIST"]

        print(f"\n  {'='*55}")
        print(f"  SUMMARY: {len(valid)} stocks  |  Regime: {self._regime}")

        if buys:
            buy_syms = ", ".join(
                f"{r['symbol']}({r['mtf_score']:.2f})" for r in buys
            )
            print(f"  🟢 BUY:       {buy_syms}")
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
            print(f"  ⏸️  HOLD/WAIT: {holds} stocks")

        next_time = datetime.now().timestamp() + self.interval
        next_str = datetime.fromtimestamp(next_time).strftime("%H:%M:%S")
        print(f"\n  Next scan at: {next_str}")
        print(f"  {'='*55}")
