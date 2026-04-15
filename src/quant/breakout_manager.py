"""
Breakout detection and dynamic SL adjustment engine.

Detects when a stock breaks above its 20-day high with volume confirmation,
then dynamically tightens the stop-loss as the price moves higher.

Breakout state is persisted to data/breakout_state.json so that SL
adjustments survive restarts.

Usage:
    from quant.breakout_manager import BreakoutManager
    bm = BreakoutManager()
    result = bm.check(symbol, current_price, df_daily, atr, rvol)
    # result = {"breakout": True, "level": 105.0, "pct_above": 3.5,
    #           "adjusted_sl": 103.5, "sl_phase": "BREAKOUT_TRAIL"}
"""

import json
import os
from datetime import datetime
from typing import Optional

import pandas as pd

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)
DEFAULT_STATE_PATH = os.path.join(_DATA_DIR, "breakout_state.json")


class BreakoutManager:
    """Tracks breakout status and computes dynamic SL for portfolio stocks."""

    def __init__(self, state_path: str = DEFAULT_STATE_PATH):
        self.state_path = state_path
        self.state: dict[str, dict] = {}
        self._load()

    # ── Persistence ──────────────────────────────────────────────────

    def _load(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r") as f:
                    data = json.load(f)
                self.state = data.get("breakouts", {})
            except (json.JSONDecodeError, KeyError):
                self.state = {}

    def _save(self):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        payload = {
            "breakouts": self.state,
            "last_updated": datetime.now().isoformat(),
        }
        with open(self.state_path, "w") as f:
            json.dump(payload, f, indent=2)

    # ── Core Detection ───────────────────────────────────────────────

    @staticmethod
    def detect_breakout(
        current_price: float,
        df_daily: pd.DataFrame,
        rvol: float = 1.0,
        lookback: int = 20,
        min_rvol: float = 1.3,
    ) -> tuple[bool, float, float]:
        """
        Detect a breakout above the N-day high with volume confirmation.

        Returns:
            (is_breakout, breakout_level, pct_above)
        """
        if df_daily is None or df_daily.empty or len(df_daily) < lookback + 1:
            return False, 0.0, 0.0

        high_col = "high" if "high" in df_daily.columns else "High"
        if high_col not in df_daily.columns:
            return False, 0.0, 0.0

        # N-day high from the lookback period EXCLUDING today
        recent_highs = df_daily[high_col].iloc[-(lookback + 1):-1]
        breakout_level = float(recent_highs.max())

        if breakout_level <= 0:
            return False, 0.0, 0.0

        pct_above = ((current_price - breakout_level) / breakout_level) * 100
        is_breakout = current_price > breakout_level and rvol >= min_rvol

        return is_breakout, round(breakout_level, 2), round(pct_above, 2)

    # ── Dynamic SL Computation ───────────────────────────────────────

    @staticmethod
    def compute_breakout_sl(
        breakout_level: float,
        highest_since_breakout: float,
        atr: float,
        current_sl: float = 0.0,
    ) -> float:
        """
        Compute a tightened SL for an active breakout.

        - Floor = breakout_level - 0.5 × ATR  (just below breakout)
        - Trail = highest_since_breakout - 1.0 × ATR
        - Result = max(floor, trail, current_sl)  (never decreases)
        """
        floor_sl = breakout_level - 0.5 * atr
        trail_sl = highest_since_breakout - 1.0 * atr
        new_sl = max(floor_sl, trail_sl, current_sl)
        return round(new_sl, 2)

    # ── Public API ───────────────────────────────────────────────────

    def check(
        self,
        symbol: str,
        current_price: float,
        df_daily: pd.DataFrame,
        atr: float,
        rvol: float = 1.0,
        current_sl: float = 0.0,
    ) -> dict:
        """
        Check breakout status for a symbol and compute adjusted SL.

        Returns dict with:
            breakout (bool), level (float), pct_above (float),
            adjusted_sl (float), phase (str),
            is_new (bool) — True on the very first detection
        """
        is_bo, level, pct_above = self.detect_breakout(
            current_price, df_daily, rvol=rvol,
        )

        existing = self.state.get(symbol)

        # If the stock was previously in breakout, keep tracking even
        # if price has pulled back slightly (within 1% of level).
        if not is_bo and existing:
            stored_level = existing.get("level", 0)
            near = stored_level > 0 and current_price >= stored_level * 0.99
            if near:
                # Still above breakout level — sustain the breakout
                is_bo = True
                level = stored_level
                pct_above = round(
                    ((current_price - stored_level) / stored_level) * 100, 2
                )

        if not is_bo:
            # Clear the breakout if price fell well below (> 1% below)
            if existing:
                del self.state[symbol]
                self._save()
            return {
                "breakout": False,
                "level": level,
                "pct_above": pct_above,
                "adjusted_sl": current_sl,
                "phase": "NORMAL",
                "is_new": False,
            }

        # ── Active breakout ──────────────────────────────────────────
        is_new = existing is None

        if is_new:
            self.state[symbol] = {
                "level": level,
                "detected_at": datetime.now().isoformat(),
                "highest_since": current_price,
                "initial_sl": current_sl,
            }
        else:
            level = existing.get("level", level)
            prev_high = existing.get("highest_since", current_price)
            self.state[symbol]["highest_since"] = max(prev_high, current_price)

        highest = self.state[symbol]["highest_since"]
        adjusted_sl = self.compute_breakout_sl(level, highest, atr, current_sl)

        self.state[symbol]["current_sl"] = adjusted_sl
        self._save()

        return {
            "breakout": True,
            "level": level,
            "pct_above": pct_above,
            "adjusted_sl": adjusted_sl,
            "phase": "BREAKOUT_TRAIL",
            "is_new": is_new,
            "detected_at": self.state[symbol].get("detected_at", ""),
            "highest_since": highest,
        }

    def get_all_active(self) -> dict[str, dict]:
        """Return all symbols with active breakouts."""
        self._load()
        return dict(self.state)

    def clear(self, symbol: str):
        """Manually clear breakout state for a symbol."""
        if symbol in self.state:
            del self.state[symbol]
            self._save()
