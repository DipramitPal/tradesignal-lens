"""
Swing Signal Runner — End-of-Day Position Trading Engine (Phase 1).

Runs entirely on DAILY candles (no intraday dependency).
Designed for position trades held days-to-weeks, not intraday scalps.

Outputs per scan:
  - BUY watchlist  : ranked candidates with entry, SL, T1/T2/T3 targets
  - HOLD updates   : updated dynamic SL for each held position (phase-aware)
  - SELL alerts    : positions where SL hit / setup broke / rank dropped
  - JSON report    : saved to data/reports/swing_signals_YYYYMMDD.json
  - Console report : human-readable summary

Usage
-----
    # On-demand (any time — uses latest daily close):
    python -m quant.swing_signal_runner

    # From code:
    runner = SwingSignalRunner(held_positions=portfolio_dict)
    report = runner.run()
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from feature_engineering import add_technical_indicators
from quant.swing_engine import classify_swing_setup
from quant.swing_ranker import compute_swing_rank
from quant.risk_manager import (
    compute_position_size,
    compute_swing_phase_sl,
    compute_swing_targets,
    compute_swing_exit_score,
    get_regime_risk_pct,
    check_rr_gate,
)
from quant.regime_classifier import classify_regime, get_weight_table
from quant.divergence_detector import detect_all_divergences, summarize_divergences
from quant.sector_analyzer import SectorAnalyzer
from settings import (
    SCAN_UNIVERSE,
    DEFAULT_ACCOUNT_VALUE,
    RISK_PER_TRADE_PCT,
    MIN_RR_RATIO,
    REPORTS_DIR,
    SYMBOL_SECTOR,
)

try:
    from portfolio.portfolio_manager import PortfolioManager as _PortfolioManager
    _PM_AVAILABLE = True
except Exception:
    _PM_AVAILABLE = False
    _PortfolioManager = None


# ------------------------------------------------------------------
# Data structures
# ------------------------------------------------------------------

@dataclass
class HeldPosition:
    """A currently held position passed in by the caller."""
    symbol: str
    entry_price: float
    shares: int
    stop_loss: float              # current SL
    entry_date: str = ""
    highest_since_entry: float = 0.0  # updated by runner each day
    sl_phase: str = "INITIAL"
    t1: float = 0.0
    t2: float = 0.0
    t3: float = 0.0


@dataclass
class BuySignal:
    symbol: str
    rank_score: float
    rank_bucket: str
    setup_type: str
    setup_quality: int
    price: float
    entry_sl: float
    t1: float
    t2: float
    t3: float
    risk_per_share: float
    suggested_shares: int
    rr_ratio: float
    regime_risk_pct: float
    sector: str
    reasons: list[str] = field(default_factory=list)
    rank_components: dict = field(default_factory=dict)


@dataclass
class HoldUpdate:
    symbol: str
    price: float
    entry_price: float
    current_sl: float
    new_sl: float
    sl_phase: str
    pnl_pct: float
    r_multiple: float
    t1: float
    t2: float
    t3: float
    t1_hit: bool
    t2_hit: bool
    sector_multiplier: float
    alert: str = ""   # "BOOK_T1", "BOOK_T2", "TIGHTEN_SL", ""


@dataclass
class SellAlert:
    symbol: str
    price: float
    entry_price: float
    pnl_pct: float
    reason: str
    urgency: str   # "IMMEDIATE", "REVIEW"
    exit_score: float
    exit_reasons: list[str] = field(default_factory=list)


@dataclass
class SwingReport:
    generated_at: str
    market_regime: str
    buy_signals: list[BuySignal] = field(default_factory=list)
    hold_updates: list[HoldUpdate] = field(default_factory=list)
    sell_alerts: list[SellAlert] = field(default_factory=list)
    universe_scanned: int = 0
    candidates_passed_filter: int = 0
    sector_summary: dict = field(default_factory=dict)


# ------------------------------------------------------------------
# Runner
# ------------------------------------------------------------------

class SwingSignalRunner:
    """
    Daily swing signal engine for position trading.

    Parameters
    ----------
    universe       : list of symbols to scan for BUY signals
    held_positions : dict of {symbol: HeldPosition} already in the portfolio
    account_value  : total account value for position sizing
    max_positions  : max concurrent swing positions
    min_rank       : minimum swing rank score to qualify as BUY
    benchmark_sym  : benchmark for relative-strength computation
    """

    def __init__(
        self,
        universe: list[str] | None = None,
        held_positions: dict[str, HeldPosition] | None = None,
        account_value: float = DEFAULT_ACCOUNT_VALUE,
        max_positions: int = 5,
        min_rank: float = 55.0,
        benchmark_sym: str = "^NSEI",
        portfolio_manager=None,
    ):
        self.universe = universe or SCAN_UNIVERSE
        self.held: dict[str, HeldPosition] = held_positions or {}
        self.account_value = account_value
        self.max_positions = max_positions
        self.min_rank = min_rank
        self.benchmark_sym = benchmark_sym

        # Optional portfolio manager for SL persistence (G4)
        self._portfolio = portfolio_manager

        self.sector_analyzer = SectorAnalyzer()
        self._data: dict[str, pd.DataFrame] = {}
        self._benchmark_df: pd.DataFrame | None = None
        self._regime: str = "RANGE_BOUND"

    # ----------------------------------------------------------
    # Public API
    # ----------------------------------------------------------

    def run(self, preloaded: dict[str, pd.DataFrame] | None = None) -> SwingReport:
        """
        Execute one full EOD scan and return a SwingReport.

        Pass *preloaded* (symbol → daily DataFrame) to skip yfinance calls.
        """
        print("\n" + "=" * 65)
        print("  SWING SIGNAL RUNNER — EOD Position Trading Scan")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 65)

        self._load_data(preloaded)
        self._classify_regime()
        self._update_sector_phases()

        report = SwingReport(
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            market_regime=self._regime,
            universe_scanned=len(self._data),
            sector_summary=self.sector_analyzer.get_sector_summary(),
        )

        # 1. Process held positions (HOLD/SELL analysis)
        for symbol, pos in list(self.held.items()):
            df = self._data.get(symbol)
            if df is None or df.empty:
                continue
            result = self._analyze_held(symbol, pos, df)
            if isinstance(result, SellAlert):
                report.sell_alerts.append(result)
            else:
                report.hold_updates.append(result)

        # 2. Scan universe for BUY candidates
        open_slots = self.max_positions - len(self.held)
        candidates = self._scan_universe()
        report.candidates_passed_filter = len(candidates)

        for c in candidates[:open_slots]:
            report.buy_signals.append(c)

        # 3. Save and print
        self._save_report(report)
        self._print_report(report)

        return report

    # ----------------------------------------------------------
    # Data loading
    # ----------------------------------------------------------

    def _load_data(self, preloaded: dict[str, pd.DataFrame] | None):
        if preloaded is not None:
            self._data = {}
            for sym, df in preloaded.items():
                prepared = self._prepare(df)
                if prepared is not None:
                    self._data[sym] = prepared
            return

        all_syms = list(set(self.universe) | set(self.held.keys()))
        print(f"\n  Loading daily data for {len(all_syms)} symbols …")

        for sym in all_syms:
            try:
                yf_sym = sym if (sym.endswith(".NS") or sym.endswith(".BO")) else f"{sym}.NS"
                df = yf.Ticker(yf_sym).history(period="2y", auto_adjust=True)
                if df.empty or len(df) < 60:
                    continue
                df.columns = [c.lower() for c in df.columns]
                df.index = df.index.tz_localize(None)
                prepared = self._prepare(df)
                if prepared is not None:
                    self._data[sym] = prepared
            except Exception as e:
                print(f"    skip {sym}: {e}")

        # Benchmark for RS ratio
        if self.benchmark_sym:
            try:
                bdf = yf.Ticker(self.benchmark_sym).history(period="2y", auto_adjust=True)
                if not bdf.empty:
                    bdf.columns = [c.lower() for c in bdf.columns]
                    bdf.index = bdf.index.tz_localize(None)
                    self._benchmark_df = bdf
            except Exception:
                pass

        print(f"  Loaded {len(self._data)} symbols with indicators.")

    def _prepare(self, df: pd.DataFrame) -> pd.DataFrame | None:
        df = df.copy()
        df.columns = [str(c).lower() for c in df.columns]
        if not {"open", "high", "low", "close", "volume"}.issubset(df.columns):
            return None
        if len(df) < 60:
            return None
        try:
            df = add_technical_indicators(df)
        except Exception:
            return None
        vol_avg = df["volume"].rolling(20).mean()
        df["rvol"] = df["volume"] / (vol_avg + 1e-10)
        df["swing_low_20d"] = df["low"].rolling(20).min()
        return df

    # ----------------------------------------------------------
    # Regime & sector
    # ----------------------------------------------------------

    def _classify_regime(self):
        for sym, df in self._data.items():
            if len(df) >= 50:
                try:
                    self._regime = classify_regime(df, self._regime)
                    break
                except Exception:
                    pass
        print(f"  Market Regime: {self._regime}")

    def _update_sector_phases(self):
        if self._benchmark_df is not None:
            try:
                self.sector_analyzer.update_sector_phases(self._data, self._benchmark_df)
            except Exception:
                pass

    # ----------------------------------------------------------
    # Held-position analysis → HOLD update or SELL alert
    # ----------------------------------------------------------

    def _analyze_held(
        self, symbol: str, pos: HeldPosition, df: pd.DataFrame
    ) -> HoldUpdate | SellAlert:
        latest = df.iloc[-1]
        price = float(latest["close"])
        atr_daily = float(latest.get("atr", price * 0.02))
        rsi = float(latest.get("rsi", 50))
        cmf = float(latest.get("cmf", 0))
        st_dir = float(latest.get("supertrend_direction", 1))
        psar = float(latest.get("psar", 0))
        swing_low = float(latest.get("swing_low_20d", 0))

        # Update highest-since-entry
        if pos.highest_since_entry <= 0:
            pos.highest_since_entry = price
        pos.highest_since_entry = max(pos.highest_since_entry, price)

        sector_mult = self.sector_analyzer.get_sector_multiplier(symbol)

        # --- Re-rank ---
        setup = classify_swing_setup(df, current_price=price, rvol=float(latest.get("rvol", 1.0)))
        rs_ratio = self._rs_ratio(df)
        rank = compute_swing_rank(
            df, price=price, swing_setup=setup.as_dict(),
            mtf_score=self._proxy_mtf(latest, price),
            entry_quality=60,
            rvol=float(latest.get("rvol", 1.0)),
            sector_multiplier=sector_mult,
            rs_ratio=rs_ratio,
        )
        rank_score = rank["score"]

        # --- Divergence ---
        divs = detect_all_divergences(df, lookback=50)
        div_summary = summarize_divergences(divs)

        # --- Daily-timeframe exit score (G3 fix) ---
        should_exit, exit_score, exit_reasons = compute_swing_exit_score(
            rsi_daily=rsi,
            supertrend_dir_daily=st_dir,
            cmf_daily=cmf,
            psar_daily=psar,
            current_price=price,
            divergence_direction=div_summary["direction"],
            swing_rank_score=rank_score,
            min_swing_rank=self.min_rank,
        )

        # --- Hard SL breach ---
        if price <= pos.stop_loss and pos.stop_loss > 0:
            pnl_pct = round((price - pos.entry_price) / pos.entry_price * 100, 2)
            return SellAlert(
                symbol=symbol, price=price, entry_price=pos.entry_price,
                pnl_pct=pnl_pct, reason="STOP_LOSS_HIT",
                urgency="IMMEDIATE", exit_score=1.0,
                exit_reasons=[f"Price {price:.2f} ≤ SL {pos.stop_loss:.2f}"],
            )

        # --- Setup / structure break ---
        if setup.setup_type == "NO_SETUP" and rank_score < 30:
            pnl_pct = round((price - pos.entry_price) / pos.entry_price * 100, 2)
            return SellAlert(
                symbol=symbol, price=price, entry_price=pos.entry_price,
                pnl_pct=pnl_pct, reason="SETUP_BROKEN",
                urgency="REVIEW", exit_score=exit_score,
                exit_reasons=["No clean swing setup remains"] + exit_reasons,
            )

        # --- Weighted exit triggers ---
        if should_exit:
            pnl_pct = round((price - pos.entry_price) / pos.entry_price * 100, 2)
            urgency = "IMMEDIATE" if exit_score >= 0.80 else "REVIEW"
            return SellAlert(
                symbol=symbol, price=price, entry_price=pos.entry_price,
                pnl_pct=pnl_pct, reason="EXIT_SCORE_TRIGGERED",
                urgency=urgency, exit_score=exit_score,
                exit_reasons=exit_reasons,
            )

        # --- Dynamic SL update (G1 fix — daily ATR) ---
        new_sl, sl_phase = compute_swing_phase_sl(
            entry_price=pos.entry_price,
            current_price=price,
            highest_since_entry=pos.highest_since_entry,
            atr_daily=atr_daily,
            swing_low_20d=swing_low,
            current_sl=pos.stop_loss,
            sector_multiplier=sector_mult,
        )

        # Persist updated SL to portfolio JSON (G4 fix)
        sl_changed = new_sl > pos.stop_loss
        pos.stop_loss = new_sl
        pos.sl_phase = sl_phase
        if sl_changed and self._portfolio is not None:
            try:
                self._portfolio.update_holding(
                    symbol,
                    stop_loss=new_sl,
                    notes=f"SL auto-updated to {new_sl:.2f} ({sl_phase}) by SwingSignalRunner",
                )
                # Also persist highest_price for next run
                if symbol in self._portfolio.holdings:
                    self._portfolio.holdings[symbol]["highest_price"] = pos.highest_since_entry
                    self._portfolio.holdings[symbol]["sl_phase"] = sl_phase
                    self._portfolio._save()
            except Exception:
                pass

        # --- Targets (G5 fix) ---
        if pos.t1 <= 0:
            tgts = compute_swing_targets(pos.entry_price, new_sl, atr_daily)
            pos.t1, pos.t2, pos.t3 = tgts["t1"], tgts["t2"], tgts["t3"]

        pnl_pct = round((price - pos.entry_price) / pos.entry_price * 100, 2)
        initial_risk = pos.entry_price - pos.stop_loss
        r_mult = round((price - pos.entry_price) / initial_risk, 2) if initial_risk > 0 else 0.0

        # Alert flags
        alert = ""
        if price >= pos.t2:
            alert = "BOOK_T2"
        elif price >= pos.t1:
            alert = "BOOK_T1"
        elif sl_changed:
            alert = "TIGHTEN_SL"

        return HoldUpdate(
            symbol=symbol, price=price, entry_price=pos.entry_price,
            current_sl=pos.stop_loss, new_sl=new_sl, sl_phase=sl_phase,
            pnl_pct=pnl_pct, r_multiple=r_mult,
            t1=pos.t1, t2=pos.t2, t3=pos.t3,
            t1_hit=(price >= pos.t1), t2_hit=(price >= pos.t2),
            sector_multiplier=sector_mult, alert=alert,
        )

    # ----------------------------------------------------------
    # Universe scan → BUY candidates
    # ----------------------------------------------------------

    def _scan_universe(self) -> list[BuySignal]:
        regime_risk = get_regime_risk_pct(self._regime)
        candidates: list[BuySignal] = []

        for symbol, df in self._data.items():
            if symbol in self.held:
                continue
            if len(df) < 65:
                continue

            # Liquidity pre-filter
            if not self._liquidity_ok(df):
                continue

            latest = df.iloc[-1]
            price = float(latest["close"])
            rvol = float(latest.get("rvol", 1.0))
            atr_daily = float(latest.get("atr", price * 0.02))
            sector_mult = self.sector_analyzer.get_sector_multiplier(symbol)
            rs_ratio = self._rs_ratio(df)

            # Classify setup
            setup = classify_swing_setup(df, current_price=price, rvol=rvol)
            if not setup.actionable:
                continue

            # Rank
            rank = compute_swing_rank(
                df, price=price, swing_setup=setup.as_dict(),
                mtf_score=self._proxy_mtf(latest, price),
                entry_quality=self._entry_quality(latest, rvol),
                rvol=rvol,
                sector_multiplier=sector_mult,
                rs_ratio=rs_ratio,
            )
            if rank["score"] < self.min_rank:
                continue

            # SL and R:R gate
            sl = float(setup.stop_loss) if setup.stop_loss > 0 else price - 1.5 * atr_daily
            rr_ok, rr_ratio, rr_reason = check_rr_gate(price, sl)
            if not rr_ok:
                continue

            # Targets (G5)
            tgts = compute_swing_targets(price, sl, atr_daily)

            # Position size
            shares = compute_position_size(
                self.account_value, price, sl, risk_pct=regime_risk
            )

            candidates.append(BuySignal(
                symbol=symbol,
                rank_score=rank["score"],
                rank_bucket=rank["bucket"],
                setup_type=setup.setup_type,
                setup_quality=setup.quality_score,
                price=price,
                entry_sl=round(sl, 2),
                t1=tgts["t1"],
                t2=tgts["t2"],
                t3=tgts["t3"],
                risk_per_share=tgts["risk_per_share"],
                suggested_shares=shares,
                rr_ratio=rr_ratio,
                regime_risk_pct=regime_risk,
                sector=SYMBOL_SECTOR.get(symbol, "MISC"),
                reasons=setup.reasons,
                rank_components=rank.get("components", {}),
            ))

        # Sort best first
        candidates.sort(key=lambda c: c.rank_score, reverse=True)
        return candidates

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    def _liquidity_ok(self, df: pd.DataFrame) -> bool:
        if len(df) < 100:
            return False
        latest = df.iloc[-1]
        price = float(latest["close"])
        if price < 50 or price > 50_000:
            return False
        tail = df.tail(20)
        avg_vol = float(tail["volume"].mean())
        avg_turnover = float((tail["close"] * tail["volume"]).mean())
        return avg_vol >= 100_000 and avg_turnover >= 1_00_00_000

    def _rs_ratio(self, df: pd.DataFrame, lookback: int = 63) -> float:
        if self._benchmark_df is None or len(df) < lookback + 1:
            return 1.0
        bench = self._benchmark_df
        last_date = df.index[-1]
        bench_slice = bench[bench.index <= last_date]
        if len(bench_slice) < lookback + 1:
            return 1.0
        s_end = float(df["close"].iloc[-1])
        s_start = float(df["close"].iloc[-lookback])
        b_end = float(bench_slice["close"].iloc[-1])
        b_start = float(bench_slice["close"].iloc[-lookback])
        if s_start <= 0 or b_start <= 0:
            return 1.0
        bench_ret = b_end / b_start
        return (s_end / s_start) / bench_ret if bench_ret > 0 else 1.0

    @staticmethod
    def _proxy_mtf(latest: pd.Series, price: float) -> float:
        ema50 = float(latest.get("ema_50", price))
        macd = float(latest.get("macd", 0))
        macd_sig = float(latest.get("macd_signal", 0))
        st = float(latest.get("supertrend_direction", 0))
        return (
            (0.3 if price > ema50 else 0)
            + (0.3 if macd > macd_sig else 0)
            + (0.4 if st == 1 else 0)
        )

    @staticmethod
    def _entry_quality(latest: pd.Series, rvol: float) -> int:
        score = 30
        rsi = float(latest.get("rsi", 50))
        cmf = float(latest.get("cmf", 0))
        sq = int(float(latest.get("squeeze_fire", 0)))
        if 35 <= rsi <= 55:
            score += 20
        if cmf > 0:
            score += 20
        if rvol > 1.2:
            score += 15
        if sq:
            score += 15
        return min(100, score)

    # ----------------------------------------------------------
    # Persistence & printing
    # ----------------------------------------------------------

    def _save_report(self, report: SwingReport):
        try:
            REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            date_str = datetime.now().strftime("%Y%m%d")
            path = REPORTS_DIR / f"swing_signals_{date_str}.json"

            def _to_dict(obj):
                if isinstance(obj, (BuySignal, HoldUpdate, SellAlert, SwingReport)):
                    return asdict(obj)
                return str(obj)

            with open(path, "w") as f:
                json.dump(asdict(report), f, indent=2, default=str)
            print(f"\n  Report saved → {path}")
        except Exception as e:
            print(f"  [Warning] Could not save report: {e}")

    def _print_report(self, report: SwingReport):
        print(f"\n{'='*65}")
        print(f"  SWING SIGNAL REPORT  |  Regime: {report.market_regime}")
        print(f"  Universe: {report.universe_scanned} scanned, "
              f"{report.candidates_passed_filter} passed filter")
        print(f"{'='*65}")

        # SELL alerts
        if report.sell_alerts:
            print(f"\n  🔴 SELL ALERTS ({len(report.sell_alerts)})")
            print(f"  {'Symbol':<14} {'Price':>8} {'PnL':>7} {'Urgency':<10} Reason")
            print(f"  {'-'*60}")
            for s in report.sell_alerts:
                sign = "+" if s.pnl_pct >= 0 else ""
                print(f"  {s.symbol:<14} {s.price:>8.2f} {sign}{s.pnl_pct:>6.1f}% "
                      f"  {s.urgency:<10} {s.reason}")
                for r in s.exit_reasons[:2]:
                    print(f"    └─ {r}")

        # HOLD updates
        if report.hold_updates:
            print(f"\n  🟡 HOLD UPDATES ({len(report.hold_updates)})")
            print(f"  {'Symbol':<14} {'Price':>8} {'PnL':>7} {'R':>5} "
                  f"{'SL':>8} {'Phase':<12} {'Alert'}")
            print(f"  {'-'*70}")
            for h in report.hold_updates:
                sign = "+" if h.pnl_pct >= 0 else ""
                alert_str = f"⚡ {h.alert}" if h.alert else ""
                print(f"  {h.symbol:<14} {h.price:>8.2f} {sign}{h.pnl_pct:>6.1f}% "
                      f"  {h.r_multiple:>+4.1f}R  {h.new_sl:>8.2f}  {h.sl_phase:<12} {alert_str}")
                print(f"    └─ Targets → T1:{h.t1:.2f}  T2:{h.t2:.2f}  T3:{h.t3:.2f}")

        # BUY signals
        if report.buy_signals:
            print(f"\n  🟢 BUY SIGNALS ({len(report.buy_signals)})")
            print(f"  {'Symbol':<14} {'Score':>6} {'Setup':<14} {'Price':>8} "
                  f"{'SL':>8} {'T1':>8} {'T2':>8} {'R:R':>5}")
            print(f"  {'-'*75}")
            for b in report.buy_signals:
                print(f"  {b.symbol:<14} {b.rank_score:>6.1f}  {b.setup_type:<14} "
                      f"{b.price:>8.2f}  {b.entry_sl:>8.2f}  {b.t1:>8.2f}  "
                      f"{b.t2:>8.2f}  {b.rr_ratio:>4.1f}x")
                print(f"    └─ {b.rank_bucket} | Sector:{b.sector} | "
                      f"Shares:{b.suggested_shares} | Risk:{b.regime_risk_pct*100:.1f}%")
                for r in b.reasons[:2]:
                    print(f"       · {r}")
        else:
            print("\n  No BUY signals this scan — market conditions / rank filter not met.")

        print(f"\n{'='*65}\n")


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def _build_held_from_portfolio() -> dict[str, HeldPosition]:
    """Load held positions from the portfolio manager (if available)."""
    held: dict[str, HeldPosition] = {}
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from portfolio.portfolio_manager import PortfolioManager
        pm = PortfolioManager()
        pm._load()
        for sym, h in pm.holdings.items():
            held[sym] = HeldPosition(
                symbol=sym,
                entry_price=float(h.get("avg_price", 0)),
                shares=int(h.get("qty", 0)),
                stop_loss=float(h.get("stop_loss", 0)),
                entry_date=h.get("date", ""),
                highest_since_entry=float(h.get("highest_price", h.get("avg_price", 0))),
            )
    except Exception as e:
        print(f"  [Info] Could not load portfolio positions: {e}")
    return held


if __name__ == "__main__":
    pm = None
    if _PM_AVAILABLE:
        try:
            pm = _PortfolioManager()
        except Exception:
            pass
    held = _build_held_from_portfolio()
    runner = SwingSignalRunner(held_positions=held, portfolio_manager=pm)
    runner.run()
