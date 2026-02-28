"""
In-memory DataFrame cache for efficient intraday + daily data management.

Startup: warm the cache with 60d daily + 5d 15m data for all symbols.
Per-cycle: fetch only the last 1d of 15m candles and append (deduplicate).
"""

import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from typing import Optional

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import INTRADAY_INTERVAL


class DataCache:
    """In-memory cache holding daily and intraday DataFrames per symbol."""

    def __init__(self):
        self.daily_cache: dict[str, pd.DataFrame] = {}
        self.intraday_cache: dict[str, pd.DataFrame] = {}
        self._last_daily_refresh: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def warm_cache(self, symbols: list[str], daily_period: str = "1y",
                   intraday_days: int = 5):
        """
        Initial cache population on startup.
        Fetches daily (60d+) and intraday (5d of 15m) data for all symbols.
        """
        print(f"  [Cache] Warming cache for {len(symbols)} symbols...")

        # Daily data
        for sym in symbols:
            df = self._fetch(sym, period=daily_period, interval="1d")
            if not df.empty:
                self.daily_cache[sym] = df

        # Intraday data
        for sym in symbols:
            df = self._fetch(sym, period=f"{intraday_days}d",
                             interval=INTRADAY_INTERVAL)
            if not df.empty:
                self.intraday_cache[sym] = df

        self._last_daily_refresh = datetime.now()
        print(f"  [Cache] Warm complete: {len(self.daily_cache)} daily, "
              f"{len(self.intraday_cache)} intraday")

    def refresh_intraday(self, symbols: list[str]):
        """
        Incremental intraday refresh — fetch last 1d of 15m candles
        and append to existing cache (deduplicate).
        """
        for sym in symbols:
            df_new = self._fetch(sym, period="1d", interval=INTRADAY_INTERVAL)
            if df_new.empty:
                continue

            if sym in self.intraday_cache:
                existing = self.intraday_cache[sym]
                combined = pd.concat([existing, df_new])
                combined = combined[~combined.index.duplicated(keep="last")]
                combined = combined.sort_index()
                # Keep only last 5 trading days to avoid unbounded growth
                cutoff = pd.Timestamp.now(tz=combined.index.tz) - pd.Timedelta(days=7)
                combined = combined[combined.index >= cutoff]
                self.intraday_cache[sym] = combined
            else:
                self.intraday_cache[sym] = df_new

    def refresh_daily_if_needed(self, symbols: list[str]):
        """Refresh daily cache if it's a new trading day since last refresh."""
        now = datetime.now()
        if (self._last_daily_refresh is None or
                now.date() > self._last_daily_refresh.date()):
            print("  [Cache] New day — refreshing daily data...")
            for sym in symbols:
                df = self._fetch(sym, period="1y", interval="1d")
                if not df.empty:
                    self.daily_cache[sym] = df
            self._last_daily_refresh = now

    def get_daily(self, symbol: str) -> pd.DataFrame:
        """Return cached daily data for a symbol."""
        return self.daily_cache.get(symbol, pd.DataFrame())

    def get_intraday(self, symbol: str) -> pd.DataFrame:
        """Return cached intraday (15m) data for a symbol."""
        return self.intraday_cache.get(symbol, pd.DataFrame())

    def get_previous_day_ohlc(self, symbol: str) -> dict:
        """
        Return previous day's OHLC for Pivot Point calculation.
        Uses the daily cache.
        """
        df = self.get_daily(symbol)
        if df.empty or len(df) < 2:
            return {}

        prev = df.iloc[-2]
        return {
            "open": float(prev.get("open", 0)),
            "high": float(prev.get("high", 0)),
            "low": float(prev.get("low", 0)),
            "close": float(prev.get("close", 0)),
        }

    def has_data(self, symbol: str) -> bool:
        """Check if both daily and intraday data are available."""
        return (symbol in self.daily_cache and not self.daily_cache[symbol].empty
                and symbol in self.intraday_cache and not self.intraday_cache[symbol].empty)

    def get_cached_symbols(self) -> list[str]:
        """Return list of symbols with both daily and intraday data."""
        return [s for s in self.daily_cache if self.has_data(s)]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch(symbol: str, period: str, interval: str) -> pd.DataFrame:
        """Fetch data from yfinance and normalize columns."""
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period=period, interval=interval,
                                  auto_adjust=True)
            if data.empty:
                return pd.DataFrame()

            data.columns = [c.lower() for c in data.columns]
            data.index.name = "date"

            keep = ["open", "high", "low", "close", "volume"]
            data = data[[c for c in keep if c in data.columns]]
            return data

        except Exception as e:
            print(f"  [Cache] Error fetching {symbol} ({interval}): {e}")
            return pd.DataFrame()
