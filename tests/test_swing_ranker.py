import unittest

import pandas as pd

from src.quant.swing_ranker import compute_swing_rank


def _daily_frame(closes):
    df = pd.DataFrame(
        {
            "open": [c * 0.99 for c in closes],
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.98 for c in closes],
            "close": closes,
            "volume": [1000] * len(closes),
        },
        index=pd.date_range("2024-01-01", periods=len(closes), freq="D"),
    )
    df["ema_21"] = df["close"].ewm(span=21, adjust=False).mean()
    df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["adx"] = 28
    return df


class SwingRankerTests(unittest.TestCase):
    def test_strong_breakout_candidate_scores_above_weak_candidate(self):
        strong = _daily_frame([100 + i * 0.7 for i in range(130)])
        weak = _daily_frame([100 - i * 0.1 for i in range(130)])
        price_strong = float(strong["close"].iloc[-1])
        price_weak = float(weak["close"].iloc[-1])

        strong_rank = compute_swing_rank(
            strong,
            price=price_strong,
            swing_setup={
                "setup_type": "BREAKOUT",
                "quality_score": 80,
                "stop_loss": price_strong * 0.92,
            },
            mtf_score=0.65,
            entry_quality=80,
            rvol=1.8,
            sector_multiplier=1.15,
        )
        weak_rank = compute_swing_rank(
            weak,
            price=price_weak,
            swing_setup={
                "setup_type": "NO_SETUP",
                "quality_score": 0,
                "stop_loss": 0,
            },
            mtf_score=0.15,
            entry_quality=30,
            rvol=0.7,
            sector_multiplier=0.9,
        )

        self.assertGreater(strong_rank["score"], weak_rank["score"])
        self.assertIn(strong_rank["bucket"], {"A+", "A", "B"})
        self.assertEqual(weak_rank["bucket"], "AVOID")

    def test_rank_requires_enough_history(self):
        df = _daily_frame([100 + i for i in range(20)])

        rank = compute_swing_rank(
            df,
            price=float(df["close"].iloc[-1]),
            swing_setup={"setup_type": "BREAKOUT", "quality_score": 80, "stop_loss": 110},
            mtf_score=0.7,
            entry_quality=80,
            rvol=2.0,
        )

        self.assertEqual(rank["score"], 0.0)
        self.assertEqual(rank["bucket"], "AVOID")


if __name__ == "__main__":
    unittest.main()
