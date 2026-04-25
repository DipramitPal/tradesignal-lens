"""
Portfolio Intelligence Advisor -- Personalized recommendations engine.

Provides 4 features:
  1. Smart Averaging Down / Pyramiding with safety gates & override
  2. Trailing Stop-Loss (TSL) management assistant
  3. Tax-Loss Harvesting recommendations (year-round)
  4. Weekly Portfolio Summary (last 5 trading days)

Usage (CLI):
    python main.py advisor                # all advisor output
    python main.py weekly-report          # weekly portfolio recap
    python main.py weekly-report --save   # save to data/reports/
"""

import os
import sys
import math
from datetime import datetime, timedelta
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import (
    DEFAULT_ACCOUNT_VALUE, SYMBOL_SECTOR, SECTOR_MAP, SCAN_UNIVERSE,
)
from portfolio.portfolio_manager import PortfolioManager
from market_data.data_cache import DataCache


class PortfolioAdvisor:
    """Generates personalized recommendations based on the user's portfolio."""

    def __init__(self, portfolio: Optional[PortfolioManager] = None,
                 cache: Optional[DataCache] = None):
        self.portfolio = portfolio or PortfolioManager()
        self.cache = cache or DataCache()
        self._cache_warmed = False

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _ensure_cache(self):
        """Warm cache for all portfolio symbols if not already done."""
        if self._cache_warmed:
            return
        symbols = self.portfolio.get_symbols()
        if symbols:
            # Only warm if cache is truly empty for these symbols
            missing = [s for s in symbols if self.cache.get_daily(s).empty]
            if missing:
                self.cache.warm_cache(missing, daily_period="6mo", intraday_days=2)
        self._cache_warmed = True

    def _get_live_price(self, symbol: str) -> Optional[float]:
        """Get latest price from cache, falling back to yfinance."""
        # Try intraday cache first
        idf = self.cache.get_intraday(symbol)
        if not idf.empty:
            p = self._safe_float(idf.iloc[-1]["close"])
            if p is not None:
                return p
        # Daily cache
        df = self.cache.get_daily(symbol)
        if not df.empty:
            p = self._safe_float(df.iloc[-1]["close"])
            if p is not None:
                return p
        # Fallback
        try:
            import yfinance as yf
            t = yf.Ticker(symbol)
            hist = t.history(period="2d", interval="1d", auto_adjust=True)
            if not hist.empty:
                return self._safe_float(hist.iloc[-1]["Close"])
        except Exception:
            pass
        return None

    @staticmethod
    def _safe_float(val, default=None):
        try:
            f = float(val)
            return default if (math.isnan(f) or math.isinf(f)) else f
        except (TypeError, ValueError):
            return default

    # ==================================================================
    # FEATURE 1: Smart Averaging Down / Pyramiding
    # ==================================================================

    def get_averaging_recommendations(self, force_override: bool = False) -> list[dict]:
        """
        For each holding trading below avg_price, evaluate whether
        averaging down is safe and compute exact quantities.

        Args:
            force_override: If True, include recommendations even for
                stocks in confirmed downtrends (with explicit warnings).

        Returns:
            List of recommendation dicts.
        """
        self.portfolio._load()
        self._ensure_cache()

        from feature_engineering import add_technical_indicators
        from quant.regime_classifier import classify_regime
        from quant.divergence_detector import detect_all_divergences, summarize_divergences

        results = []
        available_capital = self.portfolio.get_available_capital()

        for symbol, holding in self.portfolio.holdings.items():
            current_price = self._get_live_price(symbol)
            if current_price is None:
                continue

            avg_price = holding["avg_price"]
            qty = holding["qty"]
            invested = holding.get("invested_value", qty * avg_price)

            # Only consider stocks trading below avg price
            if current_price >= avg_price:
                continue

            loss_pct = ((current_price - avg_price) / avg_price) * 100
            df_daily = self.cache.get_daily(symbol)

            rec = {
                "symbol": symbol,
                "current_price": round(current_price, 2),
                "avg_price": avg_price,
                "qty": qty,
                "loss_pct": round(loss_pct, 2),
                "action": "HOLD",
                "safe_to_average": False,
                "blocked": False,
                "block_reasons": [],
                "warnings": [],
                "support_level": None,
                "recommended_qty": 0,
                "recommended_investment": 0,
                "new_avg_price": 0,
                "sector": holding.get("sector", "MISC"),
            }

            if df_daily.empty or len(df_daily) < 50:
                rec["block_reasons"].append("Insufficient historical data for analysis")
                rec["blocked"] = True
                results.append(rec)
                continue

            try:
                df_ind = add_technical_indicators(df_daily.copy())
                latest = df_ind.iloc[-1]

                # Regime classification
                regime = classify_regime(df_ind, "RANGE_BOUND")
                rsi = self._safe_float(latest.get("rsi", 50), 50)
                adx = self._safe_float(latest.get("adx", 0), 0)
                atr = self._safe_float(latest.get("atr", current_price * 0.02), current_price * 0.02)

                # Divergence detection
                divs = detect_all_divergences(df_ind, lookback=50)
                div_summary = summarize_divergences(divs)
                has_bullish_divergence = div_summary["direction"] == "BULLISH"

                # Support level detection
                fib_618 = self._safe_float(latest.get("fib_618", 0), 0)
                ema_200 = self._safe_float(latest.get("ema_200", 0), 0)
                sma_200 = self._safe_float(latest.get("sma_200", 0), 0)
                support_ref = ema_200 if ema_200 > 0 else sma_200

                # Find best support level
                support_levels = []
                if fib_618 > 0 and current_price <= fib_618 * 1.015:
                    support_levels.append(("Fib 0.618", fib_618))
                if support_ref > 0 and current_price <= support_ref * 1.02:
                    support_levels.append(("EMA/SMA 200", support_ref))

                # Bollinger lower band as support
                bb_low = self._safe_float(latest.get("bb_low", 0), 0)
                if bb_low > 0 and current_price <= bb_low * 1.01:
                    support_levels.append(("Bollinger Lower", bb_low))

                near_support = len(support_levels) > 0
                if support_levels:
                    best_support = min(support_levels, key=lambda x: abs(current_price - x[1]))
                    rec["support_level"] = {
                        "name": best_support[0],
                        "price": round(best_support[1], 2),
                    }

                # -- BLOCKING CHECKS --

                is_downtrend = (regime == "TRENDING_DOWN" and adx > 25)

                if is_downtrend and not force_override:
                    rec["blocked"] = True
                    rec["block_reasons"].append(
                        f"Stock in confirmed DOWNTREND (Regime: {regime}, ADX: {adx:.0f})"
                    )
                    rec["block_reasons"].append(
                        "Averaging down in downtrends destroys capital. "
                        "Wait for regime shift to RANGE_BOUND or TRENDING_UP."
                    )
                    rec["action"] = "DO NOT AVERAGE"
                    results.append(rec)
                    continue

                if is_downtrend and force_override:
                    rec["warnings"].append("[WARN] OVERRIDE ACTIVE -- AVERAGING IN A CONFIRMED DOWNTREND")
                    rec["warnings"].append(
                        f"[!!] The stock is in a TRENDING_DOWN regime with ADX={adx:.0f}. "
                        "Historically, averaging down in confirmed downtrends leads to "
                        "deeper losses 70-80% of the time."
                    )
                    rec["warnings"].append(
                        "[RISK] If the stock falls another 20%, your total loss will compound. "
                        "You are doubling down on a losing position."
                    )
                    rec["warnings"].append(
                        "[STOP] Only proceed if you have a STRONG fundamental conviction "
                        "that this is a temporary dip, NOT a structural decline."
                    )

                if loss_pct < -50 and not force_override:
                    rec["blocked"] = True
                    rec["block_reasons"].append(
                        f"Position down {loss_pct:.0f}% -- too deep to average safely"
                    )
                    rec["action"] = "DO NOT AVERAGE"
                    results.append(rec)
                    continue

                if loss_pct < -50 and force_override:
                    rec["warnings"].append(
                        f"[WARN] Position already down {loss_pct:.0f}%. "
                        "Averaging this deep is extremely high risk."
                    )

                # -- RECOMMENDATION LOGIC --

                if near_support and (rsi < 40 or has_bullish_divergence):
                    rec["safe_to_average"] = True
                    rec["action"] = "AVERAGE DOWN"

                    # Calculate recommended quantity
                    # Cap at 15% of available capital or 50% of current position value
                    max_additional_invest = min(
                        available_capital * 0.15,
                        invested * 0.5,
                    )

                    if max_additional_invest > current_price:
                        additional_qty = int(max_additional_invest / current_price)
                        additional_invest = round(additional_qty * current_price, 2)
                        new_total_qty = qty + additional_qty
                        new_avg = round((invested + additional_invest) / new_total_qty, 2)

                        rec["recommended_qty"] = additional_qty
                        rec["recommended_investment"] = additional_invest
                        rec["new_avg_price"] = new_avg
                        rec["action"] = f"BUY {additional_qty} shares @ Rs.{current_price:.2f}"

                        reasons = []
                        if near_support:
                            reasons.append(f"Price near {rec['support_level']['name']} support at Rs.{rec['support_level']['price']:.2f}")
                        if rsi < 40:
                            reasons.append(f"RSI oversold at {rsi:.0f}")
                        if has_bullish_divergence:
                            reasons.append("Bullish divergence detected")
                        rec["reasons"] = reasons
                    else:
                        rec["action"] = "HOLD"
                        rec["block_reasons"].append("Insufficient available capital")

                elif near_support:
                    rec["action"] = "WATCHLIST"
                    rec["reasons"] = ["Near support but no confirmation signal yet (need RSI < 40 or bullish divergence)"]

                else:
                    rec["action"] = "HOLD"
                    rec["reasons"] = [f"No support level nearby. RSI: {rsi:.0f}, Regime: {regime}"]

            except Exception as e:
                rec["block_reasons"].append(f"Analysis error: {str(e)}")
                rec["blocked"] = True

            results.append(rec)

        # Sort: actionable items first
        results.sort(key=lambda x: (
            0 if "BUY" in x["action"] else 1 if x["action"] == "WATCHLIST" else 2
        ))

        return results

    # ==================================================================
    # FEATURE 2: Trailing Stop-Loss Assistant
    # ==================================================================

    def get_tsl_advice(self) -> list[dict]:
        """
        For each holding, compute the current SL phase and generate
        human-readable advice on what SL action to take today.

        Returns:
            List of TSL advice dicts, one per holding.
        """
        self.portfolio._load()
        self._ensure_cache()

        from feature_engineering import add_technical_indicators
        from quant.risk_manager import compute_initial_sl, compute_phase_sl

        results = []

        for symbol, holding in self.portfolio.holdings.items():
            current_price = self._get_live_price(symbol)
            if current_price is None:
                continue

            avg_price = holding["avg_price"]
            qty = holding["qty"]
            current_sl = holding.get("stop_loss", 0)
            pnl_pct = ((current_price - avg_price) / avg_price) * 100
            pnl_abs = (current_price - avg_price) * qty

            rec = {
                "symbol": symbol,
                "current_price": round(current_price, 2),
                "avg_price": avg_price,
                "qty": qty,
                "pnl_pct": round(pnl_pct, 2),
                "pnl_abs": round(pnl_abs, 2),
                "current_sl": current_sl,
                "recommended_sl": current_sl,
                "sl_phase": "INITIAL",
                "action": "",
                "advice": "",
                "risk_per_share": 0,
                "sector": holding.get("sector", "MISC"),
            }

            df_daily = self.cache.get_daily(symbol)
            if df_daily.empty or len(df_daily) < 20:
                rec["advice"] = "Insufficient data. Set manual SL at entry - 5%."
                rec["recommended_sl"] = round(avg_price * 0.95, 2)
                results.append(rec)
                continue

            try:
                df_ind = add_technical_indicators(df_daily.copy())
                latest = df_ind.iloc[-1]

                atr = self._safe_float(latest.get("atr", current_price * 0.02), current_price * 0.02)
                psar = self._safe_float(latest.get("psar", 0), 0)

                # Compute initial SL if none set
                if current_sl <= 0:
                    current_sl = compute_initial_sl(avg_price, atr, multiplier=1.5)

                # Track highest since entry (approximate from daily data)
                highest = current_price
                if len(df_daily) > 5:
                    recent_high = df_daily["high"].tail(30).max()
                    highest = max(float(recent_high), current_price) if not math.isnan(recent_high) else current_price

                # Compute phase SL
                new_sl, phase = compute_phase_sl(
                    entry_price=avg_price,
                    current_price=current_price,
                    highest_since_entry=highest,
                    atr_15m=atr,
                    parabolic_sar=psar,
                    current_sl=current_sl,
                )

                rec["recommended_sl"] = round(new_sl, 2)
                rec["sl_phase"] = phase
                rec["risk_per_share"] = round(current_price - new_sl, 2)

                # Compute R-multiple
                initial_risk = abs(avg_price - compute_initial_sl(avg_price, atr))
                if initial_risk > 0:
                    r_multiple = (current_price - avg_price) / initial_risk
                else:
                    r_multiple = 0
                rec["r_multiple"] = round(r_multiple, 2)

                # Generate human-readable advice
                if pnl_pct < -30:
                    rec["action"] = "REVIEW"
                    rec["advice"] = (
                        f"[!] Deep loss ({pnl_pct:.1f}%). Your SL should be at Rs.{new_sl:.2f}. "
                        f"Consider if this is a tax-loss harvest candidate."
                    )
                elif pnl_pct < 0:
                    rec["action"] = "HOLD SL"
                    rec["advice"] = (
                        f"Position in loss ({pnl_pct:.1f}%). "
                        f"Keep SL at Rs.{new_sl:.2f}. "
                        f"Risk per share: Rs.{current_price - new_sl:.2f}."
                    )
                elif phase == "INITIAL":
                    rec["action"] = "HOLD SL"
                    rec["advice"] = (
                        f"Up {pnl_pct:.1f}% but not yet at 1R. "
                        f"Hold SL at Rs.{new_sl:.2f} (initial phase). "
                        f"Will move to breakeven at 1R = Rs.{avg_price + initial_risk:.2f}."
                    )
                elif phase == "BREAKEVEN":
                    rec["action"] = "MOVE SL"
                    rec["advice"] = (
                        f"[OK] At {r_multiple:.1f}R profit! Move SL to breakeven at "
                        f"Rs.{avg_price:.2f} (your entry price). "
                        f"This makes the trade RISK-FREE. "
                        f"Lock in: Rs.0 worst case, currently up Rs.{pnl_abs:.0f}."
                    )
                elif phase == "TRAILING":
                    rec["action"] = "TRAIL SL"
                    rec["advice"] = (
                        f"[>>] At {r_multiple:.1f}R profit! Trail SL using "
                        f"Parabolic SAR at Rs.{new_sl:.2f}. "
                        f"Locked-in profit per share: Rs.{new_sl - avg_price:.2f}. "
                        f"Let the winner run; trailing protects gains."
                    )

                # SL hit warning
                if current_price <= new_sl and new_sl > 0:
                    rec["action"] = "EXIT NOW"
                    rec["advice"] = (
                        f"[!] PRICE BELOW SL! Current: Rs.{current_price:.2f}, "
                        f"SL: Rs.{new_sl:.2f}. Exit immediately to limit losses."
                    )

            except Exception as e:
                rec["advice"] = f"Analysis error: {str(e)}. Use manual SL."
                rec["recommended_sl"] = round(avg_price * 0.95, 2)

            results.append(rec)

        # Sort: EXIT NOW first, then MOVE SL, TRAIL, HOLD, REVIEW
        action_order = {"EXIT NOW": 0, "MOVE SL": 1, "TRAIL SL": 2, "HOLD SL": 3, "REVIEW": 4, "": 5}
        results.sort(key=lambda x: action_order.get(x["action"], 5))

        return results

    # ==================================================================
    # FEATURE 3: Tax-Loss Harvesting (Year-Round)
    # ==================================================================

    def get_tax_harvest_recommendations(self, min_loss_pct: float = 5.0) -> list[dict]:
        """
        Scan portfolio for positions with significant unrealized losses
        and recommend selling for tax offset, with sector-similar
        replacement suggestions.

        Args:
            min_loss_pct: Minimum unrealized loss % to qualify (default 5%)

        Returns:
            List of harvest candidate dicts.
        """
        self.portfolio._load()
        self._ensure_cache()

        results = []
        now = datetime.now()

        # FY-end proximity flag (India FY ends March 31)
        fy_end = datetime(now.year, 3, 31) if now.month <= 3 else datetime(now.year + 1, 3, 31)
        days_to_fy_end = (fy_end - now).days
        near_fy_end = days_to_fy_end <= 60  # Within Feb-Mar window

        for symbol, holding in self.portfolio.holdings.items():
            current_price = self._get_live_price(symbol)
            if current_price is None:
                continue

            avg_price = holding["avg_price"]
            qty = holding["qty"]
            invested = holding.get("invested_value", qty * avg_price)
            current_val = qty * current_price
            unrealized_loss = invested - current_val
            loss_pct = ((current_price - avg_price) / avg_price) * 100

            # Only consider stocks with significant unrealized loss
            if loss_pct >= -min_loss_pct:
                continue

            sector = holding.get("sector", SYMBOL_SECTOR.get(symbol, "MISC"))

            # Find sector-similar replacement from universe
            replacement = self._find_sector_replacement(symbol, sector)

            rec = {
                "symbol": symbol,
                "current_price": round(current_price, 2),
                "avg_price": avg_price,
                "qty": qty,
                "loss_pct": round(loss_pct, 2),
                "unrealized_loss": round(unrealized_loss, 2),
                "invested_value": round(invested, 2),
                "current_value": round(current_val, 2),
                "sector": sector,
                "near_fy_end": near_fy_end,
                "days_to_fy_end": days_to_fy_end,
                "replacement": replacement,
                "advice": "",
                "priority": "HIGH" if near_fy_end else ("MEDIUM" if loss_pct < -20 else "LOW"),
            }

            # Build advice text
            if near_fy_end:
                rec["advice"] = (
                    f"[FY-END] Sell {qty} {symbol.replace('.NS', '')} to realize "
                    f"Rs.{unrealized_loss:,.0f} loss for tax offset. "
                    f"Only {days_to_fy_end} days left in this financial year."
                )
            else:
                rec["advice"] = (
                    f"Consider selling {qty} {symbol.replace('.NS', '')} to book "
                    f"Rs.{unrealized_loss:,.0f} loss. Down {loss_pct:.1f}% from entry."
                )

            if replacement:
                rec["advice"] += (
                    f" Replace with {replacement['symbol'].replace('.NS', '')} "
                    f"(Rs.{replacement['price']:.2f}) to maintain {sector} exposure."
                )

            results.append(rec)

        # Sort by absolute loss (largest first)
        results.sort(key=lambda x: x["unrealized_loss"], reverse=True)

        # Summary stats
        total_harvestable = sum(r["unrealized_loss"] for r in results)

        return {
            "candidates": results,
            "total_harvestable_loss": round(total_harvestable, 2),
            "near_fy_end": near_fy_end,
            "days_to_fy_end": days_to_fy_end,
            "candidate_count": len(results),
        }

    def _find_sector_replacement(self, exclude_symbol: str, sector: str) -> Optional[dict]:
        """Find a sector-similar stock from SCAN_UNIVERSE as a replacement."""
        sector_stocks = SECTOR_MAP.get(sector, [])
        # Filter out the stock being sold and any already in portfolio
        portfolio_symbols = set(self.portfolio.get_symbols())
        candidates = [
            s for s in sector_stocks
            if s != exclude_symbol and s not in portfolio_symbols
        ]

        if not candidates:
            return None

        # Try to get price for first available candidate
        for candidate in candidates[:5]:  # Check top 5 to avoid too many API calls
            price = self._get_live_price(candidate)
            if price is not None:
                return {
                    "symbol": candidate,
                    "price": round(price, 2),
                    "sector": sector,
                }

        return None

    # ==================================================================
    # FEATURE 4: Weekly Portfolio Summary (last 5 trading days)
    # ==================================================================

    def generate_weekly_report(self) -> dict:
        """
        Generate a comprehensive weekly portfolio performance report
        using the last 5 trading days.

        Returns:
            dict with weekly performance data, key decisions, etc.
        """
        self.portfolio._load()
        self._ensure_cache()

        holdings = self.portfolio.holdings
        if not holdings:
            return {"error": "Portfolio is empty", "holdings": []}

        # Per-stock weekly performance
        stock_perf = []
        total_invested = 0
        total_current = 0
        total_week_start = 0

        sector_perf = {}

        for symbol, holding in holdings.items():
            current_price = self._get_live_price(symbol)
            if current_price is None:
                continue

            avg_price = holding["avg_price"]
            qty = holding["qty"]
            invested = holding.get("invested_value", qty * avg_price)
            current_val = qty * current_price
            total_invested += invested
            total_current += current_val

            # Get price 5 trading days ago
            df_daily = self.cache.get_daily(symbol)
            week_start_price = current_price  # fallback
            week_high = current_price
            week_low = current_price

            if not df_daily.empty and len(df_daily) >= 5:
                # Use last 5 rows (trading days)
                recent = df_daily.tail(6)  # 6 to get the close BEFORE the 5-day window
                if len(recent) >= 6:
                    week_start_price = self._safe_float(recent.iloc[0]["close"], current_price)
                elif len(recent) >= 2:
                    week_start_price = self._safe_float(recent.iloc[0]["close"], current_price)

                last_5 = df_daily.tail(5)
                week_high = self._safe_float(last_5["high"].max(), current_price)
                week_low = self._safe_float(last_5["low"].min(), current_price)

            week_change_pct = ((current_price - week_start_price) / week_start_price) * 100 if week_start_price else 0
            week_pnl_abs = (current_price - week_start_price) * qty
            total_pnl_pct = ((current_price - avg_price) / avg_price) * 100

            total_week_start += qty * week_start_price

            sector = holding.get("sector", "MISC")
            if sector not in sector_perf:
                sector_perf[sector] = {"start_val": 0, "current_val": 0, "symbols": []}
            sector_perf[sector]["start_val"] += qty * week_start_price
            sector_perf[sector]["current_val"] += current_val
            sector_perf[sector]["symbols"].append(symbol.replace(".NS", ""))

            stock_perf.append({
                "symbol": symbol,
                "name": symbol.replace(".NS", ""),
                "qty": qty,
                "avg_price": avg_price,
                "current_price": round(current_price, 2),
                "week_start_price": round(week_start_price, 2),
                "week_change_pct": round(week_change_pct, 2),
                "week_pnl_abs": round(week_pnl_abs, 2),
                "total_pnl_pct": round(total_pnl_pct, 2),
                "week_high": round(week_high, 2),
                "week_low": round(week_low, 2),
                "sector": sector,
            })

        # Sort by weekly change
        stock_perf.sort(key=lambda x: x["week_change_pct"], reverse=True)

        top_gainers = stock_perf[:3]
        top_losers = stock_perf[-3:][::-1] if len(stock_perf) >= 3 else stock_perf[::-1]

        # Portfolio-level weekly change
        portfolio_week_change = (
            ((total_current - total_week_start) / total_week_start) * 100
            if total_week_start > 0 else 0
        )
        portfolio_total_pnl_pct = (
            ((total_current - total_invested) / total_invested) * 100
            if total_invested > 0 else 0
        )

        # Sector weekly performance
        sector_summary = []
        for sector, data in sector_perf.items():
            change = (
                ((data["current_val"] - data["start_val"]) / data["start_val"]) * 100
                if data["start_val"] > 0 else 0
            )
            sector_summary.append({
                "sector": sector,
                "week_change_pct": round(change, 2),
                "current_value": round(data["current_val"], 2),
                "stocks": data["symbols"],
            })
        sector_summary.sort(key=lambda x: x["week_change_pct"], reverse=True)

        # -- KEY DECISIONS --
        key_decisions = self._generate_key_decisions(stock_perf)

        report = {
            "generated_at": datetime.now().isoformat(),
            "period": "Last 5 Trading Days",
            "portfolio": {
                "total_invested": round(total_invested, 2),
                "total_current": round(total_current, 2),
                "total_pnl": round(total_current - total_invested, 2),
                "total_pnl_pct": round(portfolio_total_pnl_pct, 2),
                "week_change_pct": round(portfolio_week_change, 2),
                "week_pnl_abs": round(total_current - total_week_start, 2),
                "holdings_count": len(stock_perf),
            },
            "top_gainers": top_gainers,
            "top_losers": top_losers,
            "all_stocks": stock_perf,
            "sector_performance": sector_summary,
            "key_decisions": key_decisions,
        }

        return report

    def _generate_key_decisions(self, stock_perf: list[dict]) -> list[dict]:
        """Generate a list of key decisions the user should consider."""
        decisions = []

        for s in stock_perf:
            symbol_short = s["name"]

            # Stocks with big weekly losses
            if s["week_change_pct"] < -5:
                decisions.append({
                    "type": "WARNING",
                    "icon": "[!]",
                    "stock": s["symbol"],
                    "advice": (
                        f"{symbol_short} dropped {s['week_change_pct']:.1f}% this week. "
                        f"Review your stop-loss and consider if fundamentals have changed."
                    ),
                })

            # Deep overall losses -- tax harvest candidate
            if s["total_pnl_pct"] < -25:
                decisions.append({
                    "type": "HARVEST",
                    "icon": "[CUT]",
                    "stock": s["symbol"],
                    "advice": (
                        f"{symbol_short} is down {s['total_pnl_pct']:.1f}% overall. "
                        f"Consider tax-loss harvesting to offset gains."
                    ),
                })

            # Stocks with strong weekly gains -- consider booking partial
            if s["week_change_pct"] > 5:
                decisions.append({
                    "type": "PROFIT",
                    "icon": "[$]",
                    "stock": s["symbol"],
                    "advice": (
                        f"{symbol_short} rallied +{s['week_change_pct']:.1f}% this week. "
                        f"Consider tightening trailing SL or booking partial profits."
                    ),
                })

            # Overall profit target hit
            if s["total_pnl_pct"] > 20:
                decisions.append({
                    "type": "TARGET",
                    "icon": "[TGT]",
                    "stock": s["symbol"],
                    "advice": (
                        f"{symbol_short} up +{s['total_pnl_pct']:.1f}% from entry. "
                        f"Ensure trailing SL is active to protect gains."
                    ),
                })

        # Sector concentration warnings
        sector_exposure = self.portfolio.get_sector_exposure()
        total_invested = self.portfolio.get_total_invested()
        if total_invested > 0:
            for sector, value in sector_exposure.items():
                pct = (value / total_invested) * 100
                if pct > 30:
                    decisions.append({
                        "type": "CONCENTRATION",
                        "icon": "[BAL]",
                        "stock": sector,
                        "advice": (
                            f"{sector} sector at {pct:.0f}% of portfolio -- consider diversifying. "
                            f"Max recommended: 30%."
                        ),
                    })

        # Sort: WARNINGs first, then HARVEST, PROFIT, TARGET, CONCENTRATION
        type_order = {"WARNING": 0, "HARVEST": 1, "PROFIT": 2, "TARGET": 3, "CONCENTRATION": 4}
        decisions.sort(key=lambda x: type_order.get(x["type"], 5))

        return decisions

    # ==================================================================
    # CLI Formatters
    # ==================================================================

    @staticmethod
    def _print(text: str = ""):
        """Print with fallback for Windows terminals that can't render unicode."""
        try:
            print(text)
        except UnicodeEncodeError:
            # Final fallback: replace any non-ascii
            print(text.encode("ascii", "replace").decode("ascii"))

    def print_tsl_advice(self):
        """Print formatted TSL advice to console."""
        results = self.get_tsl_advice()

        self._print(f"\n{'='*72}")
        self._print(f"  TRAILING STOP-LOSS ASSISTANT")
        self._print(f"{'='*72}")

        if not results:
            self._print("  No holdings to analyze.")
            return

        for r in results:
            icon = "[!]" if r["action"] == "EXIT NOW" else "[+]" if "TRAIL" in r["action"] else "[~]"
            self._print(f"\n  {icon} {r['symbol'].replace('.NS', '')}")
            self._print(f"     Price: Rs.{r['current_price']} | Entry: Rs.{r['avg_price']} | "
                  f"P&L: {'+' if r['pnl_pct'] >= 0 else ''}{r['pnl_pct']:.1f}%")
            self._print(f"     SL: Rs.{r['recommended_sl']} | Phase: {r['sl_phase']} | "
                  f"Action: {r['action']}")
            self._print(f"     -> {r['advice']}")

        self._print(f"\n{'='*72}")

    def print_averaging_advice(self, force_override: bool = False):
        """Print formatted averaging recommendations to console."""
        results = self.get_averaging_recommendations(force_override=force_override)

        self._print(f"\n{'='*72}")
        self._print(f"  SMART AVERAGING DOWN ADVISOR")
        if force_override:
            self._print(f"  [WARN] FORCE OVERRIDE MODE -- Downtrend blocks bypassed")
        self._print(f"{'='*72}")

        if not results:
            self._print("  [OK] No holdings are below your average cost. Nothing to average.")
            return

        for r in results:
            icon = "[+]" if r["safe_to_average"] else "[!]" if r["blocked"] else "[~]"
            self._print(f"\n  {icon} {r['symbol'].replace('.NS', '')} [{r['sector']}]")
            self._print(f"     Price: Rs.{r['current_price']} | Avg: Rs.{r['avg_price']} | "
                  f"Loss: {r['loss_pct']:.1f}%")

            if r.get("warnings"):
                for w in r["warnings"]:
                    self._print(f"     {w}")

            if r.get("blocked"):
                for reason in r["block_reasons"]:
                    self._print(f"     [X] {reason}")
            elif "BUY" in r["action"]:
                self._print(f"     [OK] {r['action']}")
                self._print(f"     Investment: Rs.{r['recommended_investment']:,.0f} | "
                      f"New Avg: Rs.{r['new_avg_price']:.2f}")
                if r.get("support_level"):
                    self._print(f"     Support: {r['support_level']['name']} at Rs.{r['support_level']['price']}")
                if r.get("reasons"):
                    for reason in r["reasons"]:
                        self._print(f"     * {reason}")
            else:
                self._print(f"     -> {r['action']}")
                if r.get("reasons"):
                    for reason in r["reasons"]:
                        self._print(f"     * {reason}")

        self._print(f"\n{'='*72}")

    def print_tax_harvest(self):
        """Print formatted tax-loss harvesting recommendations to console."""
        data = self.get_tax_harvest_recommendations()

        self._print(f"\n{'='*72}")
        self._print(f"  TAX-LOSS HARVESTING ADVISOR")
        if data["near_fy_end"]:
            self._print(f"  [CAL] FY-End Alert: {data['days_to_fy_end']} days remaining!")
        self._print(f"{'='*72}")

        candidates = data["candidates"]
        if not candidates:
            self._print("  [OK] No significant unrealized losses to harvest.")
            return

        self._print(f"\n  Total Harvestable Loss: Rs.{data['total_harvestable_loss']:,.0f}")
        self._print(f"  Candidates: {data['candidate_count']}")

        for r in candidates:
            priority_icon = "[!]" if r["priority"] == "HIGH" else "[~]" if r["priority"] == "MEDIUM" else "[+]"
            self._print(f"\n  {priority_icon} {r['symbol'].replace('.NS', '')} [{r['sector']}] -- {r['priority']} PRIORITY")
            self._print(f"     Entry: Rs.{r['avg_price']} -> Now: Rs.{r['current_price']} | "
                  f"Loss: {r['loss_pct']:.1f}%")
            self._print(f"     Realizable Loss: Rs.{r['unrealized_loss']:,.0f}")
            self._print(f"     -> {r['advice']}")

        self._print(f"\n{'='*72}")

    def print_weekly_report(self):
        """Print formatted weekly report to console."""
        report = self.generate_weekly_report()

        if "error" in report:
            self._print(f"\n  {report['error']}")
            return

        p = report["portfolio"]

        self._print(f"\n{'='*72}")
        self._print(f"  WEEKLY PORTFOLIO REPORT -- {report['period']}")
        self._print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        self._print(f"{'='*72}")

        # Portfolio summary
        week_icon = "[UP]" if p["week_change_pct"] >= 0 else "[DN]"
        self._print(f"\n  {week_icon} Portfolio This Week: "
              f"{'+' if p['week_change_pct'] >= 0 else ''}{p['week_change_pct']:.2f}% "
              f"(Rs.{'+' if p['week_pnl_abs'] >= 0 else ''}{p['week_pnl_abs']:,.0f})")
        self._print(f"  Total P&L: {'+' if p['total_pnl_pct'] >= 0 else ''}{p['total_pnl_pct']:.2f}% "
              f"(Rs.{'+' if p['total_pnl'] >= 0 else ''}{p['total_pnl']:,.0f})")
        self._print(f"  Invested: Rs.{p['total_invested']:,.0f} | Current: Rs.{p['total_current']:,.0f}")

        # Top gainers
        self._print(f"\n  [TOP] TOP WEEKLY GAINERS:")
        for s in report["top_gainers"]:
            self._print(f"     {s['name']:<14} {'+' if s['week_change_pct'] >= 0 else ''}"
                  f"{s['week_change_pct']:.1f}%  (Rs.{s['week_start_price']} -> Rs.{s['current_price']})")

        # Top losers
        self._print(f"\n  [DN] TOP WEEKLY LOSERS:")
        for s in report["top_losers"]:
            self._print(f"     {s['name']:<14} {'+' if s['week_change_pct'] >= 0 else ''}"
                  f"{s['week_change_pct']:.1f}%  (Rs.{s['week_start_price']} -> Rs.{s['current_price']})")

        # Sector performance
        self._print(f"\n  [SECT] SECTOR PERFORMANCE:")
        for s in report["sector_performance"]:
            icon = "^" if s["week_change_pct"] >= 0 else "v"
            self._print(f"     {s['sector']:<14} {icon} {'+' if s['week_change_pct'] >= 0 else ''}"
                  f"{s['week_change_pct']:.1f}%  (Rs.{s['current_value']:,.0f})")

        # Key decisions
        decisions = report.get("key_decisions", [])
        if decisions:
            self._print(f"\n  [TGT] KEY DECISIONS TO MAKE:")
            for d in decisions:
                self._print(f"     {d['icon']} [{d['type']}] {d['advice']}")

        self._print(f"\n{'='*72}")

    def save_weekly_report(self, report: dict = None) -> str:
        """Save weekly report as a markdown file to data/reports/."""
        if report is None:
            report = self.generate_weekly_report()

        if "error" in report:
            return ""

        date_str = datetime.now().strftime("%Y-%m-%d")
        reports_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data", "reports"
        )
        os.makedirs(reports_dir, exist_ok=True)
        filepath = os.path.join(reports_dir, f"weekly_report_{date_str}.md")

        p = report["portfolio"]

        lines = [
            f"# Weekly Portfolio Report -- {date_str}",
            f"",
            f"**Period:** {report['period']}",
            f"**Generated:** {report['generated_at']}",
            f"",
            f"## Portfolio Summary",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Week Change | {'+' if p['week_change_pct'] >= 0 else ''}{p['week_change_pct']:.2f}% (Rs.{p['week_pnl_abs']:,.0f}) |",
            f"| Total P&L | {'+' if p['total_pnl_pct'] >= 0 else ''}{p['total_pnl_pct']:.2f}% (Rs.{p['total_pnl']:,.0f}) |",
            f"| Invested | Rs.{p['total_invested']:,.0f} |",
            f"| Current Value | Rs.{p['total_current']:,.0f} |",
            f"| Holdings | {p['holdings_count']} stocks |",
            f"",
            f"## Top Weekly Gainers",
            f"",
            f"| Stock | Week % | Price |",
            f"|-------|--------|-------|",
        ]

        for s in report["top_gainers"]:
            lines.append(f"| {s['name']} | {'+' if s['week_change_pct'] >= 0 else ''}{s['week_change_pct']:.1f}% | Rs.{s['current_price']} |")

        lines.extend([
            f"",
            f"## Top Weekly Losers",
            f"",
            f"| Stock | Week % | Price |",
            f"|-------|--------|-------|",
        ])

        for s in report["top_losers"]:
            lines.append(f"| {s['name']} | {'+' if s['week_change_pct'] >= 0 else ''}{s['week_change_pct']:.1f}% | Rs.{s['current_price']} |")

        lines.extend([
            f"",
            f"## Key Decisions",
            f"",
        ])

        for d in report.get("key_decisions", []):
            lines.append(f"- {d['icon']} **[{d['type']}]** {d['advice']}")

        lines.append("")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return filepath
