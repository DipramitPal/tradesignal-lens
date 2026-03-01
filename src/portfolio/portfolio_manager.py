"""
Persistent portfolio manager.

Stores and manages the user's current stock holdings in a JSON file.
Integrates with LiveMonitor to automatically:
  - Load owned positions for scan/monitor commands
  - Ensure owned symbols are always in the monitoring list
  - Track buy prices, quantities, stop-losses, and notes

Usage (CLI):
    python main.py portfolio                     # View portfolio
    python main.py portfolio add RELIANCE.NS 10 2500.00
    python main.py portfolio remove RELIANCE.NS
    python main.py portfolio update RELIANCE.NS --qty 15 --sl 2400
"""

import json
import os
from datetime import datetime
from typing import Optional

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import DEFAULT_ACCOUNT_VALUE, SYMBOL_SECTOR

DEFAULT_PORTFOLIO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "portfolio.json"
)


class PortfolioManager:
    """Persistent portfolio with JSON-backed storage."""

    def __init__(self, portfolio_path: str = DEFAULT_PORTFOLIO_PATH):
        self.portfolio_path = portfolio_path
        self.holdings: dict[str, dict] = {}
        self.account_value: float = DEFAULT_ACCOUNT_VALUE
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self):
        """Load portfolio from disk."""
        if os.path.exists(self.portfolio_path):
            try:
                with open(self.portfolio_path, "r") as f:
                    data = json.load(f)
                self.holdings = data.get("holdings", {})
                self.account_value = data.get("account_value", DEFAULT_ACCOUNT_VALUE)
            except (json.JSONDecodeError, IOError):
                self.holdings = {}

    def _save(self):
        """Persist portfolio to disk."""
        os.makedirs(os.path.dirname(self.portfolio_path), exist_ok=True)
        data = {
            "holdings": self.holdings,
            "account_value": self.account_value,
            "last_updated": datetime.now().isoformat(),
        }
        with open(self.portfolio_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    # ------------------------------------------------------------------
    # CRUD Operations
    # ------------------------------------------------------------------

    def add_holding(
        self, *,
        symbol: str,
        qty: int,
        avg_price: float,
        stop_loss: float = 0.0,
        target: float = 0.0,
        notes: str = "",
    ):
        """
        Add or update a stock holding.

        Args:
            symbol: Stock symbol (e.g., RELIANCE.NS)
            qty: Number of shares
            avg_price: Average buy price
            stop_loss: Stop-loss price (0 = auto-compute on next scan)
            target: Target price (0 = auto-compute based on R:R)
            notes: Optional notes
        """
        sector = SYMBOL_SECTOR.get(symbol, "MISC")
        invested = round(qty * avg_price, 2)

        self.holdings[symbol] = {
            "qty": qty,
            "avg_price": avg_price,
            "stop_loss": stop_loss,
            "target": target,
            "sector": sector,
            "invested_value": invested,
            "added_date": datetime.now().isoformat(),
            "notes": notes,
        }
        self._save()

    def remove_holding(self, symbol: str) -> bool:
        """Remove a holding. Returns True if found and removed."""
        if symbol in self.holdings:
            del self.holdings[symbol]
            self._save()
            return True
        return False

    def update_holding(
        self, symbol: str, *,
        qty: Optional[int] = None,
        avg_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        target: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> bool:
        """Update specific fields of an existing holding."""
        if symbol not in self.holdings:
            return False

        h = self.holdings[symbol]
        if qty is not None:
            h["qty"] = qty
        if avg_price is not None:
            h["avg_price"] = avg_price
        if stop_loss is not None:
            h["stop_loss"] = stop_loss
        if target is not None:
            h["target"] = target
        if notes is not None:
            h["notes"] = notes

        h["invested_value"] = round(h["qty"] * h["avg_price"], 2)
        self._save()
        return True

    def set_account_value(self, value: float):
        """Update the account value."""
        self.account_value = value
        self._save()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_symbols(self) -> list[str]:
        """Get list of all held symbols."""
        return list(self.holdings.keys())

    def get_holding(self, symbol: str) -> Optional[dict]:
        """Get a specific holding."""
        return self.holdings.get(symbol)

    def get_total_invested(self) -> float:
        """Get total invested value across all holdings."""
        return sum(h["invested_value"] for h in self.holdings.values())

    def get_available_capital(self) -> float:
        """Get capital available for new investments."""
        return max(0, self.account_value - self.get_total_invested())

    def get_sector_exposure(self) -> dict[str, float]:
        """Get invested value per sector."""
        exposure = {}
        for h in self.holdings.values():
            sector = h.get("sector", "MISC")
            exposure[sector] = exposure.get(sector, 0) + h["invested_value"]
        return exposure

    def is_empty(self) -> bool:
        """Check if portfolio has any holdings."""
        return len(self.holdings) == 0

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def print_portfolio(self, current_prices: Optional[dict[str, float]] = None):
        """Print portfolio summary with optional live prices."""
        if self.is_empty():
            print("\n  Portfolio is empty. Add holdings with:")
            print('    python main.py portfolio add SYMBOL QTY PRICE')
            print('    Example: python main.py portfolio add RELIANCE.NS 10 2500.00')
            return

        total_invested = self.get_total_invested()
        available = self.get_available_capital()

        print(f"\n{'='*70}")
        print(f"  MY PORTFOLIO")
        print(f"{'='*70}")
        print(f"\n  Account Value: Rs.{self.account_value:,.0f}")
        print(f"  Total Invested: Rs.{total_invested:,.0f}")
        print(f"  Available Capital: Rs.{available:,.0f}")
        print(f"  Holdings: {len(self.holdings)} stocks")

        # Header
        print(f"\n  {'Symbol':<16} {'Qty':>5} {'Avg Price':>10} {'Invested':>12} "
              f"{'SL':>8} {'Target':>8} {'Sector':<10}")
        print(f"  {'-'*16} {'-'*5} {'-'*10} {'-'*12} {'-'*8} {'-'*8} {'-'*10}")

        total_pnl = 0.0
        total_current = 0.0

        for symbol, h in sorted(self.holdings.items()):
            qty = h["qty"]
            avg = h["avg_price"]
            invested = h["invested_value"]
            sl = h.get("stop_loss", 0)
            target = h.get("target", 0)
            sector = h.get("sector", "MISC")

            sl_str = f"{sl:.1f}" if sl > 0 else "Auto"
            target_str = f"{target:.1f}" if target > 0 else "Auto"

            line = (f"  {symbol:<16} {qty:>5} {avg:>10,.2f} "
                    f"Rs.{invested:>10,.0f} {sl_str:>8} {target_str:>8} {sector:<10}")

            # Add live P&L if prices available
            if current_prices and symbol in current_prices:
                cmp = current_prices[symbol]
                pnl_pct = ((cmp - avg) / avg) * 100
                pnl_val = (cmp - avg) * qty
                current_val = cmp * qty
                total_pnl += pnl_val
                total_current += current_val
                pnl_sign = "+" if pnl_pct >= 0 else ""
                line += f"  CMP: {cmp:,.2f}  P&L: {pnl_sign}{pnl_pct:.1f}% ({pnl_sign}Rs.{pnl_val:,.0f})"
            else:
                total_current += invested

            print(line)

        # Sector exposure
        print(f"\n  Sector Exposure:")
        for sector, value in sorted(self.get_sector_exposure().items(),
                                     key=lambda x: x[1], reverse=True):
            pct = (value / total_invested * 100) if total_invested > 0 else 0
            print(f"    {sector:<12} Rs.{value:>10,.0f}  ({pct:.1f}%)")

        # Total P&L
        if current_prices:
            total_pnl_pct = ((total_current - total_invested) / total_invested * 100) if total_invested > 0 else 0
            pnl_sign = "+" if total_pnl >= 0 else ""
            print(f"\n  Total P&L: {pnl_sign}Rs.{total_pnl:,.0f} ({pnl_sign}{total_pnl_pct:.1f}%)")
            print(f"  Current Value: Rs.{total_current:,.0f}")

        notes_exist = any(h.get("notes") for h in self.holdings.values())
        if notes_exist:
            print(f"\n  Notes:")
            for sym, h in self.holdings.items():
                if h.get("notes"):
                    print(f"    {sym}: {h['notes']}")

        print(f"\n{'='*70}")
