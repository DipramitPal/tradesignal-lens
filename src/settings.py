"""
Centralized settings management using environment variables.
Loads from .env file and provides typed access to all configuration.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")


# --- Directory Paths ---
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
REPORTS_DIR = DATA_DIR / "reports"

# --- Alpha Vantage (fallback when yfinance is unreliable) ---
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
DEFAULT_OUTPUT_SIZE = os.getenv("DEFAULT_OUTPUT_SIZE", "compact")

# --- Indian Market Defaults ---
# Default NSE watchlist (Nifty 50 blue chips + popular mid-caps)
DEFAULT_WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "TITAN.NS",
    "SUNPHARMA.NS", "WIPRO.NS", "TATAMOTORS.NS", "TATASTEEL.NS", "ADANIENT.NS",
]

# Index symbols
NIFTY_50 = "^NSEI"
SENSEX = "^BSESN"
NIFTY_BANK = "^NSEBANK"

# Market hours (IST)
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30
MARKET_TIMEZONE = "Asia/Kolkata"

# --- News API ---
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
NEWS_SOURCES = os.getenv(
    "NEWS_SOURCES",
    "economic-times,the-hindu-business-line,moneycontrol"
).split(",")

# --- Reddit API ---
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "tradesignal-lens/1.0")
REDDIT_SUBREDDITS = os.getenv(
    "REDDIT_SUBREDDITS",
    "IndianStockMarket,IndianStreetBets,DalalStreetTalks,IndiaInvestments"
).split(",")

# --- LLM / AI Engine ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")  # "anthropic" or "openai"
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-4-20250514")

# --- Bot Settings ---
STOCK_SYMBOLS = os.getenv("STOCK_SYMBOLS", "")
if STOCK_SYMBOLS:
    STOCK_SYMBOLS = [s.strip() for s in STOCK_SYMBOLS.split(",")]
else:
    STOCK_SYMBOLS = DEFAULT_WATCHLIST

# Risk thresholds
MAX_RSI_BUY = float(os.getenv("MAX_RSI_BUY", "35"))
MIN_RSI_SELL = float(os.getenv("MIN_RSI_SELL", "65"))
SENTIMENT_WEIGHT = float(os.getenv("SENTIMENT_WEIGHT", "0.3"))
TECHNICAL_WEIGHT = float(os.getenv("TECHNICAL_WEIGHT", "0.7"))
