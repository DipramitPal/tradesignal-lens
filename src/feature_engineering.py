# Feature Engineering for Time Series Data to add Technical Indicators like OHLCV, RSI, MACD, EMA-12, EMA-26, and Bollinger Bands, 5 day Momentum, and 5 day Volume Momentum, Volataility, and Volume Volatility
# Edit code to do without pandas_ta

import pandas as pd
import numpy as np
from typing import List, Dict
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), '..')))
from config import ALPHA_VANTAGE_API_KEY, STOCK_SYMBOLS, DEFAULT_OUTPUT_SIZE, RAW_DATA_DIR



def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add technical indicators to the DataFrame without using pandas_ta.

    Parameters:
    df (pd.DataFrame): DataFrame with columns ['open', 'high', 'low', 'close', 'volume'].

    Returns:
    pd.DataFrame: DataFrame with added indicators.
    """
    required_columns = ['open', 'high', 'low', 'close', 'volume']
    if not all(col in df.columns for col in required_columns):
        raise ValueError(f"DataFrame must contain columns: {required_columns}")

    # RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0).rolling(window=14).mean()
    loss = -delta.clip(upper=0).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # MACD
    ema_12 = df['close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['close'].ewm(span=26, adjust=False).mean()
    df['ema_12'] = ema_12
    df['ema_26'] = ema_26
    df['macd'] = ema_12 - ema_26
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']

    # Bollinger Bands
    rolling_mean = df['close'].rolling(window=20).mean()
    rolling_std = df['close'].rolling(window=20).std()
    df['bb_high'] = rolling_mean + 2 * rolling_std
    df['bb_low'] = rolling_mean - 2 * rolling_std

    # 5-day Momentum
    df['momentum_5'] = df['close'] - df['close'].shift(5)

    # 5-day Volume Momentum
    df['volume_momentum_5'] = df['volume'] - df['volume'].shift(5)

    # Volatility
    df['volatility'] = df['close'].rolling(window=20).std()

    # Volume Volatility
    df['volume_volatility'] = df['volume'].rolling(window=20).std()

    return df

def process_all_stocks():
    raw_dir = RAW_DATA_DIR
    processed_dir = raw_dir.replace("raw", "processed")
    os.makedirs(processed_dir, exist_ok=True)

    for filename in os.listdir(raw_dir):
        if filename.endswith(".csv"):
            symbol = filename.replace(".csv", "").replace("_", ".")
            print(f"Processing {symbol}")
            df = pd.read_csv(os.path.join(raw_dir, filename), index_col='Date', parse_dates=True)
            df.columns = df.columns.str.lower()

            try:
                df_feat = add_technical_indicators(df)
                df_feat.dropna(inplace=True)
                df_feat.to_csv(os.path.join(processed_dir, filename))
            except Exception as e:
                print(f"Failed to process {symbol}: {e}")

if __name__ == "__main__":
    process_all_stocks()