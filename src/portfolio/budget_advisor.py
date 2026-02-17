"""
Budget-based portfolio advisor.
Takes an investment budget and risk tolerance, then generates suggestions
across single stocks, index funds, diversified batches, and stock+ETF mixes.

Uses a lightweight technical-only scan (no news/social/LLM calls) so results
come back in seconds rather than minutes.
"""

import os
import sys
from math import floor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import STOCK_SYMBOLS

# Popular Indian ETFs available on BSE (via Alpha Vantage)
INDEX_FUNDS = [
    {
        "symbol": "NIFTYBEES.BSE",
        "name": "Nippon India Nifty 50 BeES",
        "type": "Nifty 50 ETF",
        "description": "Tracks Nifty 50 index — broad large-cap exposure",
    },
    {
        "symbol": "JUNIORBEES.BSE",
        "name": "Nippon India Junior BeES",
        "type": "Nifty Next 50 ETF",
        "description": "Tracks Nifty Next 50 — large-to-mid cap growth",
    },
    {
        "symbol": "BANKBEES.BSE",
        "name": "Nippon India Bank BeES",
        "type": "Bank Nifty ETF",
        "description": "Tracks Bank Nifty — concentrated banking sector",
    },
    {
        "symbol": "GOLDBEES.BSE",
        "name": "Nippon India Gold BeES",
        "type": "Gold ETF",
        "description": "Tracks domestic gold prices — hedge against equity volatility",
    },
    {
        "symbol": "SETFNIF50.BSE",
        "name": "SBI ETF Nifty 50",
        "type": "Nifty 50 ETF",
        "description": "SBI's Nifty 50 tracker — alternative broad market ETF",
    },
]

# Sector classification for diversification
SECTOR_GROUPS = {
    "Financial Services": [
        "HDFCBANK.BSE", "ICICIBANK.BSE", "SBIN.BSE", "KOTAKBANK.BSE", "AXISBANK.BSE",
    ],
    "IT": ["TCS.BSE", "INFY.BSE", "WIPRO.BSE"],
    "Energy & Commodities": ["RELIANCE.BSE", "TATASTEEL.BSE", "ADANIENT.BSE"],
    "FMCG & Consumer": ["HINDUNILVR.BSE", "ITC.BSE", "TITAN.BSE", "ASIANPAINT.BSE"],
    "Auto & Industrial": ["MARUTI.BSE", "TATAMOTORS.BSE", "LT.BSE"],
    "Pharma & Healthcare": ["SUNPHARMA.BSE"],
    "Telecom": ["BHARTIARTL.BSE"],
}


class BudgetAdvisor:
    """Generates budget-based investment suggestions."""

    def __init__(self):
        self._market_data = None
        self._signal_combiner = None

    @property
    def market_data(self):
        if self._market_data is None:
            from market_data.indian_market import IndianMarketData
            self._market_data = IndianMarketData()
        return self._market_data

    @property
    def signal_combiner(self):
        if self._signal_combiner is None:
            from ai_engine.signal_combiner import SignalCombiner
            self._signal_combiner = SignalCombiner()
        return self._signal_combiner

    def get_suggestions(self, budget: float, risk_profile: str = "balanced") -> dict:
        """
        Generate investment suggestions for a given budget.

        Args:
            budget: Investment amount in INR.
            risk_profile: "conservative", "balanced", or "aggressive".

        Returns:
            dict with categorized suggestions.
        """
        stock_data = self._scan_stocks()
        etf_data = self._scan_etfs()

        return {
            "budget": budget,
            "risk_profile": risk_profile,
            "suggestions": {
                "single_stocks": self._suggest_single_stocks(stock_data, budget, risk_profile),
                "index_funds": self._suggest_index_funds(etf_data, budget),
                "batches": self._suggest_batches(stock_data, budget, risk_profile),
                "mixes": self._suggest_mixes(stock_data, etf_data, budget, risk_profile),
            },
        }

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def _scan_stocks(self) -> list[dict]:
        """Quick technical-only scan of watchlist stocks."""
        from feature_engineering import add_technical_indicators
        from signal_generator import generate_signals

        results = []
        for symbol in STOCK_SYMBOLS:
            try:
                df = self.market_data.fetch_stock(symbol, period="6mo")
                if df.empty:
                    continue

                df_tech = add_technical_indicators(df.copy())
                df_signals = generate_signals(df_tech.copy())

                latest = df_tech.iloc[-1]
                latest_signal = df_signals.iloc[-1].get("Signal", "Hold")

                technical_data = {
                    "close": float(latest["close"]),
                    "rsi": float(latest.get("rsi", 50)),
                    "macd": float(latest.get("macd", 0)),
                    "macd_signal": float(latest.get("macd_signal", 0)),
                    "macd_hist": float(latest.get("macd_hist", 0)),
                    "bb_high": float(latest.get("bb_high", 0)),
                    "bb_low": float(latest.get("bb_low", 0)),
                    "momentum_5": float(latest.get("momentum_5", 0)),
                    "volume": float(latest.get("volume", 0)),
                    "ema_12": float(latest.get("ema_12", 0)),
                    "ema_26": float(latest.get("ema_26", 0)),
                    "signal": latest_signal,
                }

                # Combine with neutral sentiment (tech-only scan)
                combined = self.signal_combiner.combine(
                    technical_data,
                    {"overall_compound": 0.0, "overall_label": "neutral"},
                    {"score": 0.0, "sentiment": "neutral"},
                )

                info = self.market_data.get_stock_info(symbol)

                results.append({
                    "symbol": symbol,
                    "name": info.get("name", symbol),
                    "sector": info.get("sector", "N/A"),
                    "price": technical_data["close"],
                    "rsi": round(technical_data["rsi"], 2),
                    "signal": latest_signal,
                    "recommendation": combined["recommendation"],
                    "confidence": combined["confidence"],
                    "score": combined["combined_score"],
                })
            except Exception as e:
                print(f"  Error scanning {symbol}: {e}")

        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def _scan_etfs(self) -> list[dict]:
        """Fetch current prices for index funds / ETFs."""
        results = []
        for etf in INDEX_FUNDS:
            try:
                df = self.market_data.fetch_stock(etf["symbol"], period="5d")
                if df.empty:
                    continue
                results.append({**etf, "price": float(df.iloc[-1]["close"])})
            except Exception as e:
                print(f"  Error fetching ETF {etf['symbol']}: {e}")
        return results

    # ------------------------------------------------------------------
    # Suggestion generators
    # ------------------------------------------------------------------

    def _suggest_single_stocks(
        self, stocks: list[dict], budget: float, risk_profile: str,
    ) -> list[dict]:
        """Top individual stock picks within budget."""
        suggestions = []
        for stock in stocks:
            if stock["price"] <= 0 or stock["price"] > budget:
                continue
            if risk_profile == "conservative" and stock["recommendation"] in (
                "SELL", "STRONG SELL",
            ):
                continue
            if risk_profile == "aggressive" and stock["recommendation"] == "HOLD":
                continue

            qty = floor(budget / stock["price"])
            total = round(qty * stock["price"], 2)
            suggestions.append({
                **stock,
                "quantity": qty,
                "total_cost": total,
                "remaining": round(budget - total, 2),
            })

        return suggestions[:5]

    def _suggest_index_funds(
        self, etfs: list[dict], budget: float,
    ) -> list[dict]:
        """Index fund / ETF allocations."""
        suggestions = []
        for etf in etfs:
            if etf["price"] <= 0 or etf["price"] > budget:
                continue
            qty = floor(budget / etf["price"])
            total = round(qty * etf["price"], 2)
            suggestions.append({
                **etf,
                "quantity": qty,
                "total_cost": total,
                "remaining": round(budget - total, 2),
            })
        return suggestions

    def _suggest_batches(
        self, stocks: list[dict], budget: float, risk_profile: str,
    ) -> list[dict]:
        """Diversified multi-stock batches."""
        batches = []

        # Group available stocks by sector
        stock_lookup = {s["symbol"]: s for s in stocks}
        stocks_by_sector: dict[str, list[dict]] = {}
        for sector, symbols in SECTOR_GROUPS.items():
            for sym in symbols:
                if sym in stock_lookup:
                    stocks_by_sector.setdefault(sector, []).append(stock_lookup[sym])

        conservative = self._build_batch(
            stocks_by_sector, budget,
            name="Conservative Blue-Chip",
            description="Large-cap leaders from different sectors. Lower volatility, steady returns.",
            risk_level="Low",
            max_stocks=5,
            prefer_positive=True,
        )
        if conservative:
            batches.append(conservative)

        balanced = self._build_batch(
            stocks_by_sector, budget,
            name="Balanced Growth",
            description="Mix of stable performers and growth picks across sectors.",
            risk_level="Medium",
            max_stocks=4,
            prefer_positive=True,
        )
        if balanced:
            batches.append(balanced)

        # Aggressive: top-signal stocks regardless of sector
        aggressive_stocks = [
            s for s in stocks if s["score"] > 0 and s["price"] <= budget
        ][:5]
        if aggressive_stocks:
            agg_alloc = self._allocate_equal(aggressive_stocks, budget)
            if agg_alloc:
                batches.append({
                    "name": "High-Momentum Aggressive",
                    "description": "Strongest technical signals. Higher risk, higher potential.",
                    "risk_level": "High",
                    "stocks": agg_alloc,
                    "total_cost": sum(s["allocation"] for s in agg_alloc),
                    "remaining": round(
                        budget - sum(s["allocation"] for s in agg_alloc), 2,
                    ),
                    "num_sectors": len(set(s.get("sector", "N/A") for s in agg_alloc)),
                })

        return batches

    def _suggest_mixes(
        self,
        stocks: list[dict],
        etfs: list[dict],
        budget: float,
        risk_profile: str,
    ) -> list[dict]:
        """Stock + ETF hybrid mix suggestions."""
        splits = {
            "conservative": [
                (0.30, 0.70, "30% Stocks / 70% Index"),
                (0.50, 0.50, "50% Stocks / 50% Index"),
            ],
            "balanced": [
                (0.50, 0.50, "50% Stocks / 50% Index"),
                (0.70, 0.30, "70% Stocks / 30% Index"),
            ],
            "aggressive": [
                (0.70, 0.30, "70% Stocks / 30% Index"),
                (0.85, 0.15, "85% Stocks / 15% Index"),
            ],
        }

        mixes = []
        for stock_pct, etf_pct, name in splits.get(risk_profile, splits["balanced"]):
            stock_budget = budget * stock_pct
            etf_budget = budget * etf_pct

            affordable = [
                s for s in stocks
                if s["price"] <= stock_budget and s["score"] > 0
            ]
            stock_picks = self._allocate_equal(affordable[:3], stock_budget)

            # Prefer a Nifty 50 ETF for the index portion
            affordable_etfs = [
                e for e in etfs if 0 < e["price"] <= etf_budget
            ]
            etf_picks = []
            if affordable_etfs:
                nifty_etf = next(
                    (e for e in affordable_etfs if "Nifty 50" in e.get("type", "")),
                    affordable_etfs[0],
                )
                qty = floor(etf_budget / nifty_etf["price"])
                if qty >= 1:
                    etf_picks.append({
                        **nifty_etf,
                        "quantity": qty,
                        "allocation": round(qty * nifty_etf["price"], 2),
                    })

            if stock_picks or etf_picks:
                stock_total = sum(s["allocation"] for s in stock_picks)
                etf_total = sum(e["allocation"] for e in etf_picks)
                mixes.append({
                    "name": name,
                    "description": (
                        f"Split your \u20b9{budget:,.0f} between "
                        f"individual stocks and index ETFs"
                    ),
                    "stock_allocation_pct": stock_pct,
                    "etf_allocation_pct": etf_pct,
                    "stocks": stock_picks,
                    "index_funds": etf_picks,
                    "total_cost": round(stock_total + etf_total, 2),
                    "remaining": round(budget - stock_total - etf_total, 2),
                })

        return mixes

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_batch(
        self,
        stocks_by_sector: dict[str, list[dict]],
        budget: float,
        *,
        name: str,
        description: str,
        risk_level: str,
        max_stocks: int,
        prefer_positive: bool,
    ) -> dict | None:
        """Build a sector-diversified batch."""
        picks = []
        sectors_used: set[str] = set()

        for sector, sector_stocks in stocks_by_sector.items():
            if len(picks) >= max_stocks:
                break
            candidates = sorted(sector_stocks, key=lambda s: s["score"], reverse=True)
            for c in candidates:
                if prefer_positive and c["score"] < 0:
                    continue
                # No single stock should eat more than half the budget
                if c["price"] <= budget / 2:
                    picks.append(c)
                    sectors_used.add(sector)
                    break

        if len(picks) < 2:
            return None

        allocated = self._allocate_equal(picks, budget)
        if not allocated:
            return None

        return {
            "name": name,
            "description": description,
            "risk_level": risk_level,
            "stocks": allocated,
            "total_cost": sum(s["allocation"] for s in allocated),
            "remaining": round(
                budget - sum(s["allocation"] for s in allocated), 2,
            ),
            "num_sectors": len(sectors_used),
        }

    @staticmethod
    def _allocate_equal(picks: list[dict], budget: float) -> list[dict]:
        """Equally distribute budget across a list of picks."""
        if not picks:
            return []
        per_stock = budget / len(picks)
        allocated = []
        for p in picks:
            qty = floor(per_stock / p["price"])
            if qty < 1:
                continue
            allocated.append({
                "symbol": p["symbol"],
                "name": p.get("name", p["symbol"]),
                "sector": p.get("sector", "N/A"),
                "price": p["price"],
                "quantity": qty,
                "allocation": round(qty * p["price"], 2),
                "score": p.get("score", 0),
                "recommendation": p.get("recommendation", "N/A"),
            })
        return allocated
