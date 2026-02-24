"""
Indian stock market data fetcher using yfinance.
Supports NSE and BSE listed stocks and historical data.
No API key required — yfinance pulls directly from Yahoo Finance.

Data flow:
  1. Run fetch_data.py (or `python main.py fetch`) to download OHLCV CSVs
  2. This module loads from those CSVs for analysis
  3. Falls back to live yfinance API call if no local data exists
"""

import os
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import RAW_DATA_DIR, PROCESSED_DATA_DIR, STOCK_SYMBOLS


class IndianMarketData:
    """Fetches and manages Indian stock market data via yfinance."""

    # Map period strings to approximate calendar days
    PERIOD_DAYS = {
        "1d": 1, "5d": 5, "1mo": 30, "3mo": 90,
        "6mo": 180, "1y": 365, "2y": 730, "5y": 1825,
        "10y": 3650,
    }

    # Valid yfinance period values
    VALID_PERIODS = {
        "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "max",
    }

    def __init__(self, symbols: list[str] | None = None):
        self.symbols = symbols or STOCK_SYMBOLS
        RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
        PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

    def fetch_stock(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV data for a single stock.

        Loads from local CSV first (populated by fetch_data.py).
        Falls back to live yfinance API call if no local data exists.

        Args:
            symbol: yfinance symbol (e.g. "RELIANCE.NS")
            period: Data period - 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,max
            interval: Data interval - 1d (daily) is default

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

        # Fall back to live yfinance fetch
        return self._fetch_live(symbol, period, interval)

    def _fetch_live(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> pd.DataFrame:
        """Fetch live data from yfinance."""
        try:
            yf_period = period if period in self.VALID_PERIODS else "1y"
            print(f"  Fetching {symbol} from yfinance (period={yf_period}, interval={interval})...")

            ticker = yf.Ticker(symbol)
            data = ticker.history(period=yf_period, interval=interval, auto_adjust=True)

            if data.empty:
                print(f"  No data returned for {symbol}")
                return pd.DataFrame()

            # Normalize columns
            data.columns = [c.lower() for c in data.columns]
            data.index.name = "date"

            # Keep only OHLCV
            keep_cols = ["open", "high", "low", "close", "volume"]
            data = data[[c for c in keep_cols if c in data.columns]]

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

        print(f"\nLoaded data for {len(results)}/{len(symbols)} stocks")
        return results

    def fetch_indices(self, period: str = "1y") -> dict[str, pd.DataFrame]:
        """
        Fetch major Indian index data via yfinance.
        yfinance supports NSE indices directly.
        """
        index_symbols = {
            "SENSEX": "^BSESN",
            "NIFTY_50": "^NSEI",
            "NIFTY_BANK": "^NSEBANK",
        }
        results = {}
        for name, symbol in index_symbols.items():
            try:
                # Try CSV first
                df = self.load_stock_data(symbol)
                if not df.empty:
                    df = self._trim_to_period(df, period)
                    if not df.empty:
                        print(f"  Loaded index {name} from CSV ({len(df)} rows)")
                        results[name] = df
                        continue

                # Fetch live
                ticker = yf.Ticker(symbol)
                data = ticker.history(period=period, auto_adjust=True)
                if not data.empty:
                    data.columns = [c.lower() for c in data.columns]
                    data.index.name = "date"
                    keep = ["open", "high", "low", "close", "volume"]
                    data = data[[c for c in keep if c in data.columns]]
                    results[name] = data
                    self._save_csv(data, symbol)
                    print(f"  Fetched index {name} ({len(data)} rows)")
            except Exception as e:
                print(f"  Error fetching index {name}: {e}")

        return results

    def get_stock_info(self, symbol: str) -> dict:
        """
        Get basic info about a stock using yfinance.
        Combines local CSV price data with yfinance metadata.
        """
        info = self._basic_info(symbol)

        try:
            ticker = yf.Ticker(symbol)
            yf_info = ticker.info
            if yf_info:
                info["name"] = yf_info.get("shortName", info["name"])
                info["sector"] = yf_info.get("sector", "N/A")
                info["industry"] = yf_info.get("industry", "N/A")
                info["market_cap"] = int(yf_info.get("marketCap", 0) or 0)
                info["pe_ratio"] = float(yf_info.get("trailingPE", 0) or 0)
                info["52w_high"] = float(yf_info.get("fiftyTwoWeekHigh", 0) or 0)
                info["52w_low"] = float(yf_info.get("fiftyTwoWeekLow", 0) or 0)
                info["dividend_yield"] = float(
                    yf_info.get("dividendYield", 0) or 0
                )
                info["currency"] = yf_info.get("currency", "INR")
                info["current_price"] = float(
                    yf_info.get("currentPrice", 0)
                    or yf_info.get("regularMarketPrice", 0)
                    or info["current_price"]
                )
        except Exception as e:
            print(f"  Could not fetch info for {symbol}: {e}")

        return info

    def _basic_info(self, symbol: str) -> dict:
        """Return basic info derived from the symbol and local CSV data."""
        df = self.load_stock_data(symbol)
        current_price = float(df.iloc[-1]["close"]) if not df.empty else 0

        # Derive a readable name from the symbol (e.g. "RELIANCE.NS" -> "RELIANCE")
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
