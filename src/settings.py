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

# --- Indian Market Defaults ---
# Default NSE watchlist (blue chips + popular mid-caps)
# yfinance uses .NS suffix for NSE and .BO suffix for BSE
DEFAULT_WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "TITAN.NS",
    "SUNPHARMA.NS", "WIPRO.NS", "TATAMOTORS.NS", "TATASTEEL.NS", "ADANIENT.NS",
]

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

# --- Live Monitoring ---
MONITOR_INTERVAL_MINUTES = int(os.getenv("MONITOR_INTERVAL_MINUTES", "15"))
MONITOR_SYMBOLS = os.getenv("MONITOR_SYMBOLS", "")
if MONITOR_SYMBOLS:
    MONITOR_SYMBOLS = [s.strip() for s in MONITOR_SYMBOLS.split(",")]
else:
    MONITOR_SYMBOLS = STOCK_SYMBOLS

# --- Intraday / Scan Settings ---
INTRADAY_INTERVAL = os.getenv("INTRADAY_INTERVAL", "15m")
SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "15"))
UNIVERSE_RESCAN_INTERVAL = int(os.getenv("UNIVERSE_RESCAN_INTERVAL", "30"))

# --- Risk Management ---
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "0.02"))
MIN_RR_RATIO = float(os.getenv("MIN_RR_RATIO", "2.0"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "5"))
MAX_SECTOR_EXPOSURE = float(os.getenv("MAX_SECTOR_EXPOSURE", "0.30"))
DAILY_LOSS_LIMIT = float(os.getenv("DAILY_LOSS_LIMIT", "0.04"))
DEFAULT_ACCOUNT_VALUE = float(os.getenv("DEFAULT_ACCOUNT_VALUE", "1000000"))

# --- NIFTY 200 Scan Universe ---
# Full NIFTY 200 constituent list (NSE symbols with .NS suffix).
# Updated quarterly; source: NSE India index composition.
SCAN_UNIVERSE = [
    # NIFTY 50
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "TITAN.NS",
    "SUNPHARMA.NS", "WIPRO.NS", "TATAMOTORS.NS", "TATASTEEL.NS", "ADANIENT.NS",
    "BAJFINANCE.NS", "BAJAJFINSV.NS", "HCLTECH.NS", "NTPC.NS", "POWERGRID.NS",
    "ULTRACEMCO.NS", "NESTLEIND.NS", "TECHM.NS", "JSWSTEEL.NS", "M&M.NS",
    "INDUSINDBK.NS", "ONGC.NS", "HINDALCO.NS", "COALINDIA.NS", "GRASIM.NS",
    "CIPLA.NS", "DRREDDY.NS", "BPCL.NS", "EICHERMOT.NS", "DIVISLAB.NS",
    "APOLLOHOSP.NS", "TATACONSUM.NS", "SBILIFE.NS", "HEROMOTOCO.NS", "BRITANNIA.NS",
    "BAJAJ-AUTO.NS", "HDFCLIFE.NS", "ADANIPORTS.NS", "LTIM.NS", "SHRIRAMFIN.NS",
    # NIFTY NEXT 50
    "BANKBARODA.NS", "VEDL.NS", "HAVELLS.NS", "GODREJCP.NS", "DLF.NS",
    "DABUR.NS", "SIEMENS.NS", "PIDILITIND.NS", "ABB.NS", "BOSCHLTD.NS",
    "AMBUJACEM.NS", "TRENT.NS", "ZOMATO.NS", "ADANIGREEN.NS", "ADANIPOWER.NS",
    "INDIGO.NS", "IOC.NS", "GAIL.NS", "NAUKRI.NS", "MOTHERSON.NS",
    "MARICO.NS", "BERGEPAINT.NS", "COLPAL.NS", "PEL.NS", "MUTHOOTFIN.NS",
    "IRCTC.NS", "PIIND.NS", "PNB.NS", "TATAPOWER.NS", "JINDALSTEL.NS",
    "CHOLAFIN.NS", "CANBK.NS", "TORNTPHARM.NS", "MAXHEALTH.NS", "PAGEIND.NS",
    "IDFCFIRSTB.NS", "HAL.NS", "BEL.NS", "PERSISTENT.NS", "COFORGE.NS",
    "MPHASIS.NS", "OBEROIRLTY.NS", "POLYCAB.NS", "SOLARINDS.NS", "MANKIND.NS",
    "LODHA.NS", "TVSMOTOR.NS", "DMART.NS", "ATGL.NS", "PHOENIXLTD.NS",
    # NIFTY MIDCAP SELECT & OTHERS
    "FEDERALBNK.NS", "VOLTAS.NS", "ESCORTS.NS", "IDBI.NS", "MRF.NS",
    "LICHSGFIN.NS", "AUROPHARMA.NS", "BIOCON.NS", "LUPIN.NS", "ALKEM.NS",
    "ASTRAL.NS", "CROMPTON.NS", "DEEPAKNTR.NS", "LALPATHLAB.NS", "LTTS.NS",
    "NAVINFLUOR.NS", "SRF.NS", "JUBLFOOD.NS", "PETRONET.NS", "CONCOR.NS",
    "NMDC.NS", "SAIL.NS", "RECLTD.NS", "PFC.NS", "NHPC.NS",
    "IRFC.NS", "BHEL.NS", "FACT.NS", "IDEA.NS", "GMRINFRA.NS",
    "ZEEL.NS", "UPL.NS", "BALRAMCHIN.NS", "BATAINDIA.NS", "CANFINHOME.NS",
    "CENTRALBK.NS", "CUMMINSIND.NS", "EXIDEIND.NS", "GLENMARK.NS", "HINDPETRO.NS",
    "IPCALAB.NS", "L&TFH.NS", "MFSL.NS", "NATCOPHARM.NS", "OFSS.NS",
    "RAJESHEXPO.NS", "RAMCOCEM.NS", "STARHEALTH.NS", "SUPREMEIND.NS", "SYNGENE.NS",
    "TATACOMM.NS", "TATAELXSI.NS", "TATACHEM.NS", "THERMAX.NS", "TIMKEN.NS",
    "UNITDSPR.NS", "WHIRLPOOL.NS", "ZYDUSLIFE.NS",
]

# --- Sector Mapping ---
SECTOR_MAP = {
    "IT": [
        "TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS",
        "LTIM.NS", "PERSISTENT.NS", "COFORGE.NS", "MPHASIS.NS", "LTTS.NS",
        "TATAELXSI.NS", "NAUKRI.NS", "OFSS.NS",
    ],
    "BANKING": [
        "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS",
        "INDUSINDBK.NS", "BANKBARODA.NS", "PNB.NS", "CANBK.NS", "IDFCFIRSTB.NS",
        "FEDERALBNK.NS", "IDBI.NS", "CENTRALBK.NS",
    ],
    "NBFC": [
        "BAJFINANCE.NS", "BAJAJFINSV.NS", "SHRIRAMFIN.NS", "CHOLAFIN.NS",
        "MUTHOOTFIN.NS", "PEL.NS", "MFSL.NS", "CANFINHOME.NS", "L&TFH.NS",
        "LICHSGFIN.NS",
    ],
    "PHARMA": [
        "SUNPHARMA.NS", "CIPLA.NS", "DRREDDY.NS", "DIVISLAB.NS", "LUPIN.NS",
        "AUROPHARMA.NS", "BIOCON.NS", "ALKEM.NS", "TORNTPHARM.NS", "IPCALAB.NS",
        "NATCOPHARM.NS", "GLENMARK.NS", "ZYDUSLIFE.NS", "LALPATHLAB.NS", "SYNGENE.NS",
        "MANKIND.NS", "MAXHEALTH.NS", "APOLLOHOSP.NS", "STARHEALTH.NS",
    ],
    "AUTO": [
        "TATAMOTORS.NS", "MARUTI.NS", "M&M.NS", "BAJAJ-AUTO.NS", "EICHERMOT.NS",
        "HEROMOTOCO.NS", "TVSMOTOR.NS", "MOTHERSON.NS", "ESCORTS.NS", "EXIDEIND.NS",
        "MRF.NS", "BATAINDIA.NS",
    ],
    "METALS": [
        "TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS", "VEDL.NS", "SAIL.NS",
        "NMDC.NS", "JINDALSTEL.NS", "COALINDIA.NS",
    ],
    "ENERGY": [
        "RELIANCE.NS", "ONGC.NS", "BPCL.NS", "IOC.NS", "GAIL.NS",
        "PETRONET.NS", "HINDPETRO.NS", "NTPC.NS", "POWERGRID.NS", "TATAPOWER.NS",
        "NHPC.NS", "ADANIGREEN.NS", "ADANIPOWER.NS", "IRFC.NS", "RECLTD.NS",
        "PFC.NS",
    ],
    "FMCG": [
        "HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS", "TATACONSUM.NS",
        "DABUR.NS", "MARICO.NS", "COLPAL.NS", "GODREJCP.NS", "UNITDSPR.NS",
        "RAJESHEXPO.NS", "BALRAMCHIN.NS",
    ],
    "INFRA": [
        "LT.NS", "ADANIENT.NS", "ADANIPORTS.NS", "DLF.NS", "OBEROIRLTY.NS",
        "LODHA.NS", "ULTRACEMCO.NS", "AMBUJACEM.NS", "GRASIM.NS", "RAMCOCEM.NS",
        "HAL.NS", "BEL.NS", "BHEL.NS", "SIEMENS.NS", "ABB.NS",
        "THERMAX.NS", "CUMMINSIND.NS", "GMRINFRA.NS", "CONCOR.NS", "IRCTC.NS",
    ],
    "CONSUMER": [
        "TITAN.NS", "ASIANPAINT.NS", "PIDILITIND.NS", "HAVELLS.NS", "VOLTAS.NS",
        "CROMPTON.NS", "WHIRLPOOL.NS", "PAGEIND.NS", "TRENT.NS", "JUBLFOOD.NS",
        "ZOMATO.NS", "DMART.NS", "BERGEPAINT.NS", "BOSCHLTD.NS", "TIMKEN.NS",
    ],
    "CHEMICALS": [
        "SRF.NS", "PIIND.NS", "DEEPAKNTR.NS", "NAVINFLUOR.NS", "UPL.NS",
        "TATACHEM.NS", "ASTRAL.NS", "FACT.NS",
    ],
    "INSURANCE": [
        "SBILIFE.NS", "HDFCLIFE.NS",
    ],
    "TELECOM": [
        "BHARTIARTL.NS", "IDEA.NS", "TATACOMM.NS", "INDIGO.NS",
    ],
    "MEDIA": [
        "ZEEL.NS", "PHOENIXLTD.NS",
    ],
    "MISC": [
        "POLYCAB.NS", "SOLARINDS.NS", "SUPREMEIND.NS", "ATGL.NS",
    ],
}

# Build reverse lookup: symbol → sector
SYMBOL_SECTOR = {}
for sector, symbols in SECTOR_MAP.items():
    for sym in symbols:
        SYMBOL_SECTOR[sym] = sector
