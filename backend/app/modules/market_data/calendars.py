"""Trading calendars for the exchange markets.

Exchange quotes only change during the regular session, so freshness cannot be judged by
wall-clock age alone: a Friday close is still the latest price on Sunday. These helpers
tell whether a market is open and which session close a quote refers to.

Holidays come from the `holidays` package financial calendars (BVMF for B3, NYSE for the
US exchanges). Early closes and exceptional sessions are not modelled; quotes are delayed
anyway and the UI labels them as such. Crypto trades around the clock.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

import holidays

Market = Literal["CRYPTO", "B3", "US"]
SessionState = Literal["open", "closed", "always_open"]


@dataclass(frozen=True, slots=True)
class Session:
    calendar: str
    tz: ZoneInfo
    opens: time
    closes: time


SESSIONS: dict[str, Session] = {
    "B3": Session("BVMF", ZoneInfo("America/Sao_Paulo"), time(10, 0), time(17, 0)),
    "US": Session("NYSE", ZoneInfo("America/New_York"), time(9, 30), time(16, 0)),
}


@dataclass(frozen=True, slots=True)
class MarketStatus:
    market: str
    state: SessionState
    #: close of the latest completed session (None for crypto)
    last_close: datetime | None
    #: next session opening when closed (None for crypto)
    next_open: datetime | None


@lru_cache(maxsize=32)
def _holidays(calendar: str, year: int) -> holidays.HolidayBase:
    return holidays.financial_holidays(calendar, years=year)


def is_trading_day(market: str, day: date) -> bool:
    if market == "CRYPTO":
        return True
    session = SESSIONS[market]
    return day.weekday() < 5 and day not in _holidays(session.calendar, day.year)


def previous_trading_day(market: str, day: date) -> date:
    day -= timedelta(days=1)
    while not is_trading_day(market, day):
        day -= timedelta(days=1)
    return day


def _next_trading_day(market: str, day: date) -> date:
    day += timedelta(days=1)
    while not is_trading_day(market, day):
        day += timedelta(days=1)
    return day


def status(market: str, now: datetime) -> MarketStatus:
    """Session state of `market` at the aware datetime `now`."""
    if market == "CRYPTO":
        return MarketStatus(market, "always_open", None, None)
    session = SESSIONS[market]
    local = now.astimezone(session.tz)
    today = local.date()

    def at(day: date, moment: time) -> datetime:
        return datetime.combine(day, moment, session.tz)

    if is_trading_day(market, today):
        if local < at(today, session.opens):
            return MarketStatus(
                market,
                "closed",
                at(previous_trading_day(market, today), session.closes),
                at(today, session.opens),
            )
        if local < at(today, session.closes):
            return MarketStatus(
                market, "open", at(previous_trading_day(market, today), session.closes), None
            )
        return MarketStatus(
            market,
            "closed",
            at(today, session.closes),
            at(_next_trading_day(market, today), session.opens),
        )
    return MarketStatus(
        market,
        "closed",
        at(previous_trading_day(market, today), session.closes),
        at(_next_trading_day(market, today), session.opens),
    )


def is_stale(market: str, observed_at: datetime, now: datetime, max_age: timedelta) -> bool:
    """Whether a quote observed at `observed_at` is older than the market allows.

    While the market is closed a quote taken after the last close is as fresh as it gets.
    """
    current = status(market, now)
    if current.state == "closed" and current.last_close is not None:
        return observed_at < current.last_close
    return now - observed_at > max_age
