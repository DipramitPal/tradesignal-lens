import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import SCAN_UNIVERSE
from src.feature_engineering import add_technical_indicators
from src.quant.risk_manager import compute_initial_sl

class MomentumBacktester:
    def __init__(self, universe: list[str] = None, start_date: str = "2020-01-01", 
                 top_n: int = 2, initial_capital: float = 100000.0):
        self.universe = universe or SCAN_UNIVERSE
        self.start_date = pd.to_datetime(start_date)
        # Fetch data starting 6 months earlier so indicators/momentum are ready by start_date
        self.fetch_start_date = self.start_date - pd.DateOffset(months=6)
        self.top_n = top_n
        self.initial_capital = initial_capital
        
        self.data: dict[str, pd.DataFrame] = {}
        
        # Portfolio state
        self.cash = initial_capital
        self.positions = {}  # symbol -> {'shares': int, 'entry_price': float, 'sl': float, 'buy_date': date}
        
        # Tracking metrics
        self.portfolio_history = []  # List of dicts with 'date', 'cash', 'stock_value', 'total_value'
        self.trade_log = []

    def fetch_data(self):
        print(f"Fetching historical daily data from {self.fetch_start_date.date()}...")
        for symbol in self.universe:
            try:
                # Add .NS for Indian stocks if missing and not already handled
                yf_sym = symbol if symbol.endswith(".NS") or symbol.endswith(".BO") else f"{symbol}.NS"
                ticker = yf.Ticker(yf_sym)
                df = ticker.history(start=self.fetch_start_date, auto_adjust=True)
                
                if df.empty or len(df) < 50:
                    continue
                
                df.columns = [c.lower() for c in df.columns]
                df.index = df.index.tz_localize(None)
                
                # Compute indicators using standard feature engineering
                df = add_technical_indicators(df)
                
                # Momentum proxy as per dashboard logic: MTF Score * RVOL * (Entry Quality / 100)
                # Since we lack 15m data for the intricate MTF, we proxy it based on the daily metrics
                # that entry_quality and daily score use. 
                # 3-month return + daily RSI/MACD synergy
                
                # Approximation of RVOL
                vol_avg = df["volume"].rolling(20).mean()
                df["rvol"] = df["volume"] / (vol_avg + 1e-10)
                
                # Approximate entry quality factors
                rsi_sweet_spot = ((df["rsi"] < 55) & (df["rsi"] > 35)).astype(int) * 30
                cmf_bullish = (df["cmf"] > 0).astype(int) * 20
                rvol_boost = (df["rvol"] > 1.2).astype(int) * 20
                entry_quality = np.clip(rsi_sweet_spot + cmf_bullish + rvol_boost + 30, 0, 100)
                
                # Approximate MTF score based on daily features
                # Bullish MACD + price above 50 EMA + bullish supertrend
                trend_score = ((df["close"] > df["ema_50"]).astype(int) * 0.3 + 
                               (df["macd"] > df["macd_signal"]).astype(int) * 0.3 +
                               (df["supertrend_direction"] == 1).astype(int) * 0.4)
                
                # 3-month return to establish pure momentum base
                df["return_3m"] = df["close"].pct_change(63) # ~63 trading days in 3 months
                
                momentum_base = df["return_3m"].clip(lower=-0.5, upper=1.0)
                mtf_proxy = (trend_score + momentum_base) / 2.0
                
                df["momentum_score"] = mtf_proxy * df["rvol"] * (entry_quality / 100.0)
                
                self.data[symbol] = df
            except Exception as e:
                print(f"Failed to process {symbol}: {e}")
        
        print(f"Data fetched and processed for {len(self.data)} stocks.")

    def run(self):
        print("Starting Simulation...")
        if not self.data:
            self.fetch_data()
            
        # Get common date range
        all_dates = pd.Index([])
        for df in self.data.values():
            all_dates = all_dates.union(df.index)
        
        all_dates = all_dates[all_dates >= self.start_date].sort_values()
        
        for i, current_date in enumerate(all_dates):
            current_date_ts = pd.Timestamp(current_date)
            is_month_end = False
            
            # Check if this is the last trading day of the calendar month
            if i < len(all_dates) - 1:
                next_date = pd.Timestamp(all_dates[i+1])
                if current_date_ts.month != next_date.month:
                    is_month_end = True
            else:
                is_month_end = True
                
            # 1. Process Daily Exits (Stop Loss/Ejections)
            stocks_to_remove = []
            for symbol, pos in self.positions.items():
                df = self.data.get(symbol)
                if df is None or current_date_ts not in df.index:
                    continue
                
                row = df.loc[current_date_ts]
                low_price = row["low"]
                
                if low_price <= pos["sl"]:
                    # Ejected! Sell at Stop Loss price (or open if it gapped down)
                    exit_price = min(pos["sl"], row["open"]) 
                    value = exit_price * pos["shares"]
                    self.cash += value
                    stocks_to_remove.append(symbol)
                    
                    self.trade_log.append({
                        "date": current_date_ts.date(),
                        "symbol": symbol,
                        "action": "SELL (SL Hit)",
                        "price": exit_price,
                        "shares": pos["shares"],
                        "balance": self._get_current_total_value(current_date_ts, stocks_to_remove)
                    })
                    print(f"[{current_date_ts.date()}] STOP LOSS HIT: Ejected {symbol} at Rs.{exit_price:.2f}")

            for sym in stocks_to_remove:
                del self.positions[sym]
                
            # 2. Mark-to-Market Portfolio tracking
            stock_value = 0.0
            for symbol, pos in self.positions.items():
                df = self.data.get(symbol)
                if df is not None and current_date_ts in df.index:
                    stock_value += df.loc[current_date_ts, "close"] * pos["shares"]
                else:
                    stock_value += pos["entry_price"] * pos["shares"] # fallback
            
            total_value = self.cash + stock_value
            self.portfolio_history.append({
                "date": current_date_ts,
                "cash": self.cash,
                "stock_value": stock_value,
                "total_value": total_value
            })

            # 3. Process Month-End Rebalancing
            if is_month_end:
                self._rebalance(current_date_ts)
                
    def _rebalance(self, current_date):
        # 1. Liquidate current holdings at close price
        stocks_to_remove = []
        for symbol, pos in self.positions.items():
            df = self.data.get(symbol)
            if df is not None and current_date in df.index:
                close_price = df.loc[current_date, "close"]
                self.cash += close_price * pos["shares"]
                stocks_to_remove.append(symbol)
                self.trade_log.append({
                    "date": current_date.date(),
                    "symbol": symbol,
                    "action": "SELL (Rebalance)",
                    "price": close_price,
                    "shares": pos["shares"],
                    "balance": self._get_current_total_value(current_date, stocks_to_remove)
                })
        
        self.positions.clear()
        
        # 2. Rank stocks by momentum
        candidates = []
        for symbol, df in self.data.items():
            if current_date in df.index:
                row = df.loc[current_date]
                # Ensure the stock has actual data and is somewhat liquid
                if not pd.isna(row["momentum_score"]) and row["close"] > 0:
                    candidates.append({
                        "symbol": symbol,
                        "score": row["momentum_score"],
                        "close": row["close"],
                        "atr": row["atr"]
                    })
                    
        candidates = sorted(candidates, key=lambda x: x["score"], reverse=True)
        top_candidates = candidates[:self.top_n]
        
        if not top_candidates:
            return
            
        # 3. Buy Top N stocks with equal weighting
        allocation_per_stock = self.cash / len(top_candidates)
        
        for cand in top_candidates:
            symbol = cand["symbol"]
            price = cand["close"]
            atr = cand["atr"]
            
            shares = int(allocation_per_stock // price)
            if shares > 0:
                cost = shares * price
                self.cash -= cost
                
                # Compute ATR-based stop loss via current algorithm
                sl = compute_initial_sl(price, atr, multiplier=1.5)
                
                self.positions[symbol] = {
                    "shares": shares,
                    "entry_price": price,
                    "sl": sl,
                    "buy_date": current_date.date()
                }
                
                self.trade_log.append({
                    "date": current_date.date(),
                    "symbol": symbol,
                    "action": "BUY (Rebalance)",
                    "price": price,
                    "shares": shares,
                    "score": cand["score"],
                    "balance": self._get_current_total_value(current_date)
                })
                print(f"[{current_date.date()}] BOUGHT: {symbol} | Shares: {shares} | Price: {price:.2f} | SL: {sl:.2f}")

    def _get_current_total_value(self, current_date, excluded_symbols=None):
        if excluded_symbols is None:
            excluded_symbols = []
        stock_value = 0.0
        for sym, p in self.positions.items():
            if sym in excluded_symbols:
                continue
            df = self.data.get(sym)
            if df is not None and current_date in df.index:
                stock_value += df.loc[current_date, "close"] * p["shares"]
            else:
                stock_value += p["entry_price"] * p["shares"]
        return self.cash + stock_value

    def get_results(self):
        return pd.DataFrame(self.portfolio_history)

if __name__ == "__main__":
    backtester = MomentumBacktester(top_n=2, initial_capital=100000.0)
    backtester.run()
    results = backtester.get_results()
    print("Final Portfolio Value:", results.iloc[-1]["total_value"])
