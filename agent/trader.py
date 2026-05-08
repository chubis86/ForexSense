import logging
import os
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

RISK_PCT = 0.01
TP_PCT = 0.02
SL_PCT = 0.01
DAILY_TARGET_PCT = 0.02

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


def _headers() -> dict:
    return {"auth-token": os.environ["METAAPI_TOKEN"]}


def _account_url(path: str) -> str:
    account_id = os.environ["METAAPI_ACCOUNT_ID"]
    return f"{BASE_URL}/users/current/accounts/{account_id}/{path}"


def calculate_lot_size(balance: float, entry_price: float, sl_price: float, symbol: str) -> float:
    risk_amount = balance * RISK_PCT
    sl_distance = abs(entry_price - sl_price)
    if sl_distance == 0:
        return 0.01
    contract_size = CONTRACT_SIZES.get(symbol, 100_000)
    lots = risk_amount / (sl_distance * contract_size)
    return max(0.01, min(round(lots, 2), 10.0))


async def get_balance() -> float:
    async with httpx.AsyncClient(timeout=15, verify=False) as client:
        r = await client.get(_account_url("account-information"), headers=_headers())
        r.raise_for_status()
        return float(r.json()["balance"])


async def get_daily_profit() -> float:
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    now = datetime.now(timezone.utc)
    from_str = today.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    to_str = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    try:
        async with httpx.AsyncClient(timeout=15, verify=False) as client:
            r = await client.get(
                _account_url(f"history-deals/time/{from_str}/{to_str}"),
                headers=_headers(),
            )
            r.raise_for_status()
            deals = r.json()
            trade_types = {"DEAL_TYPE_BUY", "DEAL_TYPE_SELL"}
            return sum(float(d.get("profit", 0)) for d in deals if d.get("type") in trade_types)
    except Exception as e:
        logger.error(f"Error obteniendo P&L diario: {e}")
        return 0.0


async def has_open_position(symbol: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=15, verify=False) as client:
            r = await client.get(_account_url("positions"), headers=_headers())
            r.raise_for_status()
            return any(p["symbol"] == symbol for p in r.json())
    except Exception as e:
        logger.error(f"Error verificando posiciones: {e}")
        return False


async def open_trade(symbol: str, signal: str, entry_price: float, balance: float) -> dict | None:
    try:
        if signal == "BUY":
            sl = round(entry_price * (1 - SL_PCT), 5)
            tp = round(entry_price * (1 + TP_PCT), 5)
            action = "ORDER_TYPE_BUY"
        else:
            sl = round(entry_price * (1 + SL_PCT), 5)
            tp = round(entry_price * (1 - TP_PCT), 5)
            action = "ORDER_TYPE_SELL"

        lots = calculate_lot_size(balance, entry_price, sl, symbol)

        payload = {
            "actionType": action,
            "symbol": symbol,
            "volume": lots,
            "stopLoss": sl,
            "takeProfit": tp,
            "comment": "ForexSense",
        }

        async with httpx.AsyncClient(timeout=15, verify=False) as client:
            r = await client.post(_account_url("trade"), headers=_headers(), json=payload)
            r.raise_for_status()

        logger.info(f"{symbol}: orden {signal} abierta — {lots} lots | TP={tp} | SL={sl}")
        return {"lots": lots, "sl": sl, "tp": tp}

    except Exception as e:
        logger.error(f"{symbol}: error abriendo orden — {e}")
        return None
