import unittest

import pandas as pd

from src.quant.swing_engine import BREAKOUT, NO_SETUP, PULLBACK, classify_swing_setup


def _daily_frame(closes, volumes=None):
    volumes = volumes or [1000] * len(closes)
    df = pd.DataFrame(
        {
            "open": [c * 0.99 for c in closes],
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.98 for c in closes],
            "close": closes,
            "volume": volumes,
        },
        index=pd.date_range("2024-01-01", periods=len(closes), freq="D"),
    )
    df["ema_21"] = df["close"].ewm(span=21, adjust=False).mean()
    df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()
    high_low = df["high"] - df["low"]
    high_close_prev = (df["high"] - df["close"].shift(1)).abs()
    low_close_prev = (df["low"] - df["close"].shift(1)).abs()
    df["atr"] = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1).rolling(14).mean()
    df["rsi"] = 50
    df["adx"] = 25
    df["cmf"] = 0.1
    df["squeeze_fire"] = 0
    df["momentum_5"] = df["close"] - df["close"].shift(5)
    return df


class SwingEngineTests(unittest.TestCase):
    def test_breakout_setup_uses_structure_stop(self):
        closes = [100 + i * 0.2 for i in range(80)] + [122]
        volumes = [1000] * 80 + [2500]
        df = _daily_frame(closes, volumes)

        setup = classify_swing_setup(df, current_price=float(df["close"].iloc[-1]), rvol=2.0)

        self.assertEqual(setup.setup_type, BREAKOUT)
        self.assertGreaterEqual(setup.quality_score, 50)
        self.assertGreater(setup.stop_loss, 0)
        self.assertLess(setup.stop_loss, float(df["close"].iloc[-1]))

    def test_pullback_setup_detects_controlled_pullback(self):
        uptrend = [100 + i * 0.5 for i in range(90)]
        pullback = [144, 142, 141, 140]
        df = _daily_frame(uptrend + pullback)

        setup = classify_swing_setup(df, current_price=float(df["close"].iloc[-1]), rvol=1.0)

        self.assertEqual(setup.setup_type, PULLBACK)
        self.assertGreaterEqual(setup.quality_score, 50)

    def test_no_setup_when_history_is_too_short(self):
        df = _daily_frame([100 + i for i in range(30)])

        setup = classify_swing_setup(df, current_price=float(df["close"].iloc[-1]), rvol=1.0)

        self.assertEqual(setup.setup_type, NO_SETUP)


if __name__ == "__main__":
    unittest.main()
