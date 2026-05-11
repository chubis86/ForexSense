import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

import httpx

logger = logging.getLogger(__name__)

RISK_PCT = 0.01
TP_PCT = 0.02
SL_PCT = 0.01
DAILY_TARGET_PCT = 0.03   # 3.0% daily target — let good days run
DAILY_LOSS_PCT = 0.01   # Stop trading if down -1% on the day
MAX_OPEN_POSITIONS = 2  # Maximum simultaneous trades across all assets
SL_ATR_MULT = 1.5       # ATR multiplier for stop loss
TP_ATR_MULT = 3.0       # ATR multiplier for take profit (1:2 R/R)

BASE_URL = "https://mt-client-api-v1.london.agiliumtrade.ai"

SYMBOL_MAP = {
    "BTC/USD": "BTCUSD",
    "ETH/USD": "ETHUSD",
    "XAU/USD": "XAUUSD",
    "EUR/USD": "EURUSD",
}

CONTRACT_SIZES = {
    "BTCUSD": 1,
    "ETHUSD": 1,
    "XAUUSD": 100,
    "EURUSD": 100_000,
}

# Assets that cannot hold simultaneous positions due to high correlation
CORRELATED_GROUPS: list[frozenset] = [
    frozenset({"BTCUSD", "ETHUSD"}),
]


def _headers() -> dict:
    return {"auth-token": os.environ["METAAPI_TOKEN"]}


def _account_url(path: str) -> str:
    account_id = os.environ["METAAPI_ACCOUNT_ID"]
    return f"{BASE_URL}/users/current/accounts/{account_id}/{path}"


async def _api_get(url: str) -> dict | list:
    """GET with exponential backoff on transient errors (timeout, connection, 5xx)."""
    delay = 1
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(url, headers=_headers())
                r.raise_for_status()
                return r.json()
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                raise
            last_exc = exc
        if attempt < 2:
            logger.warning(f"MetaAPI transient error (attempt {attempt + 1}/3), retry in {delay}s: {last_exc}")
            await asyncio.sleep(delay)
            delay *= 2
    raise last_exc  # type: ignore[misc]


def calculate_lot_size(balance: float, entry_price: float, sl_price: float, symbol: str) -> float:
    risk_amount = balance * RISK_PCT
    sl_distance = abs(entry_price - sl_price)
    if sl_distance == 0:
        return 0.01
    contract_size = CONTRACT_SIZES.get(symbol, 100_000)
    lots = risk_amount / (sl_distance * contract_size)
    return max(0.01, min(round(lots, 2), 10.0))


async def get_balance() -> float:
    data = await _api_get(_account_url("account-information"))
    return float(data["balance"])  # type: ignore[index]


async def get_daily_profit() -> float:
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    now = datetime.now(timezone.utc)
    from_str = today.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    to_str = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    try:
        deals = await _api_get(_account_url(f"history-deals/time/{from_str}/{to_str}"))
        trade_types = {"DEAL_TYPE_BUY", "DEAL_TYPE_SELL"}
        return sum(float(d.get("profit", 0)) for d in deals if d.get("type") in trade_types)  # type: ignore[union-attr]
    except Exception as e:
        logger.error(f"Error obteniendo P&L diario: {e}")
        return 0.0


async def get_open_positions() -> list:
    return await _api_get(_account_url("positions"))  # type: ignore[return-value]


async def has_open_position(symbol: str) -> bool:
    positions = await get_open_positions()
    return any(p["symbol"] == symbol for p in positions)


async def has_open_correlated_position(symbol: str) -> bool:
    """Returns True if another asset in the same correlation group has an open position."""
    group = next((g for g in CORRELATED_GROUPS if symbol in g), None)
    if group is None:
        return False
    positions = await get_open_positions()
    open_symbols = {p["symbol"] for p in positions}
    return bool((group - {symbol}) & open_symbols)


async def get_open_positions_count() -> int:
    return len(await get_open_positions())


async def get_unrealized_pnl() -> float:
    positions = await get_open_positions()
    return sum(float(p.get("unrealizedProfit", 0)) for p in positions)


async def get_closed_deals_since(minutes: int = 90) -> list:
    """Returns closing deals (DEAL_ENTRY_OUT) from the last N minutes."""
    now = datetime.now(timezone.utc)
    from_time = now - timedelta(minutes=minutes)
    from_str = from_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    to_str = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    try:
        deals = await _api_get(_account_url(f"history-deals/time/{from_str}/{to_str}"))
        return [d for d in deals if d.get("entryType") == "DEAL_ENTRY_OUT"]  # type: ignore[union-attr]
    except Exception as e:
        logger.error(f"Error obteniendo deals de cierre: {e}")
        return []


async def open_trade(
    symbol: str,
    signal: str,
    entry_price: float,
    balance: float,
    atr: float | None = None,
) -> dict | None:
    try:
        if atr is not None and atr > 0:
            if signal == "BUY":
                sl = round(entry_price - atr * SL_ATR_MULT, 5)
                tp = round(entry_price + atr * TP_ATR_MULT, 5)
            else:
                sl = round(entry_price + atr * SL_ATR_MULT, 5)
                tp = round(entry_price - atr * TP_ATR_MULT, 5)
        else:
            if signal == "BUY":
                sl = round(entry_price * (1 - SL_PCT), 5)
                tp = round(entry_price * (1 + TP_PCT), 5)
            else:
                sl = round(entry_price * (1 + SL_PCT), 5)
                tp = round(entry_price * (1 - TP_PCT), 5)

        action = "ORDER_TYPE_BUY" if signal == "BUY" else "ORDER_TYPE_SELL"
        lots = calculate_lot_size(balance, entry_price, sl, symbol)

        payload = {
            "actionType": action,
            "symbol": symbol,
            "volume": lots,
            "stopLoss": sl,
            "takeProfit": tp,
            "comment": "ForexSense",
        }

        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(_account_url("trade"), headers=_headers(), json=payload)
            if not r.is_success:
                logger.error(f"{symbol}: MetaAPI {r.status_code} — {r.text[:300]}")
                r.raise_for_status()

        logger.info(f"{symbol}: orden {signal} abierta — {lots} lots | TP={tp} | SL={sl}")
        return {"lots": lots, "sl": sl, "tp": tp}

    except Exception as e:
        logger.error(f"{symbol}: error abriendo orden — {e}")
        return None
