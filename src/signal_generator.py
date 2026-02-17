import pandas as pd
import numpy as np
from feature_engineering import add_technical_indicators

def resample_data(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    rule_map = {
        'daily': 'D',
        'weekly': 'W',
        'monthly': 'M',
        'quarterly': 'Q'
    }
    if timeframe not in rule_map:
        raise ValueError("Timeframe must be one of: daily, weekly, monthly, quarterly")

    ohlc_dict = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }
    df_resampled = df.resample(rule_map[timeframe]).apply(ohlc_dict).dropna()
    return df_resampled

def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    df['Signal'] = 'Hold'

    # MACD Bullish crossover
    macd_cross = (df['macd'] > 0) & (df['macd'].shift(1) <= 0)
    df.loc[macd_cross, 'Signal'] = 'Buy (MACD Bullish Crossover)'

    # RSI overbought
    rsi_overbought = df['rsi'] > 70
    df.loc[rsi_overbought, 'Signal'] = 'Sell (RSI Overbought)'

    # RSI oversold
    rsi_oversold = df['rsi'] < 30
    df.loc[rsi_oversold, 'Signal'] = 'Buy (RSI Oversold)'

    # Greedy Cut: Sharp upward momentum sell
    df['momentum_change'] = df['momentum_5'] - df['momentum_5'].shift(1)
    df['greedy_sell'] = (df['momentum_5'] > 0) & (df['momentum_change'] < 0) & (df['rsi'] > 65)
    df.loc[df['greedy_sell'], 'Signal'] = 'Sell (Greedy Cut on Sharp Momentum)'

    return df

def analyze_stock(df: pd.DataFrame, timeframe: str = 'weekly') -> pd.DataFrame:
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    df = resample_data(df, timeframe)
    df = add_technical_indicators(df)
    df = generate_signals(df)
    return df
