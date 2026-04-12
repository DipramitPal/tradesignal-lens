"""
Tracking manager — paper-trade tracking for stocks you're watching.

Stores simulated positions in JSON. Users can:
  - Add a stock with qty + simulated buy price
  - Edit qty/price
  - Remove from tracking
  - Mark as "bought" → moves the entry to the real PortfolioManager
"""

import json
import os
from datetime import datetime
from typing import Optional

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import DATA_DIR

DEFAULT_TRACKING_PATH = os.path.join(str(DATA_DIR), "tracking.json")


class TrackingManager:
    """JSON-backed tracking for paper positions."""

    def __init__(self, path: str = DEFAULT_TRACKING_PATH):
        self.path = path
        self.tracked: dict[str, dict] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    data = json.load(f)
                self.tracked = data.get("tracked", {})
            except (json.JSONDecodeError, KeyError):
                self.tracked = {}
        else:
            self.tracked = {}

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        payload = {
            "tracked": self.tracked,
            "last_updated": datetime.now().isoformat(),
        }
        with open(self.path, "w") as f:
            json.dump(payload, f, indent=2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_stock(self, *, symbol: str, qty: int, price: float, notes: str = ""):
        """Add a stock to tracking."""
        symbol = symbol.upper().strip()
        self.tracked[symbol] = {
            "qty": qty,
            "simulated_price": price,
            "added_date": datetime.now().isoformat(),
            "notes": notes,
        }
        self._save()

    def update_stock(self, symbol: str, *, qty: Optional[int] = None,
                     price: Optional[float] = None, notes: Optional[str] = None):
        """Update qty/price of a tracked stock."""
        self._load()
        symbol = symbol.upper().strip()
        if symbol not in self.tracked:
            return False
        if qty is not None:
            self.tracked[symbol]["qty"] = qty
        if price is not None:
            self.tracked[symbol]["simulated_price"] = price
        if notes is not None:
            self.tracked[symbol]["notes"] = notes
        self._save()
        return True

    def remove_stock(self, symbol: str) -> bool:
        self._load()  # Refresh from disk to avoid stale state
        symbol = symbol.upper().strip()
        if symbol in self.tracked:
            del self.tracked[symbol]
            self._save()
            return True
        return False

    def get_all(self) -> dict[str, dict]:
        self._load()
        return dict(self.tracked)

    def get_stock(self, symbol: str) -> Optional[dict]:
        return self.tracked.get(symbol.upper().strip())

    def is_tracked(self, symbol: str) -> bool:
        return symbol.upper().strip() in self.tracked

    def mark_as_bought(self, symbol: str, *, qty: Optional[int] = None,
                       price: Optional[float] = None):
        """
        Remove from tracking and return the data needed to add to portfolio.
        Caller is responsible for calling PortfolioManager.add_holding().
        """
        self._load()
        symbol = symbol.upper().strip()
        entry = self.tracked.get(symbol)
        if not entry:
            return None

        result = {
            "symbol": symbol,
            "qty": qty if qty is not None else entry["qty"],
            "avg_price": price if price is not None else entry["simulated_price"],
        }
        del self.tracked[symbol]
        self._save()
        return result
