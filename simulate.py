import os
import matplotlib.pyplot as plt
from src.quant.backtester import MomentumBacktester

def main():
    print("="*60)
    print("TradeSignal Lens - Momentum Strategy Backtester")
    print("="*60)
    
    # 1. Initialize backtester
    # Top 2 Stocks, 100,000 Starting Capital
    bt = MomentumBacktester(top_n=2, initial_capital=100000.0)
    
    # 2. Run simulation
    bt.run()
    
    # 3. Get Results
    results = bt.get_results()
    
    if results.empty:
        print("Error: No simulation results generated.")
        return
        
    final_value = results.iloc[-1]["total_value"]
    initial_value = 100000.0
    total_return = ((final_value - initial_value) / initial_value) * 100

    print("\n" + "="*60)
    print(f"BACKTEST COMPLETE")
    print(f"Initial Capital: Rs. {initial_value:,.2f}")
    print(f"Final Capital:   Rs. {final_value:,.2f}")
    print(f"Total Return:    {total_return:.2f}%")
    print("="*60)
    
    # 4. Plot Equity Curve
    plt.figure(figsize=(12, 6))
    plt.plot(results["date"], results["total_value"], label="Portfolio Value", color="#00ffff")
    
    plt.title("Momentum Strategy (Top 2 Active Stocks + ATR SL Auto-Eject)", fontsize=14)
    plt.xlabel("Date", fontsize=12)
    plt.ylabel("Portfolio Value (Rs.)", fontsize=12)
    
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.legend()
    
    # Use dark theme akin to the dashboard
    plt.style.use('dark_background')
    
    # Save the plot
    output_path = os.path.join(os.path.dirname(__file__), "backtest_equity_curve.png")
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"\nEquity curve graph saved to: {output_path}")

    # 5. Save Trade Log to Markdown
    import pandas as pd
    trades_df = pd.DataFrame(bt.trade_log)
    if not trades_df.empty:
        md_path = os.path.join(os.path.dirname(__file__), "trade_history.md")
        # Format columns properly for markdown
        trades_df['date'] = trades_df['date'].astype(str)
        trades_df['price'] = trades_df['price'].apply(lambda x: f"Rs. {x:,.2f}")
        try:
            trades_df['balance'] = trades_df['balance'].apply(lambda x: f"Rs. {x:,.2f}" if pd.notnull(x) else "-")
            trades_df['score'] = trades_df['score'].apply(lambda x: f"{x:.3f}" if pd.notnull(x) else "-")
        except:
            pass
            
        with open(md_path, "w") as f:
            f.write("# Backtest Trade Log (2020 - Present)\n\n")
            f.write("| Date | Symbol | Action | Shares | Price | Momentum Score | Account Balance |\n")
            f.write("|---|---|---|---|---|---|---|\n")
            for _, row in trades_df.iterrows():
                score = row.get('score', '-')
                if pd.isna(score): score = '-'
                balance = row.get('balance', '-')
                f.write(f"| {row['date']} | {row['symbol']} | {row['action']} | {row['shares']} | {row['price']} | {score} | {balance} |\n")
                
        print(f"Trade log saved to: {md_path}")

if __name__ == "__main__":
    main()
