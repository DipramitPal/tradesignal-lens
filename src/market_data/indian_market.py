"""
Indian stock market data fetcher using Alpha Vantage.
Supports NSE and BSE listed stocks and historical data.

Data flow:
  1. Run fetch_data.py (or `python main.py fetch`) to download OHLCV CSVs
  2. This module loads from those CSVs for analysis
  3. Falls back to live Alpha Vantage API if no local data exists
"""

import os
import time
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import (
    ALPHA_VANTAGE_API_KEY, DEFAULT_OUTPUT_SIZE,
    RAW_DATA_DIR, PROCESSED_DATA_DIR, STOCK_SYMBOLS,
)


class IndianMarketData:
    """Fetches and manages Indian stock market data via Alpha Vantage."""

    # Periods that fit within Alpha Vantage "compact" (100 data points)
    COMPACT_PERIODS = {"1d", "5d", "1mo", "3mo"}

    # Map period strings to approximate calendar days
    PERIOD_DAYS = {
        "1d": 1, "5d": 5, "1mo": 30, "3mo": 90,
        "6mo": 180, "1y": 365, "2y": 730, "5y": 1825,
        "10y": 3650,
    }

    def __init__(self, symbols: list[str] | None = None):
        self.symbols = symbols or STOCK_SYMBOLS
        RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
        PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

        self._ts = None
        if ALPHA_VANTAGE_API_KEY:
            try:
                from alpha_vantage.timeseries import TimeSeries
                self._ts = TimeSeries(
                    key=ALPHA_VANTAGE_API_KEY, output_format="pandas"
                )
            except ImportError:
                print("  Warning: alpha_vantage package not installed")

    def fetch_stock(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV data for a single stock.

        Loads from local CSV first (populated by fetch_data.py).
        Falls back to live Alpha Vantage API call if no local data exists.

        Args:
            symbol: Alpha Vantage symbol (e.g. "RELIANCE.BSE")
            period: Data period - 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,max
            interval: Ignored (Alpha Vantage daily only), kept for API compat

        Returns:
            DataFrame with OHLCV data, indexed by Date.
        """
        # Try loading from CSV first
        df = self.load_stock_data(symbol)
        if not df.empty:
            df = self._trim_to_period(df, period)
            if not df.empty:
                print(f"  Loaded {len(df)} rows for {symbol} from CSV")
                return df

        # Fall back to live Alpha Vantage fetch
        if self._ts is None:
            print(f"  No local data and no Alpha Vantage API configured for {symbol}")
            return pd.DataFrame()

        return self._fetch_live(symbol, period)

    def _fetch_live(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        """Fetch live daily data from Alpha Vantage API."""
        try:
            output_size = "compact" if period in self.COMPACT_PERIODS else "full"
            print(f"  Fetching {symbol} from Alpha Vantage ({output_size})...")
            data = self._ts.get_daily(symbol=symbol, outputsize=output_size)[0]

            # Alpha Vantage columns: "1. open", "2. high", etc.
            data = data.rename(
                columns=lambda x: x.split(". ")[1] if ". " in x else x
            )
            data.index.name = "date"

            # Keep only OHLCV
            keep_cols = ["open", "high", "low", "close", "volume"]
            data = data[[c for c in keep_cols if c in data.columns]]

            # Trim to requested period
            data = self._trim_to_period(data, period)

            # Save to CSV for future use
            self._save_csv(data, symbol)

            print(f"  Fetched {len(data)} rows for {symbol}")
            return data

        except Exception as e:
            print(f"  Error fetching {symbol}: {e}")
            return pd.DataFrame()

    def fetch_multiple(
        self,
        symbols: list[str] | None = None,
        period: str = "1y",
        interval: str = "1d",
        save: bool = True,
    ) -> dict[str, pd.DataFrame]:
        """Fetch data for multiple stocks (from CSV or live API)."""
        symbols = symbols or self.symbols
        results = {}

        for symbol in symbols:
            print(f"Fetching {symbol}...")
            df = self.fetch_stock(symbol, period=period, interval=interval)
            if not df.empty:
                results[symbol] = df
                if save:
                    self._save_csv(df, symbol)
            # Rate limit if fetching live
            if self._ts and df.empty:
                time.sleep(15)

        print(f"\nLoaded data for {len(results)}/{len(symbols)} stocks")
        return results

    def fetch_indices(self, period: str = "1y") -> dict[str, pd.DataFrame]:
        """
        Fetch major Indian index data.
        Note: Alpha Vantage has limited free-tier index support.
        Returns whatever is available from CSV or API.
        """
        index_symbols = {
            "SENSEX": "BSE:SENSEX",
            "NIFTY_50": "^NSEI",
            "NIFTY_BANK": "^NSEBANK",
        }
        results = {}
        for name, symbol in index_symbols.items():
            df = self.load_stock_data(symbol)
            if not df.empty:
                df = self._trim_to_period(df, period)
                print(f"  Loaded index {name} from CSV ({len(df)} rows)")
                results[name] = df
        return results

    def get_stock_info(self, symbol: str) -> dict:
        """
        Get basic info about a stock.
        Uses local CSV data for price info. Tries Alpha Vantage
        company overview API if available (uses 1 API call).
        """
        # Start with basic info from CSV
        info = self._basic_info(symbol)

        # Optionally enrich with Alpha Vantage overview
        if ALPHA_VANTAGE_API_KEY:
            try:
                from alpha_vantage.fundamentaldata import FundamentalData
                fd = FundamentalData(
                    key=ALPHA_VANTAGE_API_KEY, output_format="json"
                )
                overview, _ = fd.get_company_overview(symbol=symbol)
                if overview:
                    info["name"] = overview.get("Name", info["name"])
                    info["sector"] = overview.get("Sector", "N/A")
                    info["industry"] = overview.get("Industry", "N/A")
                    info["market_cap"] = int(
                        overview.get("MarketCapitalization", 0) or 0
                    )
                    info["pe_ratio"] = float(
                        overview.get("PERatio", 0) or 0
                    )
                    info["52w_high"] = float(
                        overview.get("52WeekHigh", 0) or 0
                    )
                    info["52w_low"] = float(
                        overview.get("52WeekLow", 0) or 0
                    )
                    info["dividend_yield"] = float(
                        overview.get("DividendYield", 0) or 0
                    )
                    info["currency"] = overview.get("Currency", "INR")
            except Exception as e:
                print(f"  Could not fetch overview for {symbol}: {e}")

        return info

    def _basic_info(self, symbol: str) -> dict:
        """Return basic info derived from the symbol and local CSV data."""
        df = self.load_stock_data(symbol)
        current_price = float(df.iloc[-1]["close"]) if not df.empty else 0

        # Derive a readable name from the symbol (e.g. "RELIANCE.BSE" -> "RELIANCE")
        name = symbol.split(".")[0].replace("_", " ")

        return {
            "symbol": symbol,
            "name": name,
            "sector": "N/A",
            "industry": "N/A",
            "market_cap": 0,
            "current_price": current_price,
            "pe_ratio": 0,
            "52w_high": float(df["close"].max()) if not df.empty else 0,
            "52w_low": float(df["close"].min()) if not df.empty else 0,
            "dividend_yield": 0,
            "currency": "INR",
        }

    def load_stock_data(
        self, symbol: str, processed: bool = False
    ) -> pd.DataFrame:
        """Load previously saved stock data from CSV."""
        base_dir = PROCESSED_DATA_DIR if processed else RAW_DATA_DIR
        filename = f"{symbol.replace('.', '_')}.csv"
        filepath = base_dir / filename

        if not filepath.exists():
            return pd.DataFrame()

        df = pd.read_csv(filepath, index_col=0, parse_dates=True)
        df.index.name = "date"

        # Normalize column names to lowercase
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]

        # Keep only OHLCV columns if present
        keep_cols = ["open", "high", "low", "close", "volume"]
        available = [c for c in keep_cols if c in df.columns]
        if available:
            df = df[available]

        return df

    def _save_csv(self, df: pd.DataFrame, symbol: str):
        """Save DataFrame to CSV in raw data directory."""
        filename = f"{symbol.replace('.', '_')}.csv"
        filepath = RAW_DATA_DIR / filename
        df.to_csv(filepath)
        print(f"  Saved to {filepath}")

    @staticmethod
    def _trim_to_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
        """Trim DataFrame to approximate the requested period."""
        if df.empty:
            return df

        days = IndianMarketData.PERIOD_DAYS.get(period)
        if days is None:
            # "ytd", "max", or unknown → return all data
            return df

        # Sort ascending for date comparison
        df_sorted = df.sort_index(ascending=True)
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=days)
        trimmed = df_sorted[df_sorted.index >= cutoff]

        return trimmed if not trimmed.empty else df_sorted
