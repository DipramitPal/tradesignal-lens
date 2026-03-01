"""
Trade journal and performance analytics engine.

Persistent JSON-file-backed trade log that tracks every entry/exit.
Computes rolling performance metrics:
  - Win rate, avg winner vs avg loser
  - Expectancy = (win% × avg_win) - (loss% × avg_loss)
  - Sharpe ratio (annualized)
  - Max drawdown and recovery time
  - Adaptive risk sizing based on recent performance
"""

import json
import os
import math
from datetime import datetime, timedelta
from typing import Optional

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import (
    RISK_PER_TRADE_PCT, DEFAULT_ACCOUNT_VALUE,
)

# Default journal file location
DEFAULT_JOURNAL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "trade_journal.json"
)


class TradeJournal:
    """Persistent trade journal with performance analytics."""

    def __init__(self, journal_path: str = DEFAULT_JOURNAL_PATH):
        self.journal_path = journal_path
        self.trades: list[dict] = []
        self.open_trades: dict[str, dict] = {}  # symbol → trade dict
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self):
        """Load journal from disk."""
        if os.path.exists(self.journal_path):
            try:
                with open(self.journal_path, "r") as f:
                    data = json.load(f)
                self.trades = data.get("trades", [])
                self.open_trades = data.get("open_trades", {})
            except (json.JSONDecodeError, IOError):
                self.trades = []
                self.open_trades = {}
        else:
            # Ensure data directory exists
            os.makedirs(os.path.dirname(self.journal_path), exist_ok=True)

    def _save(self):
        """Persist journal to disk."""
        os.makedirs(os.path.dirname(self.journal_path), exist_ok=True)
        data = {
            "trades": self.trades,
            "open_trades": self.open_trades,
            "last_updated": datetime.now().isoformat(),
        }
        with open(self.journal_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    # ------------------------------------------------------------------
    # Trade Logging
    # ------------------------------------------------------------------

    def log_entry(
        self, *,
        symbol: str,
        entry_price: float,
        shares: int,
        stop_loss: float,
        regime: str = "",
        signal_score: float = 0.0,
        entry_quality: int = 0,
        sector: str = "",
        lots: int = 3,
    ):
        """
        Log a new trade entry.

        Args:
            symbol: Stock symbol
            entry_price: Entry price
            shares: Number of shares bought
            stop_loss: Initial stop-loss price
            regime: Market regime at entry
            signal_score: MTF signal score at entry
            entry_quality: Entry quality score (0-100)
            sector: Stock sector
            lots: Number of lots for scaling out (default 3)
        """
        trade = {
            "symbol": symbol,
            "entry_price": entry_price,
            "entry_date": datetime.now().isoformat(),
            "shares": shares,
            "initial_sl": stop_loss,
            "regime_at_entry": regime,
            "signal_score": signal_score,
            "entry_quality": entry_quality,
            "sector": sector,
            "lots_initial": lots,
            "partial_exits": [],
            "status": "OPEN",
        }
        self.open_trades[symbol] = trade
        self._save()

    def log_partial_exit(
        self, *,
        symbol: str,
        exit_price: float,
        shares_sold: int,
        reason: str = "",
    ):
        """Log a partial exit (scaling out)."""
        if symbol not in self.open_trades:
            return

        trade = self.open_trades[symbol]
        partial = {
            "exit_price": exit_price,
            "exit_date": datetime.now().isoformat(),
            "shares_sold": shares_sold,
            "reason": reason,
            "pnl_pct": round(
                ((exit_price - trade["entry_price"]) / trade["entry_price"]) * 100, 2
            ),
        }
        trade["partial_exits"].append(partial)
        self._save()

    def log_exit(
        self, *,
        symbol: str,
        exit_price: float,
        reason: str = "",
    ):
        """
        Log a full trade exit. Moves trade from open_trades to trades.

        Args:
            symbol: Stock symbol
            exit_price: Final exit price
            reason: Exit reason
        """
        if symbol not in self.open_trades:
            return

        trade = self.open_trades.pop(symbol)
        entry_price = trade["entry_price"]
        initial_sl = trade["initial_sl"]

        # Compute R-multiple
        risk_per_share = abs(entry_price - initial_sl)
        if risk_per_share > 0:
            r_multiple = round((exit_price - entry_price) / risk_per_share, 2)
        else:
            r_multiple = 0.0

        # Compute hold duration
        entry_dt = datetime.fromisoformat(trade["entry_date"])
        hold_duration_hours = round(
            (datetime.now() - entry_dt).total_seconds() / 3600, 1
        )

        # Compute total P&L including partial exits
        total_pnl_pct = round(
            ((exit_price - entry_price) / entry_price) * 100, 2
        )

        trade.update({
            "exit_price": exit_price,
            "exit_date": datetime.now().isoformat(),
            "exit_reason": reason,
            "pnl_pct": total_pnl_pct,
            "r_multiple": r_multiple,
            "hold_duration_hours": hold_duration_hours,
            "is_winner": exit_price > entry_price,
            "status": "CLOSED",
        })

        self.trades.append(trade)
        self._save()

    # ------------------------------------------------------------------
    # Performance Metrics
    # ------------------------------------------------------------------

    def get_performance_metrics(self, lookback_days: int = 30) -> dict:
        """
        Compute rolling performance metrics.

        Args:
            lookback_days: Number of days to look back for metrics

        Returns:
            dict with win_rate, avg_winner, avg_loser, expectancy,
            sharpe_ratio, max_drawdown, total_trades
        """
        cutoff = datetime.now() - timedelta(days=lookback_days)
        recent_trades = [
            t for t in self.trades
            if t.get("status") == "CLOSED"
            and datetime.fromisoformat(t["exit_date"]) >= cutoff
        ]

        if not recent_trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "avg_winner_pct": 0.0,
                "avg_loser_pct": 0.0,
                "avg_r_multiple": 0.0,
                "expectancy": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown_pct": 0.0,
                "lookback_days": lookback_days,
            }

        winners = [t for t in recent_trades if t.get("is_winner")]
        losers = [t for t in recent_trades if not t.get("is_winner")]

        total = len(recent_trades)
        win_rate = len(winners) / total if total > 0 else 0.0
        avg_winner = (
            sum(t["pnl_pct"] for t in winners) / len(winners)
            if winners else 0.0
        )
        avg_loser = (
            sum(t["pnl_pct"] for t in losers) / len(losers)
            if losers else 0.0
        )

        # Expectancy = (win% × avg_win) - (loss% × avg_loss)
        expectancy = (win_rate * avg_winner) - ((1 - win_rate) * abs(avg_loser))

        # R-multiples
        r_multiples = [t.get("r_multiple", 0) for t in recent_trades]
        avg_r = sum(r_multiples) / len(r_multiples) if r_multiples else 0.0

        # Sharpe ratio (annualized from daily returns proxy)
        pnl_series = [t["pnl_pct"] for t in recent_trades]
        sharpe = self._compute_sharpe(pnl_series)

        # Max drawdown from sequential P&L
        max_dd = self._compute_max_drawdown(recent_trades)

        return {
            "total_trades": total,
            "win_rate": round(win_rate, 3),
            "avg_winner_pct": round(avg_winner, 2),
            "avg_loser_pct": round(avg_loser, 2),
            "avg_r_multiple": round(avg_r, 2),
            "expectancy": round(expectancy, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "lookback_days": lookback_days,
        }

    def get_adaptive_risk_pct(self, lookback_days: int = 30) -> float:
        """
        Dynamically adjust risk per trade based on recent performance.

        Rules:
            - Win rate < 30%: reduce to 0.5% risk per trade
            - Win rate < 40%: reduce to 1.0%
            - Win rate 40-55%: normal 2.0%
            - Win rate > 55%: increase to 2.5%
            - Max drawdown > 6%: override to 1.0% regardless

        Returns:
            Adjusted risk percentage (e.g., 0.02 for 2%)
        """
        metrics = self.get_performance_metrics(lookback_days)
        base_risk = RISK_PER_TRADE_PCT

        if metrics["total_trades"] < 5:
            return base_risk  # Not enough data

        win_rate = metrics["win_rate"]
        max_dd = metrics["max_drawdown_pct"]

        # Drawdown override
        if max_dd > 6.0:
            return 0.01  # 1% risk

        # Win-rate based adjustment
        if win_rate < 0.30:
            return 0.005  # 0.5%
        elif win_rate < 0.40:
            return 0.01  # 1%
        elif win_rate > 0.55:
            return 0.025  # 2.5%

        return base_risk

    def get_daily_pnl(self) -> float:
        """
        Compute today's realized P&L from closed trades.

        Returns:
            Sum of P&L percentages for trades closed today.
        """
        today = datetime.now().date()
        today_trades = [
            t for t in self.trades
            if (t.get("status") == "CLOSED"
                and datetime.fromisoformat(t["exit_date"]).date() == today)
        ]
        return sum(t.get("pnl_pct", 0) for t in today_trades)

    def get_summary_text(self, lookback_days: int = 30) -> str:
        """Return a formatted summary string of performance metrics."""
        m = self.get_performance_metrics(lookback_days)
        if m["total_trades"] == 0:
            return "No trades in the last {} days.".format(lookback_days)

        return (
            f"  📊 Performance ({m['lookback_days']}d): "
            f"{m['total_trades']} trades | "
            f"Win: {m['win_rate']:.0%} | "
            f"Avg W: +{m['avg_winner_pct']:.1f}% | "
            f"Avg L: {m['avg_loser_pct']:.1f}% | "
            f"Exp: {m['expectancy']:.2f} | "
            f"Sharpe: {m['sharpe_ratio']:.2f} | "
            f"MaxDD: {m['max_drawdown_pct']:.1f}%"
        )

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_sharpe(pnl_series: list[float], risk_free_annual: float = 0.06) -> float:
        """
        Compute annualized Sharpe ratio from a list of trade P&L percentages.
        Assumes ~250 trading days per year.
        """
        if len(pnl_series) < 2:
            return 0.0

        import numpy as np
        returns = np.array(pnl_series) / 100.0
        mean_return = np.mean(returns)
        std_return = np.std(returns, ddof=1)

        if std_return == 0:
            return 0.0

        # Annualize: assuming trades happen on average daily
        daily_rf = risk_free_annual / 250
        sharpe = (mean_return - daily_rf) / std_return
        annualized_sharpe = sharpe * math.sqrt(250 / max(len(pnl_series), 1))

        return annualized_sharpe

    @staticmethod
    def _compute_max_drawdown(trades: list[dict]) -> float:
        """
        Compute max drawdown from sequential trade P&L.

        Returns:
            Maximum drawdown as a positive percentage.
        """
        if not trades:
            return 0.0

        # Sort by exit date
        sorted_trades = sorted(
            trades,
            key=lambda t: t.get("exit_date", "")
        )

        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0

        for t in sorted_trades:
            cumulative += t.get("pnl_pct", 0)
            peak = max(peak, cumulative)
            drawdown = peak - cumulative
            max_dd = max(max_dd, drawdown)

        return max_dd
