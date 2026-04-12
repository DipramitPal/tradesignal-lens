"""
Stock data fetcher using yfinance.
Downloads daily OHLCV data for configured stock symbols and saves to CSV.
No API key required — yfinance pulls from Yahoo Finance.

Usage:
    cd src && python fetch_data.py          # Fetch all symbols from .env
    python main.py fetch                    # Same, from project root
"""

import os
import sys

import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from settings import STOCK_SYMBOLS, RAW_DATA_DIR


def fetch_daily_stock_data(symbol: str, period: str = "1y") -> pd.DataFrame:
    """
    Fetch daily OHLCV data for a single stock via yfinance.

    Args:
        symbol: yfinance symbol (e.g. "RELIANCE.NS")
        period: Data period — 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,max

    Returns:
        DataFrame with OHLCV columns indexed by date.
    """
    try:
        print(f"Fetching daily data for {symbol} (period={period})...")
        ticker = yf.Ticker(symbol)
        data = ticker.history(period=period, auto_adjust=True)

        if data.empty:
            print(f"  No data returned for {symbol}")
            return pd.DataFrame()

        # Normalize column names to lowercase
        data.columns = [c.lower() for c in data.columns]
        data.index.name = "date"

        # Keep only OHLCV
        keep = ["open", "high", "low", "close", "volume"]
        data = data[[c for c in keep if c in data.columns]]

        print(f"  Fetched {len(data)} rows for {symbol}")
        print(data.tail(5))
        return data
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return pd.DataFrame()


def save_to_csv(df: pd.DataFrame, symbol: str):
    """Save or merge DataFrame into a CSV in the raw data directory."""
    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    filename = os.path.join(RAW_DATA_DIR, f"{symbol.replace('.', '_')}.csv")

    if os.path.exists(filename):
        print(f"  File {filename} already exists. Merging new data...")
        existing_df = pd.read_csv(filename, index_col="date", parse_dates=True)
        print(f"  Latest date in file: {existing_df.index.max().strftime('%Y-%m-%d')}")

        new_dates = set(df.index.strftime("%Y-%m-%d")) - set(
            existing_df.index.strftime("%Y-%m-%d")
        )
        data_to_add = pd.DataFrame()
        if new_dates:
            print(f"  New dates added for {symbol}: {sorted(new_dates)}")
            data_to_add = df[df.index.strftime("%Y-%m-%d").isin(new_dates)]

        combined_df = pd.concat([existing_df, data_to_add]).sort_index(ascending=False)
        combined_df.to_csv(filename)
    else:
        df.to_csv(filename)

    print(f"  Saved {symbol} to {filename}")


def fetch_multiple_stocks(symbols: list[str], period: str = "1y"):
    """Fetch and save data for multiple stocks."""
    for symbol in symbols:
        print(f"\nFetching {symbol}...")
        df = fetch_daily_stock_data(symbol, period=period)
        if not df.empty:
            save_to_csv(df, symbol)


if __name__ == "__main__":
    fetch_multiple_stocks(STOCK_SYMBOLS)
