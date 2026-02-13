"""
Indian stock market data fetcher using yfinance.
Supports NSE and BSE listed stocks, indices, and historical data.
"""

import os
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from pathlib import Path

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import RAW_DATA_DIR, PROCESSED_DATA_DIR, NIFTY_50, SENSEX, NIFTY_BANK


class IndianMarketData:
    """Fetches and manages Indian stock market data via yfinance."""

    def __init__(self, symbols: list[str] | None = None):
        from settings import STOCK_SYMBOLS
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

        Args:
            symbol: Yahoo Finance symbol (e.g. "RELIANCE.NS" for NSE)
            period: Data period - 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max
            interval: Data interval - 1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo

        Returns:
            DataFrame with OHLCV data, indexed by Date.
        """
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)
            if df.empty:
                print(f"  No data returned for {symbol}")
                return pd.DataFrame()

            # Standardize column names to lowercase
            df.columns = [c.lower().replace(" ", "_") for c in df.columns]

            # Keep only OHLCV columns
            keep_cols = ["open", "high", "low", "close", "volume"]
            df = df[[c for c in keep_cols if c in df.columns]]

            df.index.name = "date"
            print(f"  Fetched {len(df)} rows for {symbol}")
            return df

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
        """Fetch data for multiple stocks and optionally save to CSV."""
        symbols = symbols or self.symbols
        results = {}

        for symbol in symbols:
            print(f"Fetching {symbol}...")
            df = self.fetch_stock(symbol, period=period, interval=interval)
            if not df.empty:
                results[symbol] = df
                if save:
                    self._save_csv(df, symbol)

        print(f"\nFetched data for {len(results)}/{len(symbols)} stocks")
        return results

    def fetch_indices(self, period: str = "1y") -> dict[str, pd.DataFrame]:
        """Fetch major Indian index data (Nifty 50, Sensex, Bank Nifty)."""
        indices = {
            "NIFTY_50": NIFTY_50,
            "SENSEX": SENSEX,
            "NIFTY_BANK": NIFTY_BANK,
        }
        results = {}
        for name, symbol in indices.items():
            print(f"Fetching index {name}...")
            df = self.fetch_stock(symbol, period=period)
            if not df.empty:
                results[name] = df
        return results

    def get_stock_info(self, symbol: str) -> dict:
        """Get detailed info about a stock (sector, market cap, etc.)."""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            return {
                "symbol": symbol,
                "name": info.get("longName", "N/A"),
                "sector": info.get("sector", "N/A"),
                "industry": info.get("industry", "N/A"),
                "market_cap": info.get("marketCap", 0),
                "current_price": info.get("currentPrice", 0),
                "pe_ratio": info.get("trailingPE", 0),
                "52w_high": info.get("fiftyTwoWeekHigh", 0),
                "52w_low": info.get("fiftyTwoWeekLow", 0),
                "dividend_yield": info.get("dividendYield", 0),
                "currency": info.get("currency", "INR"),
            }
        except Exception as e:
            print(f"  Error fetching info for {symbol}: {e}")
            return {"symbol": symbol, "error": str(e)}

    def load_stock_data(self, symbol: str, processed: bool = False) -> pd.DataFrame:
        """Load previously saved stock data from CSV."""
        base_dir = PROCESSED_DATA_DIR if processed else RAW_DATA_DIR
        filename = f"{symbol.replace('.', '_')}.csv"
        filepath = base_dir / filename

        if not filepath.exists():
            print(f"  No saved data for {symbol} at {filepath}")
            return pd.DataFrame()

        df = pd.read_csv(filepath, index_col="date", parse_dates=True)
        return df

    def _save_csv(self, df: pd.DataFrame, symbol: str):
        """Save DataFrame to CSV in raw data directory."""
        filename = f"{symbol.replace('.', '_')}.csv"
        filepath = RAW_DATA_DIR / filename
        df.to_csv(filepath)
        print(f"  Saved to {filepath}")
