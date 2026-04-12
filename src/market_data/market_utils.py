"""
Indian stock market utilities: market hours, holidays, trading day checks.
"""

from datetime import datetime, time, date
import pytz

MARKET_TZ = pytz.timezone("Asia/Kolkata")

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)

# Major NSE holidays for 2025-2026 (update annually)
# Source: NSE website
NSE_HOLIDAYS_2025 = [
    date(2025, 1, 26),   # Republic Day
    date(2025, 2, 26),   # Maha Shivaratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-ul-Fitr (Eid)
    date(2025, 4, 10),   # Ram Navami
    date(2025, 4, 14),   # Dr. Ambedkar Jayanti
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 6, 7),    # Bakrid
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 16),   # Janmashtami
    date(2025, 10, 2),   # Mahatma Gandhi Jayanti
    date(2025, 10, 21),  # Diwali (Lakshmi Puja)
    date(2025, 10, 22),  # Diwali Balipratipada
    date(2025, 11, 5),   # Guru Nanak Jayanti
    date(2025, 12, 25),  # Christmas
]

NSE_HOLIDAYS_2026 = [
    date(2026, 1, 26),   # Republic Day
    date(2026, 2, 17),   # Maha Shivaratri
    date(2026, 3, 3),    # Holi
    date(2026, 3, 20),   # Id-ul-Fitr (Eid)
    date(2026, 3, 30),   # Ram Navami
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 5, 27),   # Bakrid
    date(2026, 8, 15),   # Independence Day
    date(2026, 8, 25),   # Muharram
    date(2026, 10, 2),   # Mahatma Gandhi Jayanti
    date(2026, 10, 9),   # Dussehra
    date(2026, 11, 9),   # Diwali (Lakshmi Puja)
    date(2026, 11, 10),  # Diwali Balipratipada
    date(2026, 11, 25),  # Guru Nanak Jayanti
    date(2026, 12, 25),  # Christmas
]

ALL_HOLIDAYS = set(NSE_HOLIDAYS_2025 + NSE_HOLIDAYS_2026)


def now_ist() -> datetime:
    """Get current datetime in IST."""
    return datetime.now(MARKET_TZ)


def is_market_open() -> bool:
    """Check if NSE market is currently open."""
    now = now_ist()

    # Weekend check
    if now.weekday() >= 5:
        return False

    # Holiday check
    if now.date() in ALL_HOLIDAYS:
        return False

    # Time check
    current_time = now.time()
    return MARKET_OPEN <= current_time <= MARKET_CLOSE


def is_trading_day(check_date: date | None = None) -> bool:
    """Check if a given date is a trading day (not weekend, not holiday)."""
    if check_date is None:
        check_date = now_ist().date()

    if check_date.weekday() >= 5:
        return False

    if check_date in ALL_HOLIDAYS:
        return False

    return True


def get_market_holidays(year: int = None) -> list[date]:
    """Get list of market holidays for a given year."""
    if year == 2025:
        return NSE_HOLIDAYS_2025
    elif year == 2026:
        return NSE_HOLIDAYS_2026
    return sorted(ALL_HOLIDAYS)


def next_market_open() -> datetime:
    """Get the next market open datetime in IST."""
    now = now_ist()
    candidate = now.replace(
        hour=MARKET_OPEN.hour,
        minute=MARKET_OPEN.minute,
        second=0,
        microsecond=0,
    )

    # If market hasn't opened yet today and it's a trading day
    if now.time() < MARKET_OPEN and is_trading_day(now.date()):
        return candidate

    # Find next trading day
    from datetime import timedelta
    candidate += timedelta(days=1)
    while not is_trading_day(candidate.date()):
        candidate += timedelta(days=1)

    return candidate.replace(
        hour=MARKET_OPEN.hour,
        minute=MARKET_OPEN.minute,
        second=0,
        microsecond=0,
    )


def market_status() -> dict:
    """Get comprehensive market status."""
    now = now_ist()
    open_now = is_market_open()

    return {
        "ist_time": now.strftime("%Y-%m-%d %H:%M:%S IST"),
        "is_open": open_now,
        "is_trading_day": is_trading_day(now.date()),
        "next_open": next_market_open().strftime("%Y-%m-%d %H:%M IST") if not open_now else "NOW",
        "market_hours": f"{MARKET_OPEN.strftime('%H:%M')} - {MARKET_CLOSE.strftime('%H:%M')} IST",
    }
