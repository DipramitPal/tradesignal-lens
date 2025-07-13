# %%
import os
import time

# %%
#Read fom Alpha Vantage API
from alpha_vantage.timeseries import TimeSeries
import pandas as pd

# %%
import sys
import sys
import os

# Add the parent directory to sys.path so you can import from src
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), '..')))


# %%

from src.config import ALPHA_VANTAGE_API_KEY, STOCK_SYMBOLS, DEFAULT_OUTPUT_SIZE, RAW_DATA_DIR

# %%
ts = TimeSeries(key=ALPHA_VANTAGE_API_KEY, output_format='pandas')

# %%
def fetch_daily_stock_data(symbol: str, output_size=DEFAULT_OUTPUT_SIZE) -> pd.DataFrame:
    try:
        print(f"Fetching daily data for {symbol} with output size {output_size}...")
        data= ts.get_daily(symbol=symbol, outputsize=output_size)[0]
        data = data.rename(columns=lambda x: x.split('. ')[1])
        data.index.name = 'Date'
        print(f"Data for {symbol} fetched successfully.")
        print(data.head(5))
        return data
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return pd.DataFrame()

def save_to_csv(df: pd.DataFrame, symbol: str):
    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    filename = os.path.join(RAW_DATA_DIR, f"{symbol.replace('.', '_')}.csv").replace("\\", "/")
    df.to_csv(filename)

def fetch_multiple_stocks(symbols: list[str]):
    for symbol in symbols:
        print(f"Fetching {symbol}...")
        df = fetch_daily_stock_data(symbol)
        
        if not df.empty:
            save_to_csv(df, symbol)
        time.sleep(15)  # Respect rate limits

# %%
if __name__ == "__main__":
    fetch_multiple_stocks(STOCK_SYMBOLS)


