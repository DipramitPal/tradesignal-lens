"""
Live stock monitoring engine with quant-driven trading signals.

Fetches data at configurable intervals, tracks portfolio state (positions),
and outputs plain-English recommendations:
  - Should I BUY this stock?
  - If I already own it, where is my stop-loss?
  - Should I SELL, HOLD, or tighten my stop-loss?

Designed for users who may not have deep trading knowledge.
"""

import os
import sys
import time
import signal as os_signal
from datetime import datetime
from typing import Optional

import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import MONITOR_INTERVAL_MINUTES, MONITOR_SYMBOLS
from feature_engineering import add_technical_indicators
from signal_generator import generate_signals, compute_stop_loss, compute_trailing_stop


class Position:
    """Tracks a single stock position (bought/not bought)."""

    def __init__(self, symbol: str, entry_price: float, entry_date: str):
        self.symbol = symbol
        self.entry_price = entry_price
        self.entry_date = entry_date
        self.highest_since_entry = entry_price
        self.stop_loss = 0.0
        self.trailing_stop = 0.0

    def update(self, current_price: float, atr: float):
        """Update position tracking with latest price."""
        self.highest_since_entry = max(self.highest_since_entry, current_price)
        self.stop_loss = compute_stop_loss(current_price, atr)
        self.trailing_stop = compute_trailing_stop(
            current_price, self.highest_since_entry, atr
        )

    @property
    def pnl_pct(self):
        return 0.0  # can't compute without current price

    def pnl_at(self, current_price: float) -> float:
        return round(((current_price - self.entry_price) / self.entry_price) * 100, 2)


class LiveMonitor:
    """
    Monitors a list of stocks at regular intervals and provides
    actionable trading advice in plain English.
    """

    def __init__(
        self,
        symbols: list[str] | None = None,
        interval_minutes: int | None = None,
    ):
        self.symbols = symbols or MONITOR_SYMBOLS
        self.interval = (interval_minutes or MONITOR_INTERVAL_MINUTES) * 60  # seconds
        self.positions: dict[str, Position] = {}  # symbol -> Position
        self.running = False
        self._cycle_count = 0

    def add_position(self, symbol: str, entry_price: float, entry_date: str = ""):
        """Mark a stock as already bought at a given price."""
        if not entry_date:
            entry_date = datetime.now().strftime("%Y-%m-%d")
        self.positions[symbol] = Position(symbol, entry_price, entry_date)
        print(f"  Position added: {symbol} @ {entry_price} on {entry_date}")

    def remove_position(self, symbol: str):
        """Remove a position (after selling)."""
        if symbol in self.positions:
            del self.positions[symbol]

    def start(self):
        """Start the monitoring loop. Runs until Ctrl+C."""
        self.running = True

        def shutdown(signum, frame):
            print("\n\nStopping monitor...")
            self.running = False

        os_signal.signal(os_signal.SIGINT, shutdown)
        os_signal.signal(os_signal.SIGTERM, shutdown)

        print(f"\n{'='*70}")
        print(f"  LIVE STOCK MONITOR")
        print(f"  Watching: {', '.join(self.symbols)}")
        print(f"  Refresh interval: {self.interval // 60} minutes")
        print(f"  Press Ctrl+C to stop")
        print(f"{'='*70}\n")

        # Run immediately, then on interval
        self._run_cycle()

        while self.running:
            next_run = datetime.now().timestamp() + self.interval
            while self.running and datetime.now().timestamp() < next_run:
                time.sleep(1)
            if self.running:
                self._run_cycle()

    def run_once(self) -> list[dict]:
        """Run a single monitoring cycle and return results (no loop)."""
        return self._run_cycle()

    def _run_cycle(self) -> list[dict]:
        """Execute one full monitoring cycle for all symbols."""
        self._cycle_count += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        print(f"\n{'─'*70}")
        print(f"  Scan #{self._cycle_count} at {now}")
        print(f"{'─'*70}")

        results = []
        for symbol in self.symbols:
            try:
                result = self._analyze_symbol(symbol)
                results.append(result)
                self._print_recommendation(result)
            except Exception as e:
                print(f"\n  [{symbol}] Error: {e}")
                results.append({"symbol": symbol, "error": str(e)})

        self._print_summary(results)
        return results

    def _analyze_symbol(self, symbol: str) -> dict:
        """Analyze a single stock and produce a recommendation."""
        # Fetch 6 months of daily data for indicator calculation
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="6mo", auto_adjust=True)

        if df.empty:
            return {"symbol": symbol, "error": "No data available"}

        df.columns = [c.lower() for c in df.columns]
        df.index.name = "date"
        keep = ["open", "high", "low", "close", "volume"]
        df = df[[c for c in keep if c in df.columns]]

        # Add technical indicators
        df_tech = add_technical_indicators(df.copy())

        # Generate signals
        df_signals = generate_signals(df_tech.copy())

        latest = df_signals.iloc[-1]
        prev = df_signals.iloc[-2] if len(df_signals) > 1 else latest

        current_price = float(latest["close"])
        atr = float(latest.get("atr", current_price * 0.02))
        rsi = float(latest.get("rsi", 50))
        macd = float(latest.get("macd", 0))
        macd_signal_val = float(latest.get("macd_signal", 0))
        macd_hist = float(latest.get("macd_hist", 0))
        adx = float(latest.get("adx", 0))
        supertrend_dir = float(latest.get("supertrend_direction", 0))
        signal_text = str(latest.get("Signal", "Hold"))
        signal_strength = float(latest.get("signal_strength", 0))
        stop_loss_price = float(latest.get("stop_loss", current_price * 0.95))
        support = float(latest.get("support", 0))
        resistance = float(latest.get("resistance", 0))
        vwap = float(latest.get("vwap", current_price))
        ema_50 = float(latest.get("ema_50", 0))
        ema_200 = float(latest.get("ema_200", 0))

        # Price change
        prev_close = float(prev["close"])
        day_change_pct = round(((current_price - prev_close) / prev_close) * 100, 2)

        # Determine if stock is in uptrend
        in_uptrend = (
            supertrend_dir == 1
            and ema_50 > ema_200
            and current_price > ema_50
        )
        in_downtrend = (
            supertrend_dir == -1
            and ema_50 < ema_200
            and current_price < ema_50
        )

        # Momentum assessment
        momentum_score = self._assess_momentum(latest, prev)

        # Build recommendation
        owned = symbol in self.positions
        recommendation = self._build_recommendation(
            symbol=symbol,
            price=current_price,
            rsi=rsi,
            macd_hist=macd_hist,
            adx=adx,
            signal_text=signal_text,
            signal_strength=signal_strength,
            in_uptrend=in_uptrend,
            in_downtrend=in_downtrend,
            momentum_score=momentum_score,
            stop_loss=stop_loss_price,
            atr=atr,
            support=support,
            resistance=resistance,
            owned=owned,
        )

        # Update position tracking if owned
        if owned:
            self.positions[symbol].update(current_price, atr)

        result = {
            "symbol": symbol,
            "price": current_price,
            "day_change_pct": day_change_pct,
            "rsi": round(rsi, 1),
            "macd_hist": round(macd_hist, 4),
            "adx": round(adx, 1),
            "supertrend": "Bullish" if supertrend_dir == 1 else "Bearish",
            "trend": "UP" if in_uptrend else ("DOWN" if in_downtrend else "SIDEWAYS"),
            "signal": signal_text,
            "signal_strength": round(signal_strength, 2),
            "stop_loss": round(stop_loss_price, 2),
            "support": round(support, 2),
            "resistance": round(resistance, 2),
            "vwap": round(vwap, 2),
            "momentum_score": momentum_score,
            "owned": owned,
            "recommendation": recommendation,
        }

        if owned:
            pos = self.positions[symbol]
            result["entry_price"] = pos.entry_price
            result["pnl_pct"] = pos.pnl_at(current_price)
            result["trailing_stop"] = pos.trailing_stop
            result["highest_since_entry"] = pos.highest_since_entry

        return result

    def _assess_momentum(self, latest: pd.Series, prev: pd.Series) -> str:
        """Assess overall momentum: STRONG_BULLISH, BULLISH, NEUTRAL, BEARISH, STRONG_BEARISH."""
        score = 0

        # RSI direction
        rsi = float(latest.get("rsi", 50))
        if rsi > 60:
            score += 1
        elif rsi < 40:
            score -= 1

        # MACD histogram growing
        hist = float(latest.get("macd_hist", 0))
        prev_hist = float(prev.get("macd_hist", 0))
        if hist > prev_hist and hist > 0:
            score += 1
        elif hist < prev_hist and hist < 0:
            score -= 1

        # Price vs VWAP
        price = float(latest["close"])
        vwap = float(latest.get("vwap", price))
        if price > vwap:
            score += 1
        elif price < vwap:
            score -= 1

        # Supertrend
        if float(latest.get("supertrend_direction", 0)) == 1:
            score += 1
        else:
            score -= 1

        if score >= 3:
            return "STRONG_BULLISH"
        elif score >= 1:
            return "BULLISH"
        elif score <= -3:
            return "STRONG_BEARISH"
        elif score <= -1:
            return "BEARISH"
        return "NEUTRAL"

    def _build_recommendation(
        self,
        symbol: str,
        price: float,
        rsi: float,
        macd_hist: float,
        adx: float,
        signal_text: str,
        signal_strength: float,
        in_uptrend: bool,
        in_downtrend: bool,
        momentum_score: str,
        stop_loss: float,
        atr: float,
        support: float,
        resistance: float,
        owned: bool,
    ) -> dict:
        """Build a plain-English recommendation for the user."""
        action = "HOLD"
        confidence = "MEDIUM"
        reasons = []
        risk_notes = []

        if owned:
            pos = self.positions[symbol]
            pnl = pos.pnl_at(price)

            # Check if stop-loss is hit
            if price <= pos.trailing_stop and pos.trailing_stop > 0:
                action = "SELL NOW"
                confidence = "HIGH"
                reasons.append(
                    f"Price has dropped to your trailing stop-loss level ({pos.trailing_stop:.2f})"
                )
                reasons.append("Protect your capital — exit this position")

            # Check if massive drawdown
            elif pnl < -8:
                action = "SELL (Cut Loss)"
                confidence = "HIGH"
                reasons.append(
                    f"You are down {pnl:.1f}% — this is beyond normal pullback range"
                )
                reasons.append("Consider exiting to preserve capital")

            # Check if momentum has reversed hard
            elif in_downtrend and momentum_score in ("STRONG_BEARISH", "BEARISH"):
                action = "SELL"
                confidence = "MEDIUM"
                reasons.append("The stock has shifted into a downtrend")
                reasons.append("Momentum indicators are turning negative")
                if pnl > 0:
                    reasons.append(f"You still have a {pnl:.1f}% profit — lock it in")

            # Profitable and RSI overbought — take profits
            elif pnl > 10 and rsi > 70:
                action = "SELL (Book Profit)"
                confidence = "MEDIUM"
                reasons.append(
                    f"You are up {pnl:.1f}% and RSI is overbought ({rsi:.0f})"
                )
                reasons.append("Consider booking partial or full profit")

            # Doing well — hold and update stop-loss
            elif in_uptrend or momentum_score in ("STRONG_BULLISH", "BULLISH"):
                action = "HOLD"
                confidence = "HIGH"
                reasons.append("The stock is in an uptrend — let your winner run")
                reasons.append(
                    f"Your trailing stop-loss is at {pos.trailing_stop:.2f} "
                    f"(protecting a {pnl:.1f}% {'gain' if pnl > 0 else 'position'})"
                )

            else:
                action = "HOLD"
                confidence = "LOW"
                reasons.append("No strong signal to sell yet")
                reasons.append(f"Watch stop-loss at {pos.trailing_stop:.2f}")

            risk_notes.append(f"Entry: {pos.entry_price:.2f} | Current P&L: {pnl:+.1f}%")
            risk_notes.append(f"Trailing stop: {pos.trailing_stop:.2f}")

        else:
            # NOT OWNED — should we buy?
            if (
                momentum_score in ("STRONG_BULLISH",)
                and in_uptrend
                and signal_strength > 0.5
                and rsi < 65
                and adx > 20
            ):
                action = "BUY"
                confidence = "HIGH"
                reasons.append("Strong bullish momentum confirmed by multiple indicators")
                reasons.append(f"Trend: UP | Supertrend: Bullish | ADX: {adx:.0f} (trending)")
                reasons.append(f"Set stop-loss at {stop_loss:.2f} (based on ATR)")

            elif (
                momentum_score in ("BULLISH",)
                and (in_uptrend or signal_strength > 0)
                and rsi < 60
            ):
                action = "BUY"
                confidence = "MEDIUM"
                reasons.append("Moderate bullish momentum detected")
                if "Buy" in signal_text:
                    reasons.append(f"Signal: {signal_text}")
                reasons.append(f"Set stop-loss at {stop_loss:.2f} if you enter")

            elif rsi < 30 and support > 0 and (price - support) / price < 0.03:
                action = "BUY (Oversold Near Support)"
                confidence = "MEDIUM"
                reasons.append(
                    f"RSI is deeply oversold ({rsi:.0f}) and price is near support ({support:.2f})"
                )
                reasons.append("This could be a reversal opportunity")
                reasons.append(f"Tight stop-loss at {support * 0.98:.2f} (below support)")

            elif in_downtrend or momentum_score in ("STRONG_BEARISH", "BEARISH"):
                action = "AVOID"
                confidence = "HIGH"
                reasons.append("Stock is in a downtrend — not a good time to enter")
                if rsi > 70:
                    reasons.append(f"RSI is overbought ({rsi:.0f})")
                reasons.append("Wait for trend reversal before considering a buy")

            elif rsi > 70:
                action = "AVOID (Overbought)"
                confidence = "MEDIUM"
                reasons.append(f"RSI is at {rsi:.0f} — stock is overbought")
                reasons.append("Buying at these levels carries high risk of a pullback")

            else:
                action = "WAIT"
                confidence = "LOW"
                reasons.append("No clear signal — the stock is in a sideways range")
                reasons.append("Wait for a breakout or pullback to support before entering")

            risk_notes.append(f"Stop-loss (if buying): {stop_loss:.2f}")
            if support > 0:
                risk_notes.append(f"Support: {support:.2f} | Resistance: {resistance:.2f}")

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

        # Color-code action in text
        action_display = action.upper()

        print(f"\n  {sym}")
        print(f"  {'─'*50}")
        print(f"  Price: {price:.2f}  ({change_icon}{change:.2f}% today)")
        print(f"  Trend: {result['trend']}  |  Momentum: {result['momentum_score']}")
        print(f"  RSI: {result['rsi']}  |  ADX: {result['adx']}  |  Supertrend: {result['supertrend']}")

        if result.get("owned"):
            pos_info = f"  OWNED @ {result['entry_price']:.2f}  |  P&L: {result['pnl_pct']:+.1f}%"
            print(pos_info)
            print(f"  Trailing Stop: {result['trailing_stop']:.2f}")

        print(f"\n  >> {action_display}  (Confidence: {conf})")
        for reason in rec["reasons"]:
            print(f"     - {reason}")
        for note in rec["risk_notes"]:
            print(f"     * {note}")

    def _print_summary(self, results: list[dict]):
        """Print end-of-cycle summary."""
        valid = [r for r in results if "error" not in r]
        buys = [r for r in valid if r["recommendation"]["action"].startswith("BUY")]
        sells = [r for r in valid if "SELL" in r["recommendation"]["action"]]
        avoids = [r for r in valid if r["recommendation"]["action"].startswith("AVOID")]

        print(f"\n  {'='*50}")
        print(f"  SUMMARY: {len(valid)} stocks scanned")

        if buys:
            buy_syms = ", ".join(r["symbol"] for r in buys)
            print(f"  BUY signals:  {buy_syms}")
        if sells:
            sell_syms = ", ".join(r["symbol"] for r in sells)
            print(f"  SELL signals: {sell_syms}")
        if avoids:
            avoid_syms = ", ".join(r["symbol"] for r in avoids)
            print(f"  AVOID:        {avoid_syms}")

        holds = len(valid) - len(buys) - len(sells) - len(avoids)
        if holds > 0:
            print(f"  HOLD/WAIT:    {holds} stocks")

        next_time = datetime.now().timestamp() + self.interval
        next_str = datetime.fromtimestamp(next_time).strftime("%H:%M:%S")
        print(f"\n  Next scan at: {next_str}")
        print(f"  {'='*50}")
