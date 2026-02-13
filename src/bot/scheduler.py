"""
Scheduler for autonomous 24/7 bot mode (future enhancement).
Provides scheduled task execution aligned with Indian market hours.
"""

import time
import signal
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TradingScheduler:
    """
    Scheduler for running the trading bot autonomously.

    Planned schedule:
    - Pre-market (8:30 AM IST): Daily brief, news scan, set alerts
    - Market open (9:15 AM IST): Execute pending signals
    - Intraday (every 30 min): Monitor positions, check alerts
    - Market close (3:30 PM IST): End-of-day summary
    - After hours (6:00 PM IST): Deep analysis for next day
    - Overnight: Social media monitoring, global market scan

    This is a foundation module. Full autonomous mode will be
    implemented as a future enhancement.
    """

    def __init__(self):
        self.running = False
        self.tasks = []

    def add_task(self, name: str, func, schedule: str, **kwargs):
        """
        Register a scheduled task.

        Args:
            name: Task name for logging
            func: Callable to execute
            schedule: Schedule type - "pre_market", "market_open",
                      "intraday", "market_close", "after_hours"
        """
        self.tasks.append({
            "name": name,
            "func": func,
            "schedule": schedule,
            "kwargs": kwargs,
            "last_run": None,
        })

    def start(self):
        """Start the scheduler loop (placeholder for future implementation)."""
        from market_data.market_utils import is_market_open, now_ist, next_market_open

        self.running = True

        # Handle graceful shutdown
        def shutdown_handler(signum, frame):
            print("\nShutting down scheduler...")
            self.running = False

        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGTERM, shutdown_handler)

        print("Trading Scheduler started.")
        print("Press Ctrl+C to stop.\n")

        while self.running:
            now = now_ist()
            current_hour = now.hour
            current_minute = now.minute

            # Pre-market: 8:30 AM
            if current_hour == 8 and current_minute == 30:
                self._run_tasks("pre_market")

            # Market open: 9:15 AM
            elif current_hour == 9 and current_minute == 15:
                self._run_tasks("market_open")

            # Intraday: every 30 minutes during market hours
            elif is_market_open() and current_minute in (0, 30):
                self._run_tasks("intraday")

            # Market close: 3:30 PM
            elif current_hour == 15 and current_minute == 30:
                self._run_tasks("market_close")

            # After hours: 6:00 PM
            elif current_hour == 18 and current_minute == 0:
                self._run_tasks("after_hours")

            # Sleep until next minute
            time.sleep(60)

    def stop(self):
        """Stop the scheduler."""
        self.running = False

    def _run_tasks(self, schedule: str):
        """Execute all tasks matching the given schedule."""
        for task in self.tasks:
            if task["schedule"] == schedule:
                now = datetime.now()
                # Avoid re-running within the same minute
                if task["last_run"] and (now - task["last_run"]).seconds < 60:
                    continue

                print(f"[{now.strftime('%H:%M:%S')}] Running: {task['name']}")
                try:
                    task["func"](**task["kwargs"])
                    task["last_run"] = now
                except Exception as e:
                    print(f"  Error in {task['name']}: {e}")
