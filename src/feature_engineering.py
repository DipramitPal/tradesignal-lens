"""
Feature engineering for time series data.

Adds technical indicators computed with pure pandas/numpy:
  - RSI, MACD, EMA-12/26/50/200, Bollinger Bands
  - ATR (Average True Range) for stop-loss calculation
  - ADX (Average Directional Index) for trend strength
  - VWAP (Volume Weighted Average Price)
  - Supertrend indicator
  - Support & resistance levels
  - Momentum, volume momentum, volatility
"""

import pandas as pd
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from settings import RAW_DATA_DIR, PROCESSED_DATA_DIR


def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add technical indicators to the DataFrame.

    Parameters:
        df: DataFrame with columns ['open', 'high', 'low', 'close', 'volume'].

    Returns:
        DataFrame with added indicators.
    """
    required_columns = ["open", "high", "low", "close", "volume"]
    if not all(col in df.columns for col in required_columns):
        raise ValueError(f"DataFrame must contain columns: {required_columns}")

    # --- RSI (14-period) ---
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(window=14).mean()
    loss = -delta.clip(upper=0).rolling(window=14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    # --- MACD ---
    ema_12 = df["close"].ewm(span=12, adjust=False).mean()
    ema_26 = df["close"].ewm(span=26, adjust=False).mean()
    df["ema_12"] = ema_12
    df["ema_26"] = ema_26
    df["macd"] = ema_12 - ema_26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # --- EMA-50 and EMA-200 (for golden/death cross) ---
    df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()

    # --- Bollinger Bands (20-period, 2σ) ---
    rolling_mean = df["close"].rolling(window=20).mean()
    rolling_std = df["close"].rolling(window=20).std()
    df["bb_mid"] = rolling_mean
    df["bb_high"] = rolling_mean + 2 * rolling_std
    df["bb_low"] = rolling_mean - 2 * rolling_std

    # --- ATR (Average True Range, 14-period) ---
    high_low = df["high"] - df["low"]
    high_close_prev = (df["high"] - df["close"].shift(1)).abs()
    low_close_prev = (df["low"] - df["close"].shift(1)).abs()
    true_range = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(
        axis=1
    )
    df["atr"] = true_range.rolling(window=14).mean()

    # --- ADX (Average Directional Index, 14-period) ---
    df["adx"] = _compute_adx(df, period=14)

    # --- VWAP (Volume Weighted Average Price) ---
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cum_tp_vol = (typical_price * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum()
    df["vwap"] = cum_tp_vol / cum_vol

    # --- Supertrend (10-period, multiplier=3) ---
    st_period = 10
    st_multiplier = 3.0
    df["supertrend"], df["supertrend_direction"] = _compute_supertrend(
        df, st_period, st_multiplier
    )

    # --- Support & Resistance (20-period rolling) ---
    df["support"] = df["low"].rolling(window=20).min()
    df["resistance"] = df["high"].rolling(window=20).max()

    # --- 5-day Momentum ---
    df["momentum_5"] = df["close"] - df["close"].shift(5)

    # --- 5-day Volume Momentum ---
    df["volume_momentum_5"] = df["volume"] - df["volume"].shift(5)

    # --- Volatility (20-period rolling std) ---
    df["volatility"] = df["close"].rolling(window=20).std()

    # --- Volume Volatility ---
    df["volume_volatility"] = df["volume"].rolling(window=20).std()

    return df


def _compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute Average Directional Index (ADX)."""
    plus_dm = df["high"].diff()
    minus_dm = -df["low"].diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    high_low = df["high"] - df["low"]
    high_close_prev = (df["high"] - df["close"].shift(1)).abs()
    low_close_prev = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_di = 100 * (
        plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr
    )
    minus_di = 100 * (
        minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr
    )

    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1))
    adx = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return adx


def _compute_supertrend(
    df: pd.DataFrame, period: int = 10, multiplier: float = 3.0
) -> tuple[pd.Series, pd.Series]:
    """
    Compute Supertrend indicator.

    Returns:
        (supertrend_value, direction) where direction = 1 (bullish) or -1 (bearish)
    """
    hl2 = (df["high"] + df["low"]) / 2
    high_low = df["high"] - df["low"]
    high_close_prev = (df["high"] - df["close"].shift(1)).abs()
    low_close_prev = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()

    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    supertrend = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=float)

    supertrend.iloc[0] = upper_band.iloc[0]
    direction.iloc[0] = -1

    for i in range(1, len(df)):
        if pd.isna(upper_band.iloc[i]) or pd.isna(lower_band.iloc[i]):
            supertrend.iloc[i] = np.nan
            direction.iloc[i] = direction.iloc[i - 1] if i > 0 else -1
            continue

        # Adjust bands
        if lower_band.iloc[i] > lower_band.iloc[i - 1] or pd.isna(
            lower_band.iloc[i - 1]
        ):
            final_lower = lower_band.iloc[i]
        else:
            final_lower = max(lower_band.iloc[i], lower_band.iloc[i - 1])

        if upper_band.iloc[i] < upper_band.iloc[i - 1] or pd.isna(
            upper_band.iloc[i - 1]
        ):
            final_upper = upper_band.iloc[i]
        else:
            final_upper = min(upper_band.iloc[i], upper_band.iloc[i - 1])

        close_val = df["close"].iloc[i]

        if supertrend.iloc[i - 1] == upper_band.iloc[i - 1]:
            # Was bearish
            if close_val > final_upper:
                supertrend.iloc[i] = final_lower
                direction.iloc[i] = 1
            else:
                supertrend.iloc[i] = final_upper
                direction.iloc[i] = -1
        else:
            # Was bullish
            if close_val < final_lower:
                supertrend.iloc[i] = final_upper
                direction.iloc[i] = -1
            else:
                supertrend.iloc[i] = final_lower
                direction.iloc[i] = 1

    return supertrend, direction


def process_all_stocks():
    raw_dir = RAW_DATA_DIR
    processed_dir = PROCESSED_DATA_DIR
    os.makedirs(processed_dir, exist_ok=True)

    for filename in os.listdir(raw_dir):
        if filename.endswith(".csv"):
            symbol = filename.replace(".csv", "").replace("_", ".")
            print(f"Processing {symbol}")
            df = pd.read_csv(
                os.path.join(raw_dir, filename), index_col="Date", parse_dates=True
            )
            df.columns = df.columns.str.lower()

            try:
                df_feat = add_technical_indicators(df)
                df_feat.dropna(inplace=True)
                df_feat.to_csv(os.path.join(processed_dir, filename))
            except Exception as e:
                print(f"Failed to process {symbol}: {e}")


if __name__ == "__main__":
    process_all_stocks()
