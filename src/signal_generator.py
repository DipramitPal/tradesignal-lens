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
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Volume': 'sum'
    }
    df_resampled = df.resample(rule_map[timeframe]).apply(ohlc_dict).dropna()
    return df_resampled

def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    df['Signal'] = 'Hold'
    
    # MACD Bullish crossover
    macd_cross = (df['MACD'] > 0) & (df['MACD'].shift(1) <= 0)
    df.loc[macd_cross, 'Signal'] = 'Buy (MACD Bullish Crossover)'

    # RSI overbought
    rsi_overbought = df['RSI'] > 70
    df.loc[rsi_overbought, 'Signal'] = 'Sell (RSI Overbought)'

    # RSI oversold
    rsi_oversold = df['RSI'] < 30
    df.loc[rsi_oversold, 'Signal'] = 'Buy (RSI Oversold)'

    # Greedy Cut: Sharp upward momentum sell
    df['Momentum_Change'] = df['Momentum_5'] - df['Momentum_5'].shift(1)
    df['Greedy_Sell'] = (df['Momentum_5'] > 0) & (df['Momentum_Change'] < 0) & (df['RSI'] > 65)
    df.loc[df['Greedy_Sell'], 'Signal'] = 'Sell (Greedy Cut on Sharp Momentum)'

    return df

def analyze_stock(df: pd.DataFrame, timeframe: str = 'weekly') -> pd.DataFrame:
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    df = resample_data(df, timeframe)
    df = add_technical_indicators(df)
    df = generate_signals(df)
    return df
