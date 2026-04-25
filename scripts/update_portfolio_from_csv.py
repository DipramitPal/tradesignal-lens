import csv
import json
from datetime import datetime
import os

# Define paths relative to the project root
CSV_PATH = 'data/holdings.csv'
JSON_PATH = 'data/portfolio.json'

def update_portfolio():
    # Load existing portfolio to preserve metadata like sector, stop_loss, target, etc.
    if os.path.exists(JSON_PATH):
        with open(JSON_PATH, 'r') as f:
            portfolio = json.load(f)
    else:
        portfolio = {"holdings": {}, "account_value": 0.0, "last_updated": ""}

    holdings = portfolio.get("holdings", {})
    
    # Track symbols currently in the CSV to find sold positions
    current_symbols = set()
    total_invested_value = 0.0

    if not os.path.exists(CSV_PATH):
        print(f"Error: {CSV_PATH} not found.")
        return

    with open(CSV_PATH, mode='r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            instrument = row.get('Instrument')
            if not instrument or not instrument.strip():
                continue
                
            symbol = f"{instrument.strip()}.NS" # Appending .NS to match portfolio.json format
            current_symbols.add(symbol)
            
            qty = int(row.get('Qty.', 0))
            avg_price = float(row.get('Avg. cost', 0.0))
            invested_value = float(row.get('Invested', 0.0))
            total_invested_value += invested_value

            if symbol in holdings:
                # Update existing holding
                holdings[symbol]['qty'] = qty
                holdings[symbol]['avg_price'] = avg_price
                holdings[symbol]['invested_value'] = invested_value
            else:
                # Add new holding
                holdings[symbol] = {
                    "qty": qty,
                    "avg_price": avg_price,
                    "stop_loss": 0,
                    "target": 0,
                    "sector": "MISC", # Default sector, can be updated manually later
                    "invested_value": invested_value,
                    "added_date": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                    "notes": ""
                }

    # Remove symbols from portfolio that are no longer in holdings.csv (i.e. they were sold)
    symbols_to_remove = [sym for sym in holdings if sym not in current_symbols]
    for sym in symbols_to_remove:
        del holdings[sym]

    portfolio['holdings'] = holdings
    # Update last_updated timestamp
    portfolio['last_updated'] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # Save updated data back to portfolio.json
    with open(JSON_PATH, 'w') as f:
        json.dump(portfolio, f, indent=2)
        
    print(f"Success! Updated portfolio.json.")
    print(f"- Total Active Holdings: {len(current_symbols)}")
    print(f"- Sold/Removed Holdings: {len(symbols_to_remove)}")
    if symbols_to_remove:
        print(f"  Removed: {', '.join(symbols_to_remove)}")

if __name__ == "__main__":
    update_portfolio()
