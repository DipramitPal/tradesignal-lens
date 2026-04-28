"""
Flask web application — TradeSignal Lens Dashboard.

Launch via:  python main.py ui
"""

import os
import sys
import json
import math
import traceback
import threading
from datetime import datetime, timezone, timedelta

# Ensure src/ is importable
_src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from flask import Flask, render_template, request, jsonify
import yfinance as yf


def _sanitize_for_json(obj):
    """Recursively replace NaN/Inf floats with None for valid JSON."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    return obj

from settings import (
    STOCK_SYMBOLS, SCAN_UNIVERSE, SYMBOL_SECTOR, SECTOR_MAP,
    DEFAULT_ACCOUNT_VALUE, MONITOR_SYMBOLS, SCAN_INTERVAL_MINUTES,
    MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE, MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE,
)
from portfolio.portfolio_manager import PortfolioManager
from portfolio.tracking_manager import TrackingManager
from market_data.data_cache import DataCache


# ---------------------------------------------------------------------------
# Singleton helpers (created once per process)
# ---------------------------------------------------------------------------
_portfolio = PortfolioManager()
_tracking = TrackingManager()
_cache = DataCache()
_cache_warmed = False
_last_cache_refresh: datetime | None = None
_refresh_thread_started = False
_IST = timezone(timedelta(hours=5, minutes=30))

# Breakout tracking
from quant.breakout_manager import BreakoutManager
_breakout_mgr = BreakoutManager()


def _is_market_window() -> bool:
    """True if current IST time is within market hours ± 30 min buffer."""
    now = datetime.now(_IST)
    market_open = now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0)
    market_close = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0)
    buffer = timedelta(minutes=30)
    return (market_open - buffer) <= now <= (market_close + buffer)


def _background_cache_refresh():
    """Background thread: refresh cache every SCAN_INTERVAL_MINUTES."""
    global _last_cache_refresh
    import time
    import pandas as pd
    interval = SCAN_INTERVAL_MINUTES * 60
    print(f"  [Cache Refresh] Background refresh thread started (every {SCAN_INTERVAL_MINUTES} min)")
    while True:
        time.sleep(interval)
        if not _is_market_window():
            continue
        try:
            syms = list(_cache.daily_cache.keys()) or MONITOR_SYMBOLS[:20]
            print(f"  [Cache Refresh] Refreshing {len(syms)} symbols...")
            _cache.refresh_intraday(syms)
            # Also refresh daily data so charts/watchlist reflect today's candle
            for sym in syms:
                df_new = DataCache._fetch(sym, period="5d", interval="1d")
                if not df_new.empty:
                    old = _cache.daily_cache.get(sym)
                    if old is not None and not old.empty:
                        combined = pd.concat([old.iloc[:-1], df_new])
                        combined = combined[~combined.index.duplicated(keep="last")]
                        _cache.daily_cache[sym] = combined.sort_index()
                    else:
                        _cache.daily_cache[sym] = df_new
            _cache.refresh_daily_if_needed(syms)
            _last_cache_refresh = datetime.now(_IST)
            print(f"  [Cache Refresh] Done at {_last_cache_refresh.strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"  [Cache Refresh] Error: {e}")


def _ensure_cache(symbols: list[str] | None = None):
    """Warm cache lazily on first API call, start background refresh thread."""
    global _cache_warmed, _last_cache_refresh, _refresh_thread_started
    if not _cache_warmed:
        _portfolio._load()
        _tracking._load()
        
        # Combine explicitly passed symbols, top monitor symbols, portfolio, and tracked 
        base_syms = symbols if symbols else MONITOR_SYMBOLS[:20]
        portfolio_syms = list(_portfolio.holdings.keys())
        tracked_syms = list(_tracking.get_all().keys())
        
        all_syms = list(set(base_syms + portfolio_syms + tracked_syms))
        
        print(f"  [Cache] Warming {len(all_syms)} symbols...")
        _cache.warm_cache(all_syms, daily_period="6mo", intraday_days=2)
        _cache_warmed = True
        _last_cache_refresh = datetime.now(_IST)

        # Start background refresh thread (once)
        if not _refresh_thread_started:
            _refresh_thread_started = True
            t = threading.Thread(target=_background_cache_refresh, daemon=True)
            t.start()


def _safe_float(val, default=None):
    """Convert to float, returning *default* for NaN / Inf / non-numeric."""
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _get_live_price(symbol: str) -> float | None:
    """Get latest price: intraday cache → daily cache → yfinance fallback."""
    # 1. Try intraday cache (most recent, refreshed every 15 min)
    idf = _cache.get_intraday(symbol)
    if not idf.empty:
        p = _safe_float(idf.iloc[-1]["close"])
        if p is not None:
            return p
    # 2. Fall back to daily cache
    df = _cache.get_daily(symbol)
    if not df.empty:
        p = _safe_float(df.iloc[-1]["close"])
        if p is not None:
            return p
    # 3. Fallback: one-shot yfinance
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="2d", interval="1d", auto_adjust=True)
        if not hist.empty:
            p = _safe_float(hist.iloc[-1]["Close"])
            if p is not None:
                return p
    except Exception:
        pass
    return None


def _get_live_prices(symbols: list[str]) -> dict[str, float]:
    """Batch price lookup."""
    prices = {}
    for sym in symbols:
        p = _get_live_price(sym)
        if p is not None:
            prices[sym] = round(p, 2)
    return prices


def _classify_recommendation(mtf_score: float, entry_quality: int) -> str:
    """Classify into High / Medium / Low recommendation tier."""
    if mtf_score >= 0.40 and entry_quality >= 70:
        return "HIGH"
    elif mtf_score >= 0.15 and entry_quality >= 50:
        return "MEDIUM"
    else:
        return "LOW"


def _classify_swing_tier(swing_rank: float, setup_actionable: bool) -> str:
    """Classify UI recommendation tier using the swing/position engine."""
    if not setup_actionable:
        return "LOW"
    if swing_rank >= 68:
        return "HIGH"
    if swing_rank >= 55:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
    )

    # ── Page ──────────────────────────────────────────────────────────

    @app.route("/")
    def index():
        return render_template("dashboard.html")

    # ── Summary ───────────────────────────────────────────────────────

    @app.route("/api/summary")
    def api_summary():
        _portfolio._load()
        _tracking._load()

        # Portfolio snapshot
        holdings = _portfolio.holdings
        symbols = list(holdings.keys())
        prices = _get_live_prices(symbols) if symbols else {}

        total_invested = 0.0
        total_current = 0.0
        portfolio_items = []
        for sym, h in holdings.items():
            inv = h.get("invested_value", h["qty"] * h["avg_price"])
            total_invested += inv
            cur_price = prices.get(sym, h["avg_price"])
            cur_val = h["qty"] * cur_price
            total_current += cur_val
            pnl_pct = ((cur_price - h["avg_price"]) / h["avg_price"]) * 100 if h["avg_price"] else 0
            portfolio_items.append({
                "symbol": sym,
                "qty": h["qty"],
                "avg_price": h["avg_price"],
                "current_price": cur_price,
                "pnl_pct": round(pnl_pct, 2),
                "sector": h.get("sector", SYMBOL_SECTOR.get(sym, "MISC")),
            })

        total_pnl = total_current - total_invested
        total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else 0

        # Tracking snapshot
        tracked = _tracking.get_all()
        tracked_prices = _get_live_prices(list(tracked.keys())) if tracked else {}
        tracking_items = []
        for sym, t in tracked.items():
            cur_price = tracked_prices.get(sym, t["simulated_price"])
            pnl_pct = ((cur_price - t["simulated_price"]) / t["simulated_price"]) * 100 if t["simulated_price"] else 0
            tracking_items.append({
                "symbol": sym,
                "qty": t["qty"],
                "simulated_price": t["simulated_price"],
                "current_price": cur_price,
                "pnl_pct": round(pnl_pct, 2),
            })

        # Market investability (simple heuristic)
        from market_data.market_utils import market_status as get_status
        mkt = get_status()

        # Regime from NIFTY
        regime = "UNKNOWN"
        investable = True
        invest_reasons = []
        try:
            nifty_df = _cache.get_daily("^NSEI")
            if nifty_df.empty:
                nifty_df = DataCache._fetch("^NSEI", period="3mo", interval="1d")
            if not nifty_df.empty and len(nifty_df) >= 50:
                from feature_engineering import add_technical_indicators
                from quant.regime_classifier import classify_regime
                nifty_ind = add_technical_indicators(nifty_df.copy())
                regime = classify_regime(nifty_ind, "RANGE_BOUND")

                last = nifty_ind.iloc[-1]
                rsi = float(last.get("rsi", 50))
                adx = float(last.get("adx", 20))

                if regime == "TRENDING_UP":
                    invest_reasons.append("Market trending up — favorable for new buys")
                elif regime == "TRENDING_DOWN":
                    investable = False
                    invest_reasons.append("Market in downtrend — be cautious with new positions")
                elif regime == "VOLATILE":
                    investable = False
                    invest_reasons.append("High volatility — reduce position sizes")
                else:
                    invest_reasons.append("Range-bound market — selective stock picking")

                if rsi > 75:
                    investable = False
                    invest_reasons.append(f"NIFTY RSI overbought ({rsi:.0f})")
                elif rsi < 30:
                    invest_reasons.append(f"NIFTY RSI oversold ({rsi:.0f}) — potential buying opportunity")
        except Exception as e:
            invest_reasons.append(f"Could not analyze NIFTY: {e}")

        # Sector breakdown
        sector_map = {}
        for item in portfolio_items:
            sec = item["sector"]
            val = _safe_float(item["qty"] * item["current_price"], 0)
            sector_map[sec] = sector_map.get(sec, 0) + val

        return jsonify({
            "portfolio": {
                "count": len(holdings),
                "total_invested": round(total_invested, 2),
                "total_current": round(total_current, 2),
                "total_pnl": round(total_pnl, 2),
                "total_pnl_pct": round(total_pnl_pct, 2),
                "account_value": _portfolio.account_value,
                "top_gainers": sorted(portfolio_items, key=lambda x: x["pnl_pct"], reverse=True)[:3],
                "top_losers": sorted(portfolio_items, key=lambda x: x["pnl_pct"])[:3],
                "sectors": sector_map,
            },
            "tracking": {
                "count": len(tracked),
                "items": tracking_items,
            },
            "market": {
                "status": mkt,
                "regime": regime,
                "investable": investable,
                "reasons": invest_reasons,
            },
        })

    # ── Portfolio ─────────────────────────────────────────────────────

    @app.route("/api/portfolio")
    def api_portfolio():
        _portfolio._load()
        holdings = _portfolio.holdings
        symbols = list(holdings.keys())
        prices = _get_live_prices(symbols)

        items = []
        for sym, h in holdings.items():
            cur_price = prices.get(sym, h["avg_price"])
            pnl_pct = ((cur_price - h["avg_price"]) / h["avg_price"]) * 100 if h["avg_price"] else 0
            cur_val = h["qty"] * cur_price
            items.append({
                "symbol": sym,
                "qty": h["qty"],
                "avg_price": h["avg_price"],
                "current_price": cur_price,
                "invested": round(h.get("invested_value", h["qty"] * h["avg_price"]), 2),
                "current_value": round(cur_val, 2),
                "pnl_pct": round(pnl_pct, 2),
                "pnl_abs": round(cur_val - h.get("invested_value", h["qty"] * h["avg_price"]), 2),
                "stop_loss": h.get("stop_loss", 0),
                "target": h.get("target", 0),
                "sector": h.get("sector", SYMBOL_SECTOR.get(sym, "MISC")),
                "added_date": h.get("added_date", ""),
                "notes": h.get("notes", ""),
            })

        return jsonify({
            "holdings": items,
            "account_value": _portfolio.account_value,
            "total_invested": round(_portfolio.get_total_invested(), 2),
        })

    @app.route("/api/portfolio/add", methods=["POST"])
    def api_portfolio_add():
        data = request.get_json(silent=True) or {}
        symbol = data.get("symbol", "").upper().strip()
        qty = int(data.get("qty", 0))
        price = float(data.get("price", 0))
        if not symbol or qty <= 0 or price <= 0:
            return jsonify({"error": "symbol, qty > 0, price > 0 required"}), 400

        _portfolio.add_holding(
            symbol=symbol, qty=qty, avg_price=price,
            stop_loss=float(data.get("stop_loss", 0)),
            target=float(data.get("target", 0)),
            notes=data.get("notes", ""),
        )
        return jsonify({"ok": True, "symbol": symbol})

    @app.route("/api/portfolio/remove", methods=["POST"])
    def api_portfolio_remove():
        data = request.get_json(silent=True) or {}
        symbol = data.get("symbol", "").upper().strip()
        if _portfolio.remove_holding(symbol):
            return jsonify({"ok": True})
        return jsonify({"error": "Not found"}), 404

    # ── Tracking ──────────────────────────────────────────────────────

    @app.route("/api/tracking")
    def api_tracking():
        tracked = _tracking.get_all()
        symbols = list(tracked.keys())
        prices = _get_live_prices(symbols)

        items = []
        for sym, t in tracked.items():
            cur = prices.get(sym, t["simulated_price"])
            pnl = ((cur - t["simulated_price"]) / t["simulated_price"]) * 100 if t["simulated_price"] else 0
            items.append({
                "symbol": sym,
                "qty": t["qty"],
                "simulated_price": t["simulated_price"],
                "current_price": cur,
                "pnl_pct": round(pnl, 2),
                "pnl_abs": round((cur - t["simulated_price"]) * t["qty"], 2),
                "added_date": t.get("added_date", ""),
                "notes": t.get("notes", ""),
            })
        return jsonify({"items": items})

    @app.route("/api/tracking/add", methods=["POST"])
    def api_tracking_add():
        data = request.get_json(silent=True) or {}
        symbol = data.get("symbol", "").upper().strip()
        qty = int(data.get("qty", 1))
        price = float(data.get("price", 0))

        if not symbol:
            return jsonify({"error": "symbol required"}), 400

        # Auto-fetch price if not provided
        if price <= 0:
            p = _get_live_price(symbol)
            if p:
                price = p
            else:
                return jsonify({"error": "Could not fetch price, please provide manually"}), 400

        _tracking.add_stock(symbol=symbol, qty=qty, price=price,
                            notes=data.get("notes", ""))
        return jsonify({"ok": True, "symbol": symbol, "price": price})

    @app.route("/api/tracking/update", methods=["POST"])
    def api_tracking_update():
        data = request.get_json(silent=True) or {}
        symbol = data.get("symbol", "").upper().strip()
        if not symbol:
            return jsonify({"error": "symbol required"}), 400

        ok = _tracking.update_stock(
            symbol,
            qty=int(data["qty"]) if "qty" in data else None,
            price=float(data["price"]) if "price" in data else None,
            notes=data.get("notes"),
        )
        if ok:
            return jsonify({"ok": True})
        return jsonify({"error": "Not found"}), 404

    @app.route("/api/tracking/remove", methods=["POST"])
    def api_tracking_remove():
        data = request.get_json(silent=True) or {}
        symbol = data.get("symbol", "").upper().strip()
        if _tracking.remove_stock(symbol):
            return jsonify({"ok": True})
        return jsonify({"error": "Not found"}), 404

    @app.route("/api/tracking/buy", methods=["POST"])
    def api_tracking_buy():
        """Move a tracked stock to the real portfolio."""
        data = request.get_json(silent=True) or {}
        symbol = data.get("symbol", "").upper().strip()
        qty = int(data.get("qty")) if data.get("qty") else None
        price = float(data.get("price")) if data.get("price") else None

        result = _tracking.mark_as_bought(symbol, qty=qty, price=price)
        if not result:
            return jsonify({"error": "Not found in tracking"}), 404

        _portfolio.add_holding(
            symbol=result["symbol"],
            qty=result["qty"],
            avg_price=result["avg_price"],
        )
        return jsonify({"ok": True, "symbol": result["symbol"]})

    # ── Watchlist / Momentum ──────────────────────────────────────────

    @app.route("/api/watchlist")
    def api_watchlist():
        """Return watchlist with recommendation tiers."""
        _ensure_cache()

        from feature_engineering import add_technical_indicators
        from signal_generator import score_signals, normalize_score, score_to_recommendation
        from quant.regime_classifier import classify_regime, get_weight_table
        from quant.risk_manager import compute_entry_quality, compute_initial_sl
        from quant.sector_analyzer import SectorAnalyzer
        from quant.swing_engine import classify_swing_setup
        from quant.swing_ranker import compute_swing_rank

        # Determine regime
        regime = "RANGE_BOUND"
        for sym in MONITOR_SYMBOLS[:5]:
            df = _cache.get_daily(sym)
            if not df.empty and len(df) >= 50:
                try:
                    df_ind = add_technical_indicators(df.copy())
                    regime = classify_regime(df_ind, regime)
                except Exception:
                    pass
                break

        weight_table = get_weight_table(regime)
        sector_analyzer = SectorAnalyzer()
        items = []
        scan_symbols = MONITOR_SYMBOLS[:30]  # Limit for speed

        for sym in scan_symbols:
            try:
                df = _cache.get_daily(sym)
                if df.empty or len(df) < 30:
                    continue

                df_ind = add_technical_indicators(df.copy())
                latest = df_ind.iloc[-1]

                def _sf(val, fallback=0.0):
                    v = float(val)
                    return fallback if math.isnan(v) else v

                price = _sf(latest["close"], 0)
                if price == 0:
                    for i in range(2, min(len(df_ind), 10)):
                        p = _sf(df_ind.iloc[-i]["close"], 0)
                        if p > 0:
                            price = p
                            break
                if price == 0:
                    continue

                rsi = _sf(latest.get("rsi", 50), 50)
                cmf = _sf(latest.get("cmf", 0), 0)
                squeeze_fire = int(_sf(latest.get("squeeze_fire", 0), 0))
                atr = _sf(latest.get("atr", price * 0.02), price * 0.02)

                score = score_signals(df_ind, weight_table)
                normalized = normalize_score(score, max_possible=0.8)
                rec = score_to_recommendation(normalized)

                vol = _sf(latest.get("volume", 0), 0)
                vol_avg = _sf(df_ind["volume"].rolling(20).mean().iloc[-1], vol) if len(df_ind) >= 20 else vol
                rvol = vol / (vol_avg + 1e-10)

                entry_quality = compute_entry_quality(
                    price, rsi, squeeze_fire, rvol, cmf,
                )

                swing_setup = classify_swing_setup(df_ind, current_price=price, rvol=rvol)
                sector_mult = sector_analyzer.get_sector_multiplier(sym)
                swing_rank = compute_swing_rank(
                    df_ind,
                    price=price,
                    swing_setup=swing_setup.as_dict(),
                    mtf_score=normalized,
                    entry_quality=entry_quality,
                    rvol=rvol,
                    sector_multiplier=sector_mult,
                )

                sl = swing_setup.stop_loss if swing_setup.stop_loss > 0 else compute_initial_sl(price, atr)
                tier = _classify_swing_tier(swing_rank["score"], swing_setup.actionable)

                prev_close = _sf(df_ind.iloc[-2]["close"], price) if len(df_ind) > 1 else price
                day_change = round(((price - prev_close) / (prev_close + 1e-10)) * 100, 2)

                _is_bo, _bo_lvl, _ = BreakoutManager.detect_breakout(price, df, rvol=rvol)

                items.append(_sanitize_for_json({
                    "symbol": sym,
                    "price": round(price, 2),
                    "day_change_pct": day_change,
                    "rsi": round(rsi, 1),
                    "mtf_score": round(normalized, 3),
                    "entry_quality": entry_quality,
                    "recommendation": rec,
                    "tier": tier,
                    "stop_loss": round(sl, 2),
                    "swing_setup": swing_setup.setup_type,
                    "swing_setup_quality": swing_setup.quality_score,
                    "swing_rank": swing_rank["score"],
                    "swing_rank_bucket": swing_rank["bucket"],
                    "swing_rank_metrics": swing_rank["metrics"],
                    "rvol": round(rvol, 2),
                    "sector": SYMBOL_SECTOR.get(sym, "MISC"),
                    "squeeze_fire": bool(squeeze_fire),
                    "breakout": _is_bo,
                    "breakout_level": _bo_lvl,
                }))
            except Exception:
                continue

        # Sort: HIGH first, then MEDIUM, then LOW
        # Within same tier, rank by composite score (MTF × quality) for objective ordering
        tier_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        items.sort(key=lambda x: (
            tier_order.get(x["tier"], 3),
            -x.get("swing_rank", 0),
        ))

        return jsonify({"items": items, "regime": regime})

    # ── Stock Chart Data ──────────────────────────────────────────────

    @app.route("/api/stock/<symbol>/chart")
    def api_stock_chart(symbol: str):
        symbol = symbol.upper().strip()
        period = request.args.get("period", "6mo")

        # Try cache first
        df = _cache.get_daily(symbol)
        if df.empty:
            try:
                t = yf.Ticker(symbol)
                df = t.history(period=period, interval="1d", auto_adjust=True)
                if not df.empty:
                    df.columns = [c.lower() for c in df.columns]
            except Exception:
                pass

        if df.empty:
            return jsonify({"error": "No data"}), 404

        # Add indicators for baseline
        try:
            from feature_engineering import add_technical_indicators
            df_ind = add_technical_indicators(df.copy())
        except Exception:
            df_ind = df.copy()

        candles = []
        sma20 = []
        sma50 = []
        volumes = []

        for idx, row in df_ind.iterrows():
            ts = int(idx.timestamp()) if hasattr(idx, 'timestamp') else 0

            # Safe float extraction
            def _sf(val, default=None):
                try:
                    f = float(val)
                    return default if math.isnan(f) or math.isinf(f) else f
                except (TypeError, ValueError):
                    return default

            o, h, l, c = _sf(row.get("open")), _sf(row.get("high")), _sf(row.get("low")), _sf(row.get("close"))
            
            # Skip rows where OHLC data is missing completely (prevents lightweight charts crash)
            if c is None:
                continue

            # Fallback for missing intra-day OHLC values to just the close price
            o = o if o is not None else c
            h = h if h is not None else c
            l = l if l is not None else c

            candles.append({
                "time": ts,
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(l, 2),
                "close": round(c, 2),
            })
            volumes.append({
                "time": ts,
                "value": int(row.get("volume", 0)),
                "color": "rgba(38,198,218,0.3)" if row.get("close", 0) >= row.get("open", 0) else "rgba(239,83,80,0.3)",
            })
            if "sma_20" in row and not (hasattr(row["sma_20"], '__float__') and str(row["sma_20"]) == 'nan'):
                try:
                    val = float(row["sma_20"])
                    if val == val:  # not NaN
                        sma20.append({"time": ts, "value": round(val, 2)})
                except (ValueError, TypeError):
                    pass
            if "sma_50" in row:
                try:
                    val = float(row["sma_50"])
                    if val == val:
                        sma50.append({"time": ts, "value": round(val, 2)})
                except (ValueError, TypeError):
                    pass

        # Stop loss line
        sl_value = None
        try:
            from signal_generator import compute_stop_loss
            last = df_ind.iloc[-1]
            atr = float(last.get("atr", float(last["close"]) * 0.02))
            sl_value = round(compute_stop_loss(float(last["close"]), atr), 2)
        except Exception:
            pass

        # Portfolio entry price
        _portfolio._load()
        entry_price = None
        h = _portfolio.get_holding(symbol)
        if h:
            entry_price = h["avg_price"]

        return jsonify(_sanitize_for_json({
            "symbol": symbol,
            "candles": candles,
            "sma20": sma20,
            "sma50": sma50,
            "volumes": volumes,
            "stop_loss": sl_value,
            "entry_price": entry_price,
        }))

    # ── Stock Analysis ────────────────────────────────────────────────

    @app.route("/api/stock/<symbol>/analysis")
    def api_stock_analysis(symbol: str):
        symbol = symbol.upper().strip()
        _ensure_cache([symbol])

        try:
            from feature_engineering import add_technical_indicators, compute_pivot_points
            from signal_generator import (
                score_signals, normalize_score, score_to_recommendation,
                score_to_confidence, compute_stop_loss,
            )
            from quant.regime_classifier import classify_regime, get_weight_table
            from quant.risk_manager import compute_entry_quality, compute_initial_sl
            from quant.divergence_detector import detect_all_divergences, summarize_divergences
            from quant.sector_analyzer import SectorAnalyzer
            from quant.swing_engine import classify_swing_setup
            from quant.swing_ranker import compute_swing_rank

            df = _cache.get_daily(symbol)
            if df.empty:
                t = yf.Ticker(symbol)
                df = t.history(period="6mo", interval="1d", auto_adjust=True)
                if not df.empty:
                    df.columns = [c.lower() for c in df.columns]

            if df.empty or len(df) < 20:
                return jsonify({"error": "Insufficient data"}), 404

            df_ind = add_technical_indicators(df.copy())
            latest = df_ind.iloc[-1]

            # NaN-safe extraction: use last valid value from daily data
            def _sf(val, fallback=0.0):
                """Safe float — returns fallback if NaN."""
                v = float(val)
                return fallback if math.isnan(v) else v

            # Price: walk backwards to find last valid close
            price = _sf(latest["close"], 0)
            if price == 0:
                for i in range(2, min(len(df_ind), 10)):
                    p = _sf(df_ind.iloc[-i]["close"], 0)
                    if p > 0:
                        price = p
                        break

            rsi = _sf(latest.get("rsi", 50), 50)
            atr = _sf(latest.get("atr", price * 0.02), price * 0.02)
            adx = _sf(latest.get("adx", 0), 0)
            cmf = _sf(latest.get("cmf", 0), 0)
            supertrend_dir = _sf(latest.get("supertrend_direction", 0), 0)
            squeeze = int(_sf(latest.get("squeeze_fire", 0), 0))

            regime = classify_regime(df_ind, "RANGE_BOUND")
            wt = get_weight_table(regime)
            score = score_signals(df_ind, wt)
            normalized = normalize_score(score, max_possible=0.8)
            rec = score_to_recommendation(normalized)
            conf = score_to_confidence(normalized)

            vol = _sf(latest.get("volume", 0), 0)
            vol_avg = _sf(df_ind["volume"].rolling(20).mean().iloc[-1], vol) if len(df_ind) >= 20 else vol
            rvol = vol / (vol_avg + 1e-10)
            entry_quality = compute_entry_quality(price, rsi, squeeze, rvol, cmf)
            swing_setup = classify_swing_setup(df_ind, current_price=price, rvol=rvol)
            sector_mult = SectorAnalyzer().get_sector_multiplier(symbol)
            swing_rank = compute_swing_rank(
                df_ind,
                price=price,
                swing_setup=swing_setup.as_dict(),
                mtf_score=normalized,
                entry_quality=entry_quality,
                rvol=rvol,
                sector_multiplier=sector_mult,
            )
            sl = swing_setup.stop_loss if swing_setup.stop_loss > 0 else compute_initial_sl(price, atr)

            divs = detect_all_divergences(df_ind, lookback=50)
            div_summary = summarize_divergences(divs)

            prev_close = _sf(df_ind.iloc[-2]["close"], price) if len(df_ind) > 1 else price
            day_change = round(((price - prev_close) / (prev_close + 1e-10)) * 100, 2)

            tier = _classify_swing_tier(swing_rank["score"], swing_setup.actionable)

            # Breakout detection
            is_bo, bo_level, pct_above_bo = _breakout_mgr.detect_breakout(
                price, df, rvol=rvol,
            )

            # News & Sentiment (Background/Fast fetch)
            news_items = []
            news_label = "Neutral"
            try:
                from news.news_fetcher import NewsFetcher
                from news.sentiment_analyzer import SentimentAnalyzer
                nf = NewsFetcher()
                sa = SentimentAnalyzer()
                
                # Fetch just 3 articles for speed
                articles = nf.fetch_stock_news(symbol, max_results=3)
                if articles:
                    analysis = sa.analyze_articles(articles)
                    news_label = analysis["overall_label"].title()
                    for art, sent in zip(articles, analysis["article_sentiments"]):
                        news_items.append({
                            "title": art["title"],
                            "url": art["url"],
                            "source": art["source"],
                            "sentiment": sent["label"].title()
                        })
            except Exception as e:
                print(f"Error fetching news for {symbol}: {e}")

            return jsonify(_sanitize_for_json({
                "symbol": symbol,
                "price": round(price, 2),
                "day_change_pct": day_change,
                "rsi": round(rsi, 1),
                "adx": round(adx, 1),
                "cmf": round(cmf, 3),
                "atr": round(atr, 2),
                "rvol": round(rvol, 2),
                "supertrend": "Bullish" if supertrend_dir == 1 else "Bearish",
                "squeeze_fire": bool(squeeze),
                "regime": regime,
                "mtf_score": round(normalized, 3),
                "entry_quality": entry_quality,
                "recommendation": rec,
                "confidence": conf,
                "stop_loss": round(sl, 2),
                "swing_setup": swing_setup.setup_type,
                "swing_setup_quality": swing_setup.quality_score,
                "swing_rank": swing_rank["score"],
                "swing_rank_bucket": swing_rank["bucket"],
                "swing_rank_components": swing_rank["components"],
                "swing_rank_metrics": swing_rank["metrics"],
                "divergence": div_summary["direction"],
                "sector": SYMBOL_SECTOR.get(symbol, "MISC"),
                "tier": tier,
                "breakout": is_bo,
                "breakout_level": round(bo_level, 2),
                "pct_above_breakout": round(pct_above_bo, 2),
                "news_sentiment": news_label,
                "recent_news": news_items,
            }))
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    # ── Portfolio Advisor ─────────────────────────────────────────────

    @app.route("/api/portfolio/advisor")
    def api_portfolio_advisor():
        """All advisor outputs in one payload."""
        try:
            from portfolio.portfolio_advisor import PortfolioAdvisor
            advisor = PortfolioAdvisor(portfolio=_portfolio, cache=_cache)
            _ensure_cache()

            force = request.args.get("force", "false").lower() == "true"

            tsl = advisor.get_tsl_advice()
            averaging = advisor.get_averaging_recommendations(force_override=force)
            harvest = advisor.get_tax_harvest_recommendations()

            return jsonify(_sanitize_for_json({
                "tsl_advice": tsl,
                "averaging_recommendations": averaging,
                "tax_harvest": harvest,
            }))
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route("/api/portfolio/weekly-report")
    def api_portfolio_weekly_report():
        """Weekly portfolio performance report."""
        try:
            from portfolio.portfolio_advisor import PortfolioAdvisor
            advisor = PortfolioAdvisor(portfolio=_portfolio, cache=_cache)
            _ensure_cache()

            report = advisor.generate_weekly_report()
            return jsonify(_sanitize_for_json(report))
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route("/api/portfolio/tsl")
    def api_portfolio_tsl():
        """Lightweight TSL advice endpoint."""
        try:
            from portfolio.portfolio_advisor import PortfolioAdvisor
            advisor = PortfolioAdvisor(portfolio=_portfolio, cache=_cache)
            _ensure_cache()

            tsl = advisor.get_tsl_advice()
            return jsonify(_sanitize_for_json({"tsl_advice": tsl}))
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    # ── Market Status (keep existing) ─────────────────────────────────

    @app.route("/api/market-status")
    def market_status():
        from market_data.market_utils import market_status as get_status
        return jsonify(get_status())

    # ── Cache Status ──────────────────────────────────────────────────

    @app.route("/api/cache-status")
    def cache_status():
        return jsonify({
            "last_refresh": _last_cache_refresh.isoformat() if _last_cache_refresh else None,
            "refresh_interval_minutes": SCAN_INTERVAL_MINUTES,
            "symbols_cached": len(_cache.daily_cache),
        })

    # ── Symbol search ─────────────────────────────────────────────────

    @app.route("/api/search")
    def api_search():
        q = request.args.get("q", "").upper().strip()
        if len(q) < 2:
            return jsonify({"results": []})
        all_syms = list(set(SCAN_UNIVERSE + MONITOR_SYMBOLS + list(_portfolio.holdings.keys())))
        matches = [s for s in all_syms if q in s][:15]
        return jsonify({"results": matches})

    # ── Swing Backtest API ─────────────────────────────────────────────

    @app.route("/api/backtest/run", methods=["POST"])
    def api_backtest_run():
        """Run the swing backtester and return full analytics."""
        try:
            from quant.swing_backtester import SwingBacktester, SwingBacktestConfig
            from quant.backtest_analytics import compute_full_analytics

            data = request.get_json(silent=True) or {}

            cfg = SwingBacktestConfig(
                universe=data.get("universe", MONITOR_SYMBOLS[:15]),
                start_date=data.get("start_date", "2023-06-01"),
                end_date=data.get("end_date", "2024-12-31"),
                initial_capital=float(data.get("initial_capital", 500_000)),
                max_positions=int(data.get("max_positions", 5)),
                rebalance_freq=data.get("rebalance_freq", "weekly"),
                risk_per_trade=float(data.get("risk_per_trade", 0.02)),
                min_swing_rank=float(data.get("min_swing_rank", 40)),
                replacement_threshold=float(data.get("replacement_threshold", 10)),
                min_price=float(data.get("min_price", 50)),
                min_avg_volume=int(data.get("min_avg_volume", 100_000)),
            )

            bt = SwingBacktester(cfg)
            bt.load_data()
            bt.run()

            report = compute_full_analytics(bt)

            # Add equity curve for charting
            eq = bt.get_equity_curve()
            eq_data = []
            if not eq.empty and "date" in eq.columns:
                for _, row in eq.iterrows():
                    ts = int(pd.Timestamp(row["date"]).timestamp())
                    eq_data.append({"time": ts, "value": round(float(row["total_value"]), 2)})

            # Recent trades
            trades_df = bt.get_trade_log()
            recent = []
            if not trades_df.empty:
                tail = trades_df.tail(30)
                for _, t in tail.iterrows():
                    recent.append({
                        "date": str(t.get("date", ""))[:10],
                        "symbol": str(t.get("symbol", "")),
                        "action": str(t.get("action", "")),
                        "price": round(float(t.get("price", 0)), 2),
                        "reason": str(t.get("reason", "")),
                        "pnl": round(float(t.get("pnl", 0)), 2),
                    })

            return jsonify(_sanitize_for_json({
                "report": report,
                "equity_curve": eq_data,
                "recent_trades": recent,
                "config": {
                    "universe_size": len(cfg.universe),
                    "start_date": cfg.start_date,
                    "end_date": cfg.end_date,
                    "initial_capital": cfg.initial_capital,
                    "max_positions": cfg.max_positions,
                    "rebalance_freq": cfg.rebalance_freq,
                },
            }))
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    # ── Swing Signal Runner API ───────────────────────────────────────

    @app.route("/api/swing-signals")
    def api_swing_signals():
        """Return the latest saved swing signal report (from data/reports/)."""
        try:
            from settings import REPORTS_DIR
            import glob

            pattern = str(REPORTS_DIR / "swing_signals_*.json")
            files = sorted(glob.glob(pattern), reverse=True)

            if not files:
                return jsonify({"error": "No swing signal report found. Run the EOD scan first.", "empty": True}), 200

            with open(files[0], "r") as f:
                report = json.load(f)

            report["report_file"] = os.path.basename(files[0])
            return jsonify(_sanitize_for_json(report))
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route("/api/swing-signals/run", methods=["POST"])
    def api_swing_signals_run():
        """Run the SwingSignalRunner on-demand and return the report."""
        try:
            _ensure_cache()

            from quant.swing_signal_runner import SwingSignalRunner, HeldPosition

            # Build held positions from portfolio
            _portfolio._load()
            held = {}
            for sym, h in _portfolio.holdings.items():
                held[sym] = HeldPosition(
                    symbol=sym,
                    entry_price=float(h.get("avg_price", 0)),
                    shares=int(h.get("qty", 0)),
                    stop_loss=float(h.get("stop_loss", 0)),
                    entry_date=h.get("added_date", ""),
                    highest_since_entry=float(h.get("highest_price", h.get("avg_price", 0))),
                )

            # Build preloaded data from cache where available
            preloaded = {}
            from feature_engineering import add_technical_indicators
            all_syms = list(set(MONITOR_SYMBOLS[:30]) | set(held.keys()))
            for sym in all_syms:
                df = _cache.get_daily(sym)
                if not df.empty and len(df) >= 60:
                    try:
                        df_ind = add_technical_indicators(df.copy())
                        df_ind["rvol"] = df_ind["volume"] / (df_ind["volume"].rolling(20).mean() + 1e-10)
                        df_ind["swing_low_20d"] = df_ind["low"].rolling(20).min()
                        preloaded[sym] = df_ind
                    except Exception:
                        pass

            runner = SwingSignalRunner(
                universe=list(preloaded.keys()),
                held_positions=held,
                account_value=_portfolio.account_value,
                portfolio_manager=_portfolio,
            )
            report = runner.run(preloaded=preloaded)

            # Return the dataclass as dict
            from dataclasses import asdict
            return jsonify(_sanitize_for_json(asdict(report)))
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    return app


if __name__ == "__main__":
    create_app().run(debug=True, host="0.0.0.0", port=5000)
