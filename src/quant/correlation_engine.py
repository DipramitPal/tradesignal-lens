"""
Portfolio correlation and risk engine.

Implements:
  - Rolling pairwise correlation matrix
  - Correlation conflict detection for new positions
  - Portfolio Value at Risk (VaR) at 95% confidence
  - Drawdown circuit breaker (pause BUYs if drawdown > threshold)
"""

import numpy as np
import pandas as pd
from typing import Optional

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import DEFAULT_ACCOUNT_VALUE


# --- Configuration defaults ---
CORRELATION_LOOKBACK = 30       # days for rolling correlation
MAX_CORRELATION = 0.70          # max acceptable cross-position correlation
MAX_DRAWDOWN_PCT = 0.08         # 8% max portfolio drawdown triggers circuit breaker
VAR_CONFIDENCE = 0.95           # VaR confidence level
MAX_DAILY_VAR_PCT = 0.03        # block trade if portfolio VaR > 3% of account


class CorrelationEngine:
    """Portfolio-level correlation and risk management."""

    def __init__(
        self,
        account_value: float = DEFAULT_ACCOUNT_VALUE,
        lookback: int = CORRELATION_LOOKBACK,
        max_correlation: float = MAX_CORRELATION,
        max_drawdown_pct: float = MAX_DRAWDOWN_PCT,
    ):
        self.account_value = account_value
        self.lookback = lookback
        self.max_correlation = max_correlation
        self.max_drawdown_pct = max_drawdown_pct
        self._portfolio_peak = account_value
        self._current_portfolio_value = account_value

    # ------------------------------------------------------------------
    # Correlation Analysis
    # ------------------------------------------------------------------

    def compute_correlation_matrix(
        self,
        daily_data: dict[str, pd.DataFrame],
        symbols: list[str],
    ) -> pd.DataFrame:
        """
        Compute rolling pairwise correlation matrix from daily close prices.

        Args:
            daily_data: symbol → daily DataFrame with 'close' column
            symbols: list of symbols to include

        Returns:
            Correlation matrix as a DataFrame (symbols × symbols)
        """
        close_prices = {}
        for sym in symbols:
            df = daily_data.get(sym)
            if df is not None and not df.empty and len(df) >= self.lookback:
                close_prices[sym] = df["close"].iloc[-self.lookback:]

        if len(close_prices) < 2:
            return pd.DataFrame()

        price_df = pd.DataFrame(close_prices)
        # Compute returns-based correlation (more stable than price-level)
        returns_df = price_df.pct_change().dropna()

        if returns_df.empty or len(returns_df) < 5:
            return pd.DataFrame()

        return returns_df.corr()

    def check_correlation_conflict(
        self,
        new_symbol: str,
        existing_symbols: list[str],
        daily_data: dict[str, pd.DataFrame],
    ) -> tuple[bool, float, str]:
        """
        Check if a new position has high correlation with existing positions.

        Args:
            new_symbol: symbol being considered for purchase
            existing_symbols: symbols already in the portfolio
            daily_data: symbol → daily DataFrame

        Returns:
            (has_conflict, max_corr_value, conflicting_symbol)
        """
        if not existing_symbols:
            return False, 0.0, ""

        all_symbols = list(set(existing_symbols + [new_symbol]))
        corr_matrix = self.compute_correlation_matrix(daily_data, all_symbols)

        if corr_matrix.empty or new_symbol not in corr_matrix.columns:
            return False, 0.0, ""

        max_corr = 0.0
        conflicting = ""

        for sym in existing_symbols:
            if sym in corr_matrix.columns:
                corr = abs(corr_matrix.loc[new_symbol, sym])
                if corr > max_corr:
                    max_corr = corr
                    conflicting = sym

        has_conflict = max_corr > self.max_correlation
        return has_conflict, round(max_corr, 3), conflicting

    def get_position_size_adjustment(
        self,
        new_symbol: str,
        existing_symbols: list[str],
        daily_data: dict[str, pd.DataFrame],
        base_shares: int,
    ) -> tuple[int, str]:
        """
        Adjust position size based on correlation with existing portfolio.

        Args:
            new_symbol: symbol being considered
            existing_symbols: current portfolio symbols
            daily_data: symbol → daily DataFrame
            base_shares: original position size

        Returns:
            (adjusted_shares, reason_str)
        """
        has_conflict, max_corr, conflicting = self.check_correlation_conflict(
            new_symbol, existing_symbols, daily_data
        )

        if has_conflict:
            adjusted = max(1, base_shares // 2)
            reason = (
                f"Position halved ({base_shares}→{adjusted} shares): "
                f"corr {max_corr:.2f} with {conflicting}"
            )
            return adjusted, reason

        return base_shares, ""

    # ------------------------------------------------------------------
    # Portfolio VaR
    # ------------------------------------------------------------------

    def compute_portfolio_var(
        self,
        daily_data: dict[str, pd.DataFrame],
        position_values: dict[str, float],
        confidence: float = VAR_CONFIDENCE,
    ) -> float:
        """
        Compute portfolio Value at Risk (VaR) at given confidence level.

        Args:
            daily_data: symbol → daily DataFrame with 'close'
            position_values: symbol → current position value in ₹
            confidence: VaR confidence level (default 0.95)

        Returns:
            VaR as a positive number (potential loss in ₹)
        """
        symbols = list(position_values.keys())
        if not symbols:
            return 0.0

        # Build returns matrix
        returns_data = {}
        for sym in symbols:
            df = daily_data.get(sym)
            if df is not None and not df.empty and len(df) >= self.lookback:
                returns_data[sym] = df["close"].pct_change().dropna().iloc[-self.lookback:]

        if not returns_data:
            return 0.0

        returns_df = pd.DataFrame(returns_data).dropna()
        if returns_df.empty or len(returns_df) < 5:
            return 0.0

        # Portfolio weights
        total_value = sum(position_values.values())
        if total_value <= 0:
            return 0.0

        weights = np.array([
            position_values.get(sym, 0) / total_value
            for sym in returns_df.columns
        ])

        # Portfolio returns
        portfolio_returns = returns_df.values @ weights

        # Historical VaR (percentile method)
        var_pct = np.percentile(portfolio_returns, (1 - confidence) * 100)

        return round(abs(var_pct) * total_value, 2)

    def check_var_limit(
        self,
        daily_data: dict[str, pd.DataFrame],
        position_values: dict[str, float],
    ) -> tuple[bool, float]:
        """
        Check if portfolio VaR exceeds the daily limit.

        Returns:
            (exceeds_limit, current_var_pct)
        """
        var = self.compute_portfolio_var(daily_data, position_values)
        var_pct = var / self.account_value if self.account_value > 0 else 0
        return var_pct > MAX_DAILY_VAR_PCT, round(var_pct, 4)

    # ------------------------------------------------------------------
    # Drawdown Circuit Breaker
    # ------------------------------------------------------------------

    def update_portfolio_value(self, current_value: float):
        """Update current portfolio value and track peak."""
        self._current_portfolio_value = current_value
        self._portfolio_peak = max(self._portfolio_peak, current_value)

    def get_current_drawdown(self) -> float:
        """
        Get current portfolio drawdown from peak.

        Returns:
            Drawdown as a positive percentage (e.g., 0.05 for 5%)
        """
        if self._portfolio_peak <= 0:
            return 0.0
        dd = (self._portfolio_peak - self._current_portfolio_value) / self._portfolio_peak
        return max(0.0, dd)

    def check_drawdown_circuit_breaker(self) -> tuple[bool, float]:
        """
        Check if drawdown exceeds the circuit breaker threshold.

        Returns:
            (circuit_breaker_active, current_drawdown_pct)
        """
        dd = self.get_current_drawdown()
        return dd > self.max_drawdown_pct, round(dd, 4)

    def reset_peak(self):
        """Reset peak to current value (e.g., after new capital injection)."""
        self._portfolio_peak = self._current_portfolio_value
