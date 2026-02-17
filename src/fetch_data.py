"""
Standalone Alpha Vantage data fetcher.
Downloads daily OHLCV data for configured stock symbols and saves to CSV.

Usage:
    cd src && python fetch_data.py          # Fetch all symbols from .env
    python main.py fetch                    # Same, from project root
"""

import os
import sys
import time

import pandas as pd
from alpha_vantage.timeseries import TimeSeries

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from settings import ALPHA_VANTAGE_API_KEY, STOCK_SYMBOLS, DEFAULT_OUTPUT_SIZE, RAW_DATA_DIR

ts = TimeSeries(key=ALPHA_VANTAGE_API_KEY, output_format='pandas')


def fetch_daily_stock_data(symbol: str, output_size=DEFAULT_OUTPUT_SIZE) -> pd.DataFrame:
    try:
        print(f"Fetching daily data for {symbol} with output size {output_size}...")
        data = ts.get_daily(symbol=symbol, outputsize=output_size)[0]
        data = data.rename(columns=lambda x: x.split('. ')[1])
        data.index.name = 'date'
        print(f"Data for {symbol} fetched successfully.")
        print(data.head(5))
        return data
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return pd.DataFrame()


def save_to_csv(df: pd.DataFrame, symbol: str):
    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    filename = os.path.join(RAW_DATA_DIR, f"{symbol.replace('.', '_')}.csv")
    if os.path.exists(filename):
        print(f"File {filename} already exists. Updating with new data...")
        existing_df = pd.read_csv(filename, index_col='date', parse_dates=True)
        print(f"Latest date available in file: {existing_df.index.max().strftime('%Y-%m-%d')}")

        new_dates = set(df.index.strftime('%Y-%m-%d')) - set(existing_df.index.strftime('%Y-%m-%d'))
        data_to_add = pd.DataFrame()
        if new_dates:
            print(f"New dates added for {symbol}: {sorted(new_dates)}")
            data_to_add = df[df.index.strftime('%Y-%m-%d').isin(new_dates)]

        combined_df = pd.concat([existing_df, data_to_add]).sort_index(ascending=False)
        combined_df.to_csv(filename)
    else:
        df.to_csv(filename)
    print(f"Saved {symbol} to {filename}")


def fetch_multiple_stocks(symbols: list[str]):
    for symbol in symbols:
        print(f"\nFetching {symbol}...")
        df = fetch_daily_stock_data(symbol)

        if not df.empty:
            save_to_csv(df, symbol)
        time.sleep(15)  # Respect Alpha Vantage rate limits (5 calls/min)


if __name__ == "__main__":
    fetch_multiple_stocks(STOCK_SYMBOLS)
