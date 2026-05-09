import logging
import os
from datetime import datetime, timezone, timedelta

import httpx

logger = logging.getLogger(__name__)

BLACKOUT_MINUTES = 30  # Block trading N minutes before/after a HIGH impact event


def _parse_event_time(date_str: str) -> datetime | None:
    """Parses FMP date string (YYYY-MM-DD HH:MM:SS or ISO format) as UTC."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _affects_asset(event_country: str, asset_name: str) -> bool:
    """Returns True if this event's country affects the given asset."""
    c = event_country.upper()
    is_usd = c in ("US", "USD")
    is_eur = c in ("EU", "EUR")
    # USD events affect all assets (all are USD-quoted)
    if is_usd:
        return True
    # EUR events only affect EUR/USD
    if is_eur and asset_name == "EUR/USD":
        return True
    return False


async def fetch_high_impact_events() -> list[dict]:
    """
    Fetches today's HIGH impact economic events from FMP.
    Returns empty list if FMP_API_KEY is not set or the request fails.
    Register for a free key at https://financialmodelingprep.com/developer/docs
    """
    api_key = os.environ.get("FMP_API_KEY", "")
    if not api_key:
        return []

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://financialmodelingprep.com/api/v3/economic_calendar",
                params={"from": today, "to": today, "apikey": api_key},
            )
            r.raise_for_status()
            events = r.json()

        high = [
            e for e in events
            if str(e.get("impact", "")).lower() == "high"
        ]
        if high:
            names = [e.get("event", "?") for e in high]
            logger.info(f"Eventos HIGH impact hoy: {names}")
        return high

    except Exception as e:
        logger.warning(f"Calendario económico no disponible: {e}")
        return []


def is_news_blackout(asset_name: str, events: list[dict]) -> bool:
    """
    Returns True if a HIGH impact event affecting this asset
    is within BLACKOUT_MINUTES of now.
    """
    if not events:
        return False

    now = datetime.now(timezone.utc)
    window = timedelta(minutes=BLACKOUT_MINUTES)

    for ev in events:
        if not _affects_asset(ev.get("country", ""), asset_name):
            continue
        ev_time = _parse_event_time(ev.get("date", ""))
        if ev_time is None:
            continue
        if abs(now - ev_time) <= window:
            logger.info(
                f"{asset_name}: blackout por {ev.get('event')} "
                f"({ev.get('country')}) @ {ev.get('date')} UTC"
            )
            return True

    return False
