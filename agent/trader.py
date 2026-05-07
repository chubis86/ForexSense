import logging
import os
from datetime import datetime, timezone

from metaapi_cloud_sdk import MetaApi

logger = logging.getLogger(__name__)

RISK_PCT = 0.01
TP_PCT = 0.02
SL_PCT = 0.01
DAILY_TARGET_PCT = 0.02

# Exness standard account symbol names
SYMBOL_MAP = {
    "BTC/USD": "BTCUSD",
    "ETH/USD": "ETHUSD",
    "XAU/USD": "XAUUSD",
    "EUR/USD": "EURUSD",
}

# Units per standard lot on Exness
CONTRACT_SIZES = {
    "BTCUSD": 1,
    "ETHUSD": 1,
    "XAUUSD": 100,
    "EURUSD": 100_000,
}


def calculate_lot_size(balance: float, entry_price: float, sl_price: float, symbol: str) -> float:
    """Risk-based lot sizing: balance * 1% / (sl_distance * contract_size)."""
    risk_amount = balance * RISK_PCT
    sl_distance = abs(entry_price - sl_price)
    if sl_distance == 0:
        return 0.01
    contract_size = CONTRACT_SIZES.get(symbol, 100_000)
    lots = risk_amount / (sl_distance * contract_size)
    return max(0.01, min(round(lots, 2), 10.0))


async def connect():
    """Returns (api, connection) or (None, None) on failure."""
    try:
        api = MetaApi(os.environ["METAAPI_TOKEN"])
        account = await api.metatrader_account_api.get_account(os.environ["METAAPI_ACCOUNT_ID"])
        if account.state not in ("DEPLOYING", "DEPLOYED"):
            await account.deploy()
        await account.wait_connected()
        conn = account.get_rpc_connection()
        await conn.connect()
        await conn.wait_synchronized({"timeoutInSeconds": 60})
        logger.info("MetaAPI: conectado")
        return api, conn
    except Exception as e:
        logger.error(f"MetaAPI: error de conexión — {e}")
        return None, None


async def get_balance(conn) -> float:
    info = await conn.get_account_information()
    return float(info["balance"])


async def get_daily_profit(conn) -> float:
    """Sum of realized P&L from closed trades today (UTC)."""
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    now = datetime.now(timezone.utc)
    try:
        deals = await conn.get_deals_by_time_range(today, now)
        trade_types = {"DEAL_TYPE_BUY", "DEAL_TYPE_SELL"}
        return sum(float(d.get("profit", 0)) for d in deals if d.get("type") in trade_types)
    except Exception as e:
        logger.error(f"Error obteniendo P&L diario: {e}")
        return 0.0


async def has_open_position(conn, symbol: str) -> bool:
    try:
        positions = await conn.get_positions()
        return any(p["symbol"] == symbol for p in positions)
    except Exception as e:
        logger.error(f"Error verificando posiciones abiertas: {e}")
        return False


async def open_trade(conn, symbol: str, signal: str, entry_price: float, balance: float) -> dict | None:
    """Opens a market order with automatic TP/SL. Returns trade details or None on failure."""
    try:
        if signal == "BUY":
            sl = round(entry_price * (1 - SL_PCT), 5)
            tp = round(entry_price * (1 + TP_PCT), 5)
        else:
            sl = round(entry_price * (1 + SL_PCT), 5)
            tp = round(entry_price * (1 - TP_PCT), 5)

        lots = calculate_lot_size(balance, entry_price, sl, symbol)

        if signal == "BUY":
            await conn.create_market_buy_order(symbol, lots, sl, tp, {"comment": "ForexSense"})
        else:
            await conn.create_market_sell_order(symbol, lots, sl, tp, {"comment": "ForexSense"})

        logger.info(f"{symbol}: orden {signal} abierta — {lots} lots | TP={tp} | SL={sl}")
        return {"lots": lots, "sl": sl, "tp": tp}
    except Exception as e:
        logger.error(f"{symbol}: error abriendo orden — {e}")
        return None
