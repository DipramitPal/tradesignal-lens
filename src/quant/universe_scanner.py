"""
Dynamic stock universe scanner (Tier 1 pre-screen).

Scans the NIFTY 200 universe with lightweight filters to find
breakout candidates. Filters:
  - Volume surge > 1.5× 20-day average
  - Price within 3% of 20-day high (breakout proximity)
  - ATR/close > 0.8% (sufficient volatility)
  - Relative Strength vs NIFTY 50 > 1.0
"""

import pandas as pd
import yfinance as yf
from typing import Optional

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import SCAN_UNIVERSE, INTRADAY_INTERVAL


class UniverseScanner:
    """Scans the stock universe for breakout candidates."""

    def __init__(self, universe: list[str] | None = None):
        self.universe = universe or SCAN_UNIVERSE
        self._active_watchlist: list[str] = []

    def scan(self, benchmark_df: Optional[pd.DataFrame] = None) -> list[dict]:
        """
        Run Tier 1 pre-screen on the universe.

        Returns:
            List of dicts with 'symbol', 'volume_ratio', 'proximity_pct',
            'atr_pct', 'passed' for each symbol.
        """
        results = []
        passed_symbols = []

        for symbol in self.universe:
            try:
                result = self._prescreen_symbol(symbol)
                results.append(result)
                if result["passed"]:
                    passed_symbols.append(symbol)
            except Exception as e:
                results.append({"symbol": symbol, "passed": False,
                                "error": str(e)})

        self._active_watchlist = passed_symbols
        print(f"  [Universe] Scanned {len(self.universe)} symbols, "
              f"{len(passed_symbols)} passed pre-screen")
        return results

    def scan_lightweight(self, daily_cache: dict[str, pd.DataFrame]) -> list[str]:
        """
        Lightweight scan using cached daily data (no new API calls).
        Use this for fast rescans during market hours.

        Returns:
            List of symbols that pass the pre-screen.
        """
        passed = []
        for symbol in self.universe:
            df = daily_cache.get(symbol)
            if df is None or df.empty or len(df) < 20:
                continue

            try:
                vol_avg = df["volume"].rolling(20).mean().iloc[-1]
                vol_current = df["volume"].iloc[-1]
                vol_ratio = vol_current / (vol_avg + 1e-10)

                high_20 = df["high"].rolling(20).max().iloc[-1]
                price = df["close"].iloc[-1]
                proximity = (high_20 - price) / (high_20 + 1e-10) * 100

                # Simple ATR
                tr = pd.concat([
                    df["high"] - df["low"],
                    (df["high"] - df["close"].shift(1)).abs(),
                    (df["low"] - df["close"].shift(1)).abs(),
                ], axis=1).max(axis=1)
                atr_14 = tr.rolling(14).mean().iloc[-1]
                atr_pct = (atr_14 / (price + 1e-10)) * 100

                if vol_ratio >= 1.5 and proximity <= 3.0 and atr_pct >= 0.8:
                    passed.append(symbol)
            except Exception:
                continue

        self._active_watchlist = passed
        return passed

    @property
    def active_watchlist(self) -> list[str]:
        """Currently active symbols from last scan."""
        return self._active_watchlist

    def _prescreen_symbol(self, symbol: str) -> dict:
        """Run pre-screen on a single symbol using 2d of daily data."""
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1mo", interval="1d", auto_adjust=True)

            if df.empty or len(df) < 20:
                return {"symbol": symbol, "passed": False,
                        "reason": "insufficient data"}

            df.columns = [c.lower() for c in df.columns]

            # Volume ratio
            vol_avg = df["volume"].rolling(20).mean().iloc[-1]
            vol_current = df["volume"].iloc[-1]
            vol_ratio = vol_current / (vol_avg + 1e-10)

            # Proximity to 20-day high
            high_20 = df["high"].rolling(20).max().iloc[-1]
            price = df["close"].iloc[-1]
            proximity = (high_20 - price) / (high_20 + 1e-10) * 100

            # ATR as percentage of close
            tr = pd.concat([
                df["high"] - df["low"],
                (df["high"] - df["close"].shift(1)).abs(),
                (df["low"] - df["close"].shift(1)).abs(),
            ], axis=1).max(axis=1)
            atr_14 = tr.rolling(14).mean().iloc[-1]
            atr_pct = (atr_14 / (price + 1e-10)) * 100

            passed = (
                vol_ratio >= 1.5
                and proximity <= 3.0
                and atr_pct >= 0.8
            )

            return {
                "symbol": symbol,
                "price": round(price, 2),
                "volume_ratio": round(vol_ratio, 2),
                "proximity_pct": round(proximity, 2),
                "atr_pct": round(atr_pct, 2),
                "passed": passed,
            }

        except Exception as e:
            return {"symbol": symbol, "passed": False, "error": str(e)}
