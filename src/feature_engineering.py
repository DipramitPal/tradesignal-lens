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

    # =====================================================================
    # NEW INDICATORS (v2 – hedge-fund-grade quant stack)
    # =====================================================================

    # --- EMA-9 and EMA-21 (fast intraday trend) ---
    df["ema_9"] = df["close"].ewm(span=9, adjust=False).mean()
    df["ema_21"] = df["close"].ewm(span=21, adjust=False).mean()

    # --- Bollinger Band Width (squeeze detection) ---
    if "bb_high" in df.columns and "bb_low" in df.columns and "bb_mid" in df.columns:
        df["bb_width"] = (df["bb_high"] - df["bb_low"]) / df["bb_mid"]

    # --- On-Balance Volume (OBV) ---
    obv = pd.Series(0.0, index=df.index)
    obv.iloc[0] = df["volume"].iloc[0]
    for i in range(1, len(df)):
        if df["close"].iloc[i] > df["close"].iloc[i - 1]:
            obv.iloc[i] = obv.iloc[i - 1] + df["volume"].iloc[i]
        elif df["close"].iloc[i] < df["close"].iloc[i - 1]:
            obv.iloc[i] = obv.iloc[i - 1] - df["volume"].iloc[i]
        else:
            obv.iloc[i] = obv.iloc[i - 1]
    df["obv"] = obv

    # --- Stochastic RSI (14, 14, 3, 3) ---
    if "rsi" in df.columns:
        rsi_series = df["rsi"]
        rsi_min = rsi_series.rolling(window=14).min()
        rsi_max = rsi_series.rolling(window=14).max()
        stoch_rsi_raw = (rsi_series - rsi_min) / (rsi_max - rsi_min + 1e-10)
        df["stoch_rsi_k"] = stoch_rsi_raw.rolling(window=3).mean() * 100
        df["stoch_rsi_d"] = df["stoch_rsi_k"].rolling(window=3).mean()

    # --- Ichimoku Cloud ---
    high_9 = df["high"].rolling(window=9).max()
    low_9 = df["low"].rolling(window=9).min()
    df["ichimoku_tenkan"] = (high_9 + low_9) / 2

    high_26 = df["high"].rolling(window=26).max()
    low_26 = df["low"].rolling(window=26).min()
    df["ichimoku_kijun"] = (high_26 + low_26) / 2

    df["ichimoku_senkou_a"] = ((df["ichimoku_tenkan"] + df["ichimoku_kijun"]) / 2).shift(26)

    high_52 = df["high"].rolling(window=52).max()
    low_52 = df["low"].rolling(window=52).min()
    df["ichimoku_senkou_b"] = ((high_52 + low_52) / 2).shift(26)

    df["ichimoku_chikou"] = df["close"].shift(-26)

    # --- Chaikin Money Flow (CMF, 20-period) ---
    mf_multiplier = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / (
        df["high"] - df["low"] + 1e-10
    )
    mf_volume = mf_multiplier * df["volume"]
    df["cmf"] = mf_volume.rolling(window=20).sum() / df["volume"].rolling(window=20).sum()

    # --- Money Flow Index (MFI, 14-period) ---
    typical_price_mfi = (df["high"] + df["low"] + df["close"]) / 3
    raw_money_flow = typical_price_mfi * df["volume"]
    tp_diff = typical_price_mfi.diff()
    positive_flow = (raw_money_flow * (tp_diff > 0).astype(float)).rolling(14).sum()
    negative_flow = (raw_money_flow * (tp_diff < 0).astype(float)).rolling(14).sum()
    money_ratio = positive_flow / (negative_flow + 1e-10)
    df["mfi"] = 100 - (100 / (1 + money_ratio))

    # --- Keltner Channels (EMA 20 ± 1.5 × ATR 10) ---
    keltner_ema = df["close"].ewm(span=20, adjust=False).mean()
    kc_atr = _compute_atr_simple(df, period=10)
    df["keltner_high"] = keltner_ema + 1.5 * kc_atr
    df["keltner_low"] = keltner_ema - 1.5 * kc_atr
    df["keltner_mid"] = keltner_ema

    # Squeeze detection: BB inside Keltner
    if "bb_low" in df.columns and "bb_high" in df.columns:
        df["squeeze_on"] = (
            (df["bb_low"] > df["keltner_low"]) & (df["bb_high"] < df["keltner_high"])
        ).astype(int)
        # Squeeze fires when it was on and now off
        df["squeeze_fire"] = (
            (df["squeeze_on"].shift(1) == 1) & (df["squeeze_on"] == 0)
        ).astype(int)

    # --- Rate of Change (ROC, 12-period) ---
    df["roc"] = ((df["close"] - df["close"].shift(12)) / (df["close"].shift(12) + 1e-10)) * 100

    # --- Williams %R (14-period) ---
    high_14 = df["high"].rolling(window=14).max()
    low_14 = df["low"].rolling(window=14).min()
    df["williams_r"] = ((high_14 - df["close"]) / (high_14 - low_14 + 1e-10)) * -100

    # --- Parabolic SAR ---
    df["psar"], df["psar_direction"] = _compute_parabolic_sar(df)

    # --- Fibonacci Auto-Retracement (from 50-bar swing high/low) ---
    lookback_fib = min(50, len(df))
    if lookback_fib >= 10:
        swing_high = df["high"].iloc[-lookback_fib:].max()
        swing_low = df["low"].iloc[-lookback_fib:].min()
        fib_range = swing_high - swing_low
        df["fib_0"] = swing_high
        df["fib_236"] = swing_high - 0.236 * fib_range
        df["fib_382"] = swing_high - 0.382 * fib_range
        df["fib_500"] = swing_high - 0.500 * fib_range
        df["fib_618"] = swing_high - 0.618 * fib_range
        df["fib_786"] = swing_high - 0.786 * fib_range
        df["fib_1"] = swing_low

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


def _compute_atr_simple(df: pd.DataFrame, period: int = 10) -> pd.Series:
    """Simple ATR computation for Keltner Channels."""
    high_low = df["high"] - df["low"]
    high_close_prev = (df["high"] - df["close"].shift(1)).abs()
    low_close_prev = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def _compute_parabolic_sar(
    df: pd.DataFrame, af_start: float = 0.02, af_step: float = 0.02,
    af_max: float = 0.20,
) -> tuple[pd.Series, pd.Series]:
    """
    Compute Parabolic SAR.

    Returns:
        (sar_values, direction) where direction = 1 (bullish) or -1 (bearish)
    """
    n = len(df)
    sar = pd.Series(0.0, index=df.index)
    direction = pd.Series(0.0, index=df.index)

    if n < 2:
        return sar, direction

    # Initialize
    is_uptrend = df["close"].iloc[1] > df["close"].iloc[0]
    af = af_start
    if is_uptrend:
        sar.iloc[0] = df["low"].iloc[0]
        ep = df["high"].iloc[0]
        direction.iloc[0] = 1
    else:
        sar.iloc[0] = df["high"].iloc[0]
        ep = df["low"].iloc[0]
        direction.iloc[0] = -1

    for i in range(1, n):
        prev_sar = sar.iloc[i - 1]

        if is_uptrend:
            sar_val = prev_sar + af * (ep - prev_sar)
            # SAR must not be above the prior two lows
            sar_val = min(sar_val, df["low"].iloc[i - 1])
            if i >= 2:
                sar_val = min(sar_val, df["low"].iloc[i - 2])

            if df["low"].iloc[i] < sar_val:
                # Flip to downtrend
                is_uptrend = False
                sar_val = ep
                ep = df["low"].iloc[i]
                af = af_start
                direction.iloc[i] = -1
            else:
                direction.iloc[i] = 1
                if df["high"].iloc[i] > ep:
                    ep = df["high"].iloc[i]
                    af = min(af + af_step, af_max)
        else:
            sar_val = prev_sar + af * (ep - prev_sar)
            # SAR must not be below the prior two highs
            sar_val = max(sar_val, df["high"].iloc[i - 1])
            if i >= 2:
                sar_val = max(sar_val, df["high"].iloc[i - 2])

            if df["high"].iloc[i] > sar_val:
                # Flip to uptrend
                is_uptrend = True
                sar_val = ep
                ep = df["high"].iloc[i]
                af = af_start
                direction.iloc[i] = 1
            else:
                direction.iloc[i] = -1
                if df["low"].iloc[i] < ep:
                    ep = df["low"].iloc[i]
                    af = min(af + af_step, af_max)

        sar.iloc[i] = sar_val

    return sar, direction


def compute_pivot_points(prev_ohlc: dict) -> dict:
    """
    Compute Camarilla Pivot Points + Central Pivot Range from previous day's OHLC.

    Args:
        prev_ohlc: dict with keys 'open', 'high', 'low', 'close'

    Returns:
        dict with pivot, R1-R4, S1-S4, TC, BC, CPR_width
    """
    if not prev_ohlc:
        return {}

    h = prev_ohlc["high"]
    l = prev_ohlc["low"]
    c = prev_ohlc["close"]
    hl_range = h - l

    pivot = (h + l + c) / 3

    # Camarilla levels
    r4 = c + hl_range * 1.1 / 2
    r3 = c + hl_range * 1.1 / 4
    r2 = c + hl_range * 1.1 / 6
    r1 = c + hl_range * 1.1 / 12

    s1 = c - hl_range * 1.1 / 12
    s2 = c - hl_range * 1.1 / 6
    s3 = c - hl_range * 1.1 / 4
    s4 = c - hl_range * 1.1 / 2

    # Central Pivot Range
    bc = (h + l) / 2
    tc = (pivot - bc) + pivot
    cpr_width = abs(tc - bc) / (pivot + 1e-10)

    return {
        "pivot": round(pivot, 2),
        "r1": round(r1, 2), "r2": round(r2, 2),
        "r3": round(r3, 2), "r4": round(r4, 2),
        "s1": round(s1, 2), "s2": round(s2, 2),
        "s3": round(s3, 2), "s4": round(s4, 2),
        "tc": round(tc, 2), "bc": round(bc, 2),
        "cpr_width": round(cpr_width, 4),
    }


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
