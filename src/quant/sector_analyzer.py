"""
Sector rotation and relative strength analyzer.

Computes:
  - Relative Strength (RS) ratio vs NIFTY 50 benchmark
  - Sector phase classification (Leading / Weakening / Lagging / Improving)
  - Sector adjustment multiplier for signal scoring
"""

import pandas as pd
import numpy as np

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import SECTOR_MAP, SYMBOL_SECTOR


class SectorAnalyzer:
    """Analyzes sector rotation and relative strength."""

    def __init__(self):
        self.sector_map = SECTOR_MAP
        self.symbol_sector = SYMBOL_SECTOR
        self._rs_cache: dict[str, float] = {}
        self._sector_phase_cache: dict[str, str] = {}

    def compute_relative_strength(
        self, stock_df: pd.DataFrame, benchmark_df: pd.DataFrame,
        period: int = 20,
    ) -> float:
        """
        Compute RS ratio = stock return / benchmark return over N days.

        Args:
            stock_df: stock daily DataFrame with 'close'
            benchmark_df: NIFTY 50 daily DataFrame with 'close'
            period: lookback period for return calculation

        Returns:
            RS ratio (>1.0 = outperforming, <1.0 = underperforming)
        """
        if stock_df.empty or benchmark_df.empty:
            return 1.0

        if len(stock_df) < period or len(benchmark_df) < period:
            return 1.0

        stock_return = (
            (stock_df["close"].iloc[-1] - stock_df["close"].iloc[-period])
            / (stock_df["close"].iloc[-period] + 1e-10)
        )
        bench_return = (
            (benchmark_df["close"].iloc[-1] - benchmark_df["close"].iloc[-period])
            / (benchmark_df["close"].iloc[-period] + 1e-10)
        )

        if abs(bench_return) < 1e-10:
            return 1.0

        return round(stock_return / bench_return, 3) if bench_return != 0 else 1.0

    def classify_sector_phase(
        self, sector: str, sector_stock_dfs: dict[str, pd.DataFrame],
        benchmark_df: pd.DataFrame, period: int = 20,
    ) -> str:
        """
        Classify a sector's phase based on average RS of its constituents.

        Returns:
            LEADING, WEAKENING, LAGGING, or IMPROVING
        """
        symbols = self.sector_map.get(sector, [])
        if not symbols:
            return "LAGGING"

        rs_values = []
        rs_prev_values = []
        for sym in symbols:
            df = sector_stock_dfs.get(sym)
            if df is None or df.empty or len(df) < period + 5:
                continue

            rs_current = self.compute_relative_strength(df, benchmark_df, period)
            rs_values.append(rs_current)

            # RS 5 bars ago (to detect direction)
            df_prev = df.iloc[:-5]
            benchmark_prev = benchmark_df.iloc[:-5] if len(benchmark_df) > 5 else benchmark_df
            rs_prev = self.compute_relative_strength(df_prev, benchmark_prev, period)
            rs_prev_values.append(rs_prev)

        if not rs_values:
            return "LAGGING"

        avg_rs = np.mean(rs_values)
        avg_rs_prev = np.mean(rs_prev_values) if rs_prev_values else avg_rs
        rs_rising = avg_rs > avg_rs_prev

        if avg_rs > 1.0 and rs_rising:
            return "LEADING"
        elif avg_rs > 1.0 and not rs_rising:
            return "WEAKENING"
        elif avg_rs < 1.0 and rs_rising:
            return "IMPROVING"
        else:
            return "LAGGING"

    def get_sector_multiplier(self, symbol: str,
                              phase_override: str = "") -> float:
        """
        Get the sector rotation adjustment multiplier for a symbol.

        Returns:
            Multiplier (0.70 to 1.15) applied to signal score.
        """
        sector = self.symbol_sector.get(symbol, "MISC")
        phase = phase_override or self._sector_phase_cache.get(sector, "LEADING")

        multipliers = {
            "LEADING": 1.15,
            "IMPROVING": 1.05,
            "WEAKENING": 0.90,
            "LAGGING": 0.70,
        }
        return multipliers.get(phase, 1.0)

    def get_symbol_sector(self, symbol: str) -> str:
        """Get the sector for a symbol."""
        return self.symbol_sector.get(symbol, "MISC")

    def update_sector_phases(
        self, all_stock_dfs: dict[str, pd.DataFrame],
        benchmark_df: pd.DataFrame,
    ):
        """
        Update all sector phase classifications.
        Call this periodically (e.g. once per day or every 30 min).
        """
        for sector in self.sector_map:
            # Get DataFrames for stocks in this sector
            sector_dfs = {
                sym: all_stock_dfs[sym]
                for sym in self.sector_map[sector]
                if sym in all_stock_dfs
            }
            phase = self.classify_sector_phase(
                sector, sector_dfs, benchmark_df
            )
            self._sector_phase_cache[sector] = phase

    def get_sector_summary(self) -> dict[str, str]:
        """Return current sector phase classifications."""
        return dict(self._sector_phase_cache)
